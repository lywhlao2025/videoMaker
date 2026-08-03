import json
import os
import tempfile
from pathlib import Path

from app.utils import utils


class ArtifactStore:
    def __init__(self, root: str | None = None):
        self.root = Path(root or utils.storage_dir("projects", create=True)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, project_id: str, run_id: str) -> Path:
        return self.root / project_id / "runs" / run_id

    def write_json(
        self,
        project_id: str,
        run_id: str,
        relative_path: str,
        payload,
    ) -> str:
        run_dir = self.run_dir(project_id, run_id).resolve()
        destination = (run_dir / relative_path).resolve()
        try:
            if os.path.commonpath([str(run_dir), str(destination)]) != str(run_dir):
                raise ValueError("artifact path is outside the run directory")
        except ValueError as exc:
            raise ValueError("invalid artifact path") from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}-",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        return str(destination)
