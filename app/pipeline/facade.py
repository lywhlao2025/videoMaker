from app.pipeline.artifacts import ArtifactStore
from app.pipeline.domain import (
    ContentProject,
    ContentTheme,
    PipelinePolicy,
    PipelineRun,
    ProjectSnapshot,
)
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.repository import PipelineRepository
from app.pipeline.stages.script import ScriptStage


class QualityPipeline:
    """Small external interface for callers and tests."""

    def __init__(
        self,
        repository: PipelineRepository,
        artifacts: ArtifactStore,
        script_stage: ScriptStage | None = None,
    ):
        self.repository = repository
        self.orchestrator = PipelineOrchestrator(
            repository=repository,
            script_stage=script_stage or ScriptStage(),
            artifacts=artifacts,
        )

    def create_project(
        self,
        *,
        title: str,
        topic: str,
        source_content: str,
        theme: ContentTheme | str,
        target_audience: str = "普通中文短视频用户",
        target_duration_seconds: int = 55,
        policy: PipelinePolicy | None = None,
    ) -> tuple[ContentProject, PipelineRun]:
        project = ContentProject(
            title=title.strip(),
            topic=topic.strip(),
            source_content=source_content.strip(),
            theme=ContentTheme(theme),
            target_audience=target_audience.strip(),
            target_duration_seconds=target_duration_seconds,
        )
        run = PipelineRun(project_id=project.project_id, policy=policy or PipelinePolicy())
        self.repository.create_project(project)
        self.repository.create_run(run)
        return project, run

    def execute(self, run_id: str) -> ProjectSnapshot:
        return self.orchestrator.run_script_loop(run_id)

    def get_project(self, project_id: str) -> ProjectSnapshot | None:
        return self.repository.get_snapshot(project_id)

    def list_projects(self, limit: int = 30) -> list[ContentProject]:
        return self.repository.list_projects(limit=limit)
