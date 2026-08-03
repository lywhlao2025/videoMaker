"""Durable WebUI video worker backed by a shared filesystem queue."""

import argparse
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
from uuid import UUID

from loguru import logger


def _validated_task_id(value: object) -> str:
    return str(UUID(str(value)))


def _queue_directories(job_root: str) -> tuple[Path, Path]:
    root = Path(job_root).resolve()
    pending = root / "pending"
    running = root / "running"
    pending.mkdir(parents=True, exist_ok=True)
    running.mkdir(parents=True, exist_ok=True)
    return pending, running


def write_job(job_path: str, job: dict) -> None:
    """Atomically persist a trusted local worker payload."""
    destination = Path(job_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    task_id = _validated_task_id(job.get("task_id"))
    if destination.name != f"{task_id}.pkl":
        raise ValueError("job filename must match task id")

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{task_id}-",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            # Job files are created and consumed only inside the private application
            # storage mount. Pickle is used to preserve VideoParams and subtitle timing
            # objects; never load files supplied by users or another trust boundary.
            pickle.dump(job, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def load_job(job_path: str) -> dict:
    path = Path(job_path).resolve()
    with path.open("rb") as handle:
        job = pickle.load(handle)
    if not isinstance(job, dict):
        raise ValueError("invalid worker job payload")
    task_id = _validated_task_id(job.get("task_id"))
    if path.name != f"{task_id}.pkl":
        raise ValueError("job filename does not match task id")
    return job


def claim_next_job(job_root: str) -> str | None:
    pending, running = _queue_directories(job_root)
    candidates = sorted(
        pending.glob("*.pkl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    for candidate in candidates:
        destination = running / candidate.name
        try:
            os.replace(candidate, destination)
        except FileNotFoundError:
            continue
        return str(destination)
    return None


def recover_running_jobs(job_root: str) -> int:
    pending, running = _queue_directories(job_root)
    recovered = 0
    for job_path in sorted(running.glob("*.pkl")):
        destination = pending / job_path.name
        os.replace(job_path, destination)
        recovered += 1
    return recovered


def execute_job_file(
    job_path: str,
    run_generation: Callable | None = None,
):
    job = load_job(job_path)
    if run_generation is None and job.get("job_type") == "quality_pipeline":
        from app.pipeline.worker import execute_pipeline_job

        return execute_pipeline_job(job)

    if run_generation is None:
        from app.services import webui_task

        run_generation = webui_task._run_generation

    return run_generation(
        task_id=job["task_id"],
        params=job["params"],
        capture_logs=bool(job.get("capture_logs", True)),
        voice_preview=job.get("voice_preview"),
    )


def _mark_worker_process_failed(job_path: str, return_code: int) -> None:
    try:
        job = load_job(job_path)
        if job.get("job_type") == "quality_pipeline":
            from app.pipeline.worker import mark_pipeline_job_failed

            mark_pipeline_job_failed(job, return_code)
            return

        from app.models import const
        from app.services import state as sm

        task_id = job["task_id"]
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="worker_process",
            error=f"background worker exited with code {return_code}",
        )
    except Exception as exc:
        logger.exception(
            f"failed to persist worker process failure: "
            f"job_path={job_path}, error={exc}"
        )


def run_worker(job_root: str, poll_interval: float = 1.0) -> None:
    root = Path(job_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    recovered = recover_running_jobs(str(root))
    logger.info(f"durable WebUI worker started: root={root}, recovered={recovered}")

    heartbeat = root / "worker.ready"
    while True:
        heartbeat.touch()
        job_path = claim_next_job(str(root))
        if not job_path:
            time.sleep(poll_interval)
            continue

        task_id = Path(job_path).stem
        logger.info(f"background worker claimed task: task_id={task_id}")
        completed = subprocess.run(
            [sys.executable, "-m", "app.services.webui_worker", "execute", job_path],
            check=False,
        )
        if completed.returncode != 0:
            _mark_worker_process_failed(job_path, completed.returncode)
        try:
            os.remove(job_path)
        except FileNotFoundError:
            pass
        heartbeat.touch()


def main() -> int:
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo WebUI worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--job-root", default="")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("job_path")
    args = parser.parse_args()

    if args.command == "execute":
        execute_job_file(args.job_path)
        return 0

    default_job_root = os.getenv("MPT_WEBUI_JOB_ROOT", "").strip() or str(
        Path(__file__).resolve().parents[2] / "storage" / "webui_jobs"
    )
    run_worker(args.job_root or default_job_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
