"""Shared adapter artifact types."""

from __future__ import annotations

from typing import TypeAlias

AdapterRecord: TypeAlias = dict[str, object]
AdapterRecords: TypeAlias = list[AdapterRecord]
AdapterArtifact: TypeAlias = dict[str, object]
AdapterArtifacts: TypeAlias = list[AdapterArtifact]

__all__ = ["AdapterArtifact", "AdapterArtifacts", "AdapterRecord", "AdapterRecords"]
