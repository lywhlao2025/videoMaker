from app.pipeline.domain import PipelineEvent, PipelineStage, ProjectStatus
from app.pipeline.runtime import get_pipeline


def execute_pipeline_job(job: dict):
    pipeline = get_pipeline()
    return pipeline.execute(str(job["run_id"]))


def mark_pipeline_job_failed(job: dict, return_code: int) -> None:
    pipeline = get_pipeline()
    repository = pipeline.repository
    run = repository.get_run(str(job["run_id"]))
    if run is None:
        return
    project = repository.get_project(run.project_id)
    if project is None:
        return
    run.status = ProjectStatus.failed
    run.current_stage = PipelineStage.failed
    run.error = f"background worker exited with code {return_code}"
    project.status = ProjectStatus.failed
    repository.update_run(run)
    repository.update_project(project)
    repository.append_event(
        PipelineEvent(
            project_id=project.project_id,
            run_id=run.run_id,
            stage=PipelineStage.failed,
            event_type="worker_process_failed",
            payload={"return_code": return_code},
        )
    )
