import json
import os
import sqlite3

from app.pipeline.domain import (
    ContentBrief,
    ContentProject,
    PipelineEvent,
    PipelineRun,
    ProjectSnapshot,
    ScriptCandidate,
    utc_now,
)
from app.pipeline.repository import PipelineRepository


class SQLitePipelineRepository(PipelineRepository):
    """Single-host durable repository for quality-pipeline metadata."""

    def __init__(self, database_path: str):
        self.database_path = os.path.realpath(database_path)
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_projects (
                    project_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES content_projects(project_id)
                );
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project
                    ON pipeline_runs(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS pipeline_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, version),
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_run
                    ON pipeline_candidates(run_id, version);
                CREATE TABLE IF NOT EXISTS pipeline_events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    candidate_id TEXT,
                    stage TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_project
                    ON pipeline_events(project_id, created_at);
                """
            )

    @staticmethod
    def _dump(model) -> str:
        return json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def create_project(self, project: ContentProject) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO content_projects(project_id, payload, updated_at) VALUES (?, ?, ?)",
                (project.project_id, self._dump(project), project.updated_at),
            )

    def get_project(self, project_id: str) -> ContentProject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM content_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return ContentProject.model_validate_json(row["payload"]) if row else None

    def list_projects(self, limit: int = 30) -> list[ContentProject]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM content_projects ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [ContentProject.model_validate_json(row["payload"]) for row in rows]

    def update_project(self, project: ContentProject) -> None:
        project.updated_at = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE content_projects SET payload = ?, updated_at = ? WHERE project_id = ?",
                (self._dump(project), project.updated_at, project.project_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown project: {project.project_id}")

    def create_run(self, run: PipelineRun) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pipeline_runs(run_id, project_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                (run.run_id, run.project_id, self._dump(run), run.updated_at),
            )

    def get_run(self, run_id: str) -> PipelineRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM pipeline_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return PipelineRun.model_validate_json(row["payload"]) if row else None

    def update_run(self, run: PipelineRun) -> None:
        run.updated_at = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE pipeline_runs SET payload = ?, updated_at = ? WHERE run_id = ?",
                (self._dump(run), run.updated_at, run.run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown run: {run.run_id}")

    def save_brief(self, run_id: str, brief: ContentBrief) -> None:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        run.brief = brief
        self.update_run(run)

    def save_candidate(self, candidate: ScriptCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pipeline_candidates(
                    candidate_id, run_id, version, payload, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET payload = excluded.payload
                """,
                (
                    candidate.candidate_id,
                    candidate.run_id,
                    candidate.version,
                    self._dump(candidate),
                    candidate.created_at,
                ),
            )

    def list_candidates(self, run_id: str) -> list[ScriptCandidate]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM pipeline_candidates WHERE run_id = ? ORDER BY version",
                (run_id,),
            ).fetchall()
        return [ScriptCandidate.model_validate_json(row["payload"]) for row in rows]

    def append_event(self, event: PipelineEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pipeline_events(
                    event_id, project_id, run_id, candidate_id, stage,
                    event_type, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.run_id,
                    event.candidate_id,
                    event.stage.value,
                    event.event_type,
                    json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
                    event.created_at,
                ),
            )

    def get_snapshot(self, project_id: str) -> ProjectSnapshot | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        with self._connect() as connection:
            run_rows = connection.execute(
                "SELECT payload FROM pipeline_runs WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            event_rows = connection.execute(
                "SELECT * FROM pipeline_events WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        runs = [PipelineRun.model_validate_json(row["payload"]) for row in run_rows]
        candidates = [
            candidate
            for run in runs
            for candidate in self.list_candidates(run.run_id)
        ]
        events = [
            PipelineEvent(
                event_id=row["event_id"],
                project_id=row["project_id"],
                run_id=row["run_id"],
                candidate_id=row["candidate_id"],
                stage=row["stage"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in event_rows
        ]
        return ProjectSnapshot(
            project=project,
            runs=runs,
            candidates=candidates,
            events=events,
        )
