from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.persistence.contracts import ArtifactReference


class ArtifactRepository:
    def __init__(self, *, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def persist_bytes(
        self,
        *,
        run_id: int,
        url_result_id: int,
        name: str,
        content: bytes,
    ) -> ArtifactReference:
        safe_name = Path(name).name
        if not safe_name or safe_name != name:
            raise ValueError("artifact name must be a plain file name")
        relative = (
            Path("runs")
            / str(max(run_id, 0))
            / "results"
            / str(url_result_id)
            / safe_name
        )
        target = self.resolve_uri(relative.as_posix())
        self._atomic_write(target, bytes(content))
        return ArtifactReference(
            name=safe_name,
            uri=relative.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    def resolve_uri(self, uri: str) -> Path:
        raw_uri = str(uri or "").strip()
        if not raw_uri:
            raise ValueError("artifact URI must be a non-empty relative path")
        relative = Path(raw_uri)
        if relative.is_absolute():
            raise ValueError("artifact URI must be a non-empty relative path")
        root = self._root_dir.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("artifact URI escapes the configured artifact root")
        return target

    def remove_run_tree(self, run_id: int) -> None:
        """Remove runs/{run_id}/ from the artifact root (ignore-errors).

        This repository is the single owner of the on-disk layout
        (INVARIANTS §12), so the runs/{run_id}/ path is built here.
        """
        relative = (Path("runs") / str(max(int(run_id), 0))).as_posix()
        shutil.rmtree(self.resolve_uri(relative), ignore_errors=True)

    def read_bytes(self, uri: str) -> bytes:
        return self.resolve_uri(uri).read_bytes()

    def read_text(self, uri: str) -> str:
        return self.resolve_uri(uri).read_text(encoding="utf-8")

    def read_json(self, uri: str) -> Any:
        return json.loads(self.read_text(uri))

    def reference_exists(self, reference: ArtifactReference) -> bool:
        path = self.resolve_uri(reference.uri)
        if not path.is_file():
            return False
        content = path.read_bytes()
        return (
            len(content) == reference.size_bytes
            and hashlib.sha256(content).hexdigest() == reference.sha256
        )

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
