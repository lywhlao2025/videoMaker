from abc import ABC, abstractmethod

from app.pipeline.domain import (
    ContentBrief,
    ContentProject,
    PipelineEvent,
    PipelineRun,
    ProjectSnapshot,
    ScriptCandidate,
)


class PipelineRepository(ABC):
    @abstractmethod
    def create_project(self, project: ContentProject) -> None: ...

    @abstractmethod
    def get_project(self, project_id: str) -> ContentProject | None: ...

    @abstractmethod
    def list_projects(self, limit: int = 30) -> list[ContentProject]: ...

    @abstractmethod
    def update_project(self, project: ContentProject) -> None: ...

    @abstractmethod
    def create_run(self, run: PipelineRun) -> None: ...

    @abstractmethod
    def get_run(self, run_id: str) -> PipelineRun | None: ...

    @abstractmethod
    def update_run(self, run: PipelineRun) -> None: ...

    @abstractmethod
    def save_brief(self, run_id: str, brief: ContentBrief) -> None: ...

    @abstractmethod
    def save_candidate(self, candidate: ScriptCandidate) -> None: ...

    @abstractmethod
    def list_candidates(self, run_id: str) -> list[ScriptCandidate]: ...

    @abstractmethod
    def append_event(self, event: PipelineEvent) -> None: ...

    @abstractmethod
    def get_snapshot(self, project_id: str) -> ProjectSnapshot | None: ...
