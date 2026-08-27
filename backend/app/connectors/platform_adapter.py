"""Contract shared by deterministic platform evidence adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field


def node_text(node: object, *, separator: str = "") -> str:
    text_fn = getattr(node, "text", None)
    if not callable(text_fn):
        return ""
    try:
        kwargs: dict[str, object] = {"strip": True}
        if separator:
            kwargs["separator"] = separator
        return str(text_fn(**kwargs) or "")
    except Exception:
        return ""


def node_attr(node: object, name: str) -> str | None:
    attrs = getattr(node, "attributes", {}) or {}
    value = attrs.get(name) if isinstance(attrs, Mapping) else None
    return str(value).strip() or None if value is not None else None


@dataclass(slots=True)
class AdapterResult:
    records: list[dict[str, object]] = field(default_factory=list)
    source_type: str = "adapter"
    adapter_name: str = ""

    @property
    def artifacts(self) -> list[dict[str, object]]:
        return [
            {
                "artifact_type": "adapter_json",
                "source_type": self.source_type,
                "adapter_name": self.adapter_name,
                "body": record,
            }
            for record in self.records
        ]


class BaseAdapter(ABC):
    name = "base"

    @abstractmethod
    async def can_handle(self, url: str, html: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def extract(
        self,
        url: str,
        html: str,
        surface: str,
        proxy: str | None = None,
    ) -> AdapterResult:
        raise NotImplementedError

    def result(self, records: list[dict[str, object]]) -> AdapterResult:
        return AdapterResult(
            records=records,
            source_type=f"{self.name}_adapter",
            adapter_name=self.name,
        )
