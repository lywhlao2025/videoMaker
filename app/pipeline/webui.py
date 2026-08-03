import os

from app.config import config
from app.controllers.manager.base_manager import TaskQueueFullError
from app.pipeline.domain import ContentTheme, PipelinePolicy, ProjectStatus
from app.pipeline.runtime import get_pipeline
from app.services import webui_task, webui_worker


def create_and_submit_project(
    *,
    title: str,
    topic: str,
    source_content: str,
    theme: ContentTheme | str,
    target_audience: str,
    target_duration_seconds: int,
    policy: PipelinePolicy | None = None,
):
    pipeline = get_pipeline()
    project, run = pipeline.create_project(
        title=title,
        topic=topic,
        source_content=source_content,
        theme=theme,
        target_audience=target_audience,
        target_duration_seconds=target_duration_seconds,
        policy=policy,
    )
    try:
        job_root = webui_task._job_root()
        pending_dir = os.path.join(job_root, "pending")
        running_dir = os.path.join(job_root, "running")
        os.makedirs(pending_dir, exist_ok=True)
        os.makedirs(running_dir, exist_ok=True)
        queued_count = sum(
            1
            for directory in (pending_dir, running_dir)
            for name in os.listdir(directory)
            if name.endswith(".pkl")
        )
        max_queued_tasks = max(1, int(config.app.get("max_queued_tasks", 100)))
        if queued_count >= max_queued_tasks:
            raise TaskQueueFullError("task queue is full, please try again later")

        webui_worker.write_job(
            os.path.join(pending_dir, f"{run.run_id}.pkl"),
            {
                "job_type": "quality_pipeline",
                "task_id": run.run_id,
                "project_id": project.project_id,
                "run_id": run.run_id,
            },
        )
        return project, run
    except Exception as exc:
        project.status = ProjectStatus.failed
        run.status = ProjectStatus.failed
        run.error = f"{type(exc).__name__}: {exc}"
        pipeline.repository.update_project(project)
        pipeline.repository.update_run(run)
        raise
