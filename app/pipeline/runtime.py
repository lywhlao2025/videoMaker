import os

from app.pipeline.artifacts import ArtifactStore
from app.pipeline.facade import QualityPipeline
from app.pipeline.sqlite_repository import SQLitePipelineRepository
from app.utils import utils


def pipeline_database_path() -> str:
    return os.path.realpath(
        os.getenv(
            "MPT_PIPELINE_DB",
            os.path.join(utils.storage_dir(create=True), "pipeline.sqlite3"),
        )
    )


def pipeline_artifact_root() -> str:
    return os.path.realpath(
        os.getenv(
            "MPT_PIPELINE_ARTIFACT_ROOT",
            utils.storage_dir("projects", create=True),
        )
    )


def get_pipeline() -> QualityPipeline:
    return QualityPipeline(
        repository=SQLitePipelineRepository(pipeline_database_path()),
        artifacts=ArtifactStore(pipeline_artifact_root()),
    )
