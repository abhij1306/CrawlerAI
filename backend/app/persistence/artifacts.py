from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.persistence.contracts import ArtifactManifest, ArtifactReference


class ArtifactRepository:
    def __init__(self, *, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

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
        relative = Path("runs") / str(max(run_id, 0)) / "results" / str(url_result_id) / safe_name
        target = self._root_dir / relative
        self._atomic_write(target, bytes(content))
        return ArtifactReference(
            name=safe_name,
            uri=relative.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    def persist_manifest(self, manifest: ArtifactManifest) -> ArtifactReference:
        content = json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        return self.persist_bytes(
            run_id=manifest.run_id,
            url_result_id=manifest.url_result_id,
            name="manifest.json",
            content=content,
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
