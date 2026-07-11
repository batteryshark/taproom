from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Iterable

from .models import Capability, Tap, TapSource


FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
FIELD = re.compile(r"^(name|description):\s*(.+?)\s*$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group("body").splitlines():
        field = FIELD.match(line)
        if field:
            result[field.group(1)] = field.group(2).strip().strip('"').strip("'")
    return result


def _legacy_source_specs(variable: str, kind: str) -> list[TapSource]:
    raw = os.environ.get(variable, "")
    sources: list[TapSource] = []
    for item in raw.split(os.pathsep):
        if not item:
            continue
        name, separator, path = item.partition("=")
        if not separator:
            path = name
            name = Path(path).name
        _validate_name(name, "source")
        sources.append(TapSource(name=name, kind=kind, path=Path(path).expanduser().resolve()))
    return sources


def default_taps() -> list[Tap]:
    workspace = Path(__file__).resolve().parents[3]
    sources = []
    for name, kind, path in (
        ("skilltap", "skill", workspace / "skill-tap" / "skills"),
        ("mcptap", "mcp", workspace / "mcp-tap" / "servers"),
    ):
        if path.is_dir():
            sources.append(TapSource(name=name, kind=kind, path=path.resolve()))
    return [Tap(name="public", visibility="public", sources=tuple(sources))]


def load_taps(config_path: str | Path | None = None) -> list[Tap]:
    explicit = config_path or os.environ.get("TAPROOM_CONFIG")
    candidate = Path(explicit).expanduser() if explicit else Path.cwd() / "taproom.toml"
    if candidate.is_file():
        return _load_tap_config(candidate.resolve())
    if explicit:
        raise FileNotFoundError(f"Taproom config not found: {candidate}")

    legacy_sources = _legacy_source_specs("TAPROOM_SKILL_ROOTS", "skill")
    legacy_sources += _legacy_source_specs("TAPROOM_MCP_ROOTS", "mcp")
    if legacy_sources:
        tap_name = os.environ.get("TAPROOM_TAP_NAME", "environment")
        visibility = os.environ.get("TAPROOM_TAP_VISIBILITY", "public")
        _validate_name(tap_name, "tap")
        _validate_visibility(visibility)
        return [Tap(name=tap_name, visibility=visibility, sources=tuple(legacy_sources))]
    return default_taps()


def _load_tap_config(path: Path) -> list[Tap]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("taproom.toml must set version = 1")
    taps: list[Tap] = []
    tap_names: set[str] = set()
    for item in data.get("taps", []):
        if not item.get("enabled", True):
            continue
        name = item.get("name", "")
        visibility = item.get("visibility", "public")
        _validate_name(name, "tap")
        _validate_visibility(visibility)
        if name in tap_names:
            raise ValueError(f"Duplicate tap name: {name}")
        tap_names.add(name)
        sources: list[TapSource] = []
        source_keys: set[tuple[str, str]] = set()
        for source in item.get("sources", []):
            if not source.get("enabled", True):
                continue
            source_name = source.get("name", "")
            kind = source.get("kind", "")
            _validate_name(source_name, "source")
            if kind not in ("skill", "mcp"):
                raise ValueError(f"Tap source {source_name!r} must use kind = 'skill' or 'mcp'")
            key = (kind, source_name)
            if key in source_keys:
                raise ValueError(f"Duplicate {kind} source {source_name!r} in tap {name!r}")
            source_keys.add(key)
            raw_path = source.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError(f"Tap source {source_name!r} must set a path")
            source_path = Path(raw_path).expanduser()
            if not source_path.is_absolute():
                source_path = path.parent / source_path
            source_path = source_path.resolve()
            if not source_path.is_dir():
                raise ValueError(f"Tap source directory does not exist: {source_path}")
            sources.append(TapSource(name=source_name, kind=kind, path=source_path))
        taps.append(Tap(name=name, visibility=visibility, sources=tuple(sources)))
    if not taps:
        raise ValueError("taproom.toml does not enable any taps")
    return taps


def _validate_name(name: str, label: str) -> None:
    if not NAME.fullmatch(name):
        raise ValueError(f"{label} name must use lowercase letters, digits, and hyphens: {name!r}")


def _validate_visibility(value: str) -> None:
    if value not in ("public", "private"):
        raise ValueError("tap visibility must be 'public' or 'private'")


def load_capabilities(taps: Iterable[Tap]) -> list[Capability]:
    capabilities: list[Capability] = []
    for tap in taps:
        for source in tap.sources:
            spec = [(tap.name, source.name, source.path)]
            if source.kind == "skill":
                capabilities.extend(load_skills(spec))
            else:
                capabilities.extend(load_mcp_servers(spec))
    return capabilities


def load_skills(sources: Iterable[tuple[str, str, Path]]) -> list[Capability]:
    capabilities: list[Capability] = []
    for tap, source, root in sources:
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("SKILL.md")):
            package = entry.parent
            relative = package.relative_to(root)
            locator = "~".join((source, *relative.parts))
            fields = _frontmatter(entry)
            name = fields.get("name", package.name)
            description = fields.get("description", "")
            category = relative.parts[0] if package != root else ""
            capabilities.append(
                Capability(
                    id=f"{tap}:skill:{locator}",
                    kind="skill",
                    tap=tap,
                    source=source,
                    locator=locator,
                    name=name,
                    description=description,
                    category=category,
                    path=package,
                )
            )
    return capabilities


def load_mcp_servers(sources: Iterable[tuple[str, str, Path]]) -> list[Capability]:
    capabilities: list[Capability] = []
    for tap, source, root in sources:
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("server.json")):
            try:
                manifest = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = manifest.get("name", entry.parent.name)
            locator = "~".join((source, *entry.parent.relative_to(root).parts))
            capabilities.append(
                Capability(
                    id=f"{tap}:mcp:{locator}",
                    kind="mcp",
                    tap=tap,
                    source=source,
                    locator=locator,
                    name=name,
                    description=manifest.get("description", ""),
                    category=manifest.get("category", ""),
                    version=str(manifest.get("version", "unversioned")),
                    tags=tuple(manifest.get("tags", ())),
                    path=entry.parent,
                    metadata=manifest,
                )
            )
    return capabilities
