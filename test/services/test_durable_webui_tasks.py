from pathlib import Path
from unittest.mock import patch

import yaml

from app.models import const
from app.models.schema import VideoParams
from app.services import state as state_service
from app.services import webui_task, webui_worker


ROOT_DIR = Path(__file__).parent.parent.parent


def test_sqlite_state_is_visible_across_process_instances(tmp_path):
    database = tmp_path / "task-state.sqlite3"
    writer = state_service.SQLiteState(str(database))
    reader = state_service.SQLiteState(str(database))

    writer.update_task(
        "durable-state-task",
        state=const.TASK_STATE_PROCESSING,
        progress=20,
        video_subject="durable background task",
    )
    assert reader.get_task("durable-state-task") == {
        "task_id": "durable-state-task",
        "state": const.TASK_STATE_PROCESSING,
        "progress": 20,
        "video_subject": "durable background task",
    }

    assert reader.patch_task("durable-state-task", progress=55)
    assert writer.get_task("durable-state-task")["progress"] == 55


def test_submit_generation_persists_job_before_returning(tmp_path):
    task_id = "91e4e3f4-1b72-4aca-97eb-e7b80a584eb6"
    params = VideoParams(video_subject="persisted queue test")
    state = state_service.MemoryState()

    with (
        patch.object(webui_task, "_job_root", return_value=str(tmp_path)),
        patch.object(webui_task.sm, "state", state),
    ):
        webui_task.submit_generation(task_id, params, capture_logs=True)

    job_path = tmp_path / "pending" / f"{task_id}.pkl"
    assert job_path.is_file()
    job = webui_worker.load_job(str(job_path))
    assert job["task_id"] == task_id
    assert job["params"] == params
    assert job["capture_logs"] is True
    assert state.get_task(task_id)["state"] == const.TASK_STATE_PROCESSING


def test_worker_claims_and_executes_job_without_submitter_memory(tmp_path):
    task_id = "2b6490c4-f18e-4fd0-933b-64db22d0eab8"
    params = VideoParams(video_subject="detached worker test")
    pending = tmp_path / "pending"
    running = tmp_path / "running"
    pending.mkdir(parents=True)
    running.mkdir(parents=True)
    webui_worker.write_job(
        str(pending / f"{task_id}.pkl"),
        {
            "task_id": task_id,
            "params": params,
            "capture_logs": False,
            "voice_preview": None,
        },
    )

    claimed = webui_worker.claim_next_job(str(tmp_path))
    assert claimed == str(running / f"{task_id}.pkl")

    captured = {}

    def run_generation(**kwargs):
        captured.update(kwargs)
        return {"videos": ["final-1.mp4"]}

    result = webui_worker.execute_job_file(claimed, run_generation=run_generation)
    assert result == {"videos": ["final-1.mp4"]}
    assert captured["task_id"] == task_id
    assert captured["params"] == params
    assert captured["capture_logs"] is False


def test_task_logs_are_persisted_and_tail_is_bounded(tmp_path):
    task_log = tmp_path / "task.log"
    with patch.object(webui_task, "task_log_path", return_value=str(task_log)):
        for index in range(8):
            webui_task._append_task_log("durable-log-task", f"line-{index}\n")
        assert webui_task.get_task_logs("durable-log-task", limit=3) == [
            "[task_id=durable-log-task] line-5",
            "[task_id=durable-log-task] line-6",
            "[task_id=durable-log-task] line-7",
        ]

    assert task_log.read_text(encoding="utf-8").splitlines()[-1] == (
        "[task_id=durable-log-task] line-7"
    )


def test_recover_running_jobs_returns_jobs_to_pending(tmp_path):
    task_id = "7a9d5817-acce-44b4-994e-baa820a38ac4"
    running = tmp_path / "running"
    running.mkdir(parents=True)
    job_path = running / f"{task_id}.pkl"
    job_path.write_bytes(b"job")

    recovered = webui_worker.recover_running_jobs(str(tmp_path))

    assert recovered == 1
    assert not job_path.exists()
    assert (tmp_path / "pending" / f"{task_id}.pkl").read_bytes() == b"job"


def test_worker_entrypoint_is_independent_from_streamlit_session_state():
    worker_source = Path(webui_worker.__file__).read_text(encoding="utf-8")
    assert "streamlit" not in worker_source
    assert "session_state" not in worker_source


def test_saas_compose_runs_worker_with_shared_state_and_queue():
    compose = yaml.safe_load(
        (ROOT_DIR / "docker-compose.saas.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert services["worker"]["command"][-1] == "run"
    for service_name in ("webui", "worker"):
        environment = services[service_name]["environment"]
        assert environment["MPT_STATE_BACKEND"] == "sqlite"
        assert environment["MPT_WEBUI_JOB_ROOT"].endswith("/storage/webui_jobs")
        assert "./storage:/MoneyPrinterTurbo/storage" in services[service_name][
            "volumes"
        ]


def test_history_card_shows_task_id_and_persisted_logs():
    main_source = (ROOT_DIR / "webui" / "Main.py").read_text(encoding="utf-8")
    assert "st.caption(f\"{tr('Task ID')} · `{task_id}`\")" in main_source
    assert "webui_task.get_task_logs(task_id, limit=120)" in main_source
