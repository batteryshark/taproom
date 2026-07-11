from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


CapabilityKind = Literal["skill", "mcp"]
TapVisibility = Literal["public", "private"]


@dataclass(frozen=True)
class TapSource:
    name: str
    kind: CapabilityKind
    path: Path


@dataclass(frozen=True)
class Tap:
    name: str
    visibility: TapVisibility
    sources: tuple[TapSource, ...]


@dataclass(frozen=True)
class Capability:
    id: str
    kind: CapabilityKind
    tap: str
    source: str
    locator: str
    name: str
    description: str
    path: Path
    category: str = ""
    version: str = "unversioned"
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        value = asdict(self)
        value["tags"] = list(self.tags)
        if include_path:
            value["path"] = str(self.path)
        else:
            value.pop("path")
        return value
