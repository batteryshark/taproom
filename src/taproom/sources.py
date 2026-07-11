from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable

from .models import Capability


FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
FIELD = re.compile(r"^(name|description):\s*(.+?)\s*$")


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


def _source_specs(variable: str, defaults: Iterable[tuple[str, Path]]) -> list[tuple[str, Path]]:
    raw = os.environ.get(variable)
    if not raw:
        return [(name, path.resolve()) for name, path in defaults if path.is_dir()]
    specs: list[tuple[str, Path]] = []
    for item in raw.split(os.pathsep):
        if not item:
            continue
        name, separator, path = item.partition("=")
        if not separator:
            path = name
            name = Path(path).name
        specs.append((name, Path(path).expanduser().resolve()))
    return specs


def default_skill_sources() -> list[tuple[str, Path]]:
    workspace = Path(__file__).resolve().parents[3]
    return _source_specs(
        "TAPROOM_SKILL_ROOTS",
        (
            ("skilltap", workspace / "skill-tap" / "skills"),
            ("skilltap-private", workspace / "skill-tap-private" / "skills"),
        ),
    )


def default_mcp_sources() -> list[tuple[str, Path]]:
    workspace = Path(__file__).resolve().parents[3]
    return _source_specs(
        "TAPROOM_MCP_ROOTS",
        (
            ("mcptap", workspace / "mcp-tap" / "servers"),
            ("mcptap-private", workspace / "mcp-tap-private" / "servers"),
        ),
    )


def load_skills(sources: Iterable[tuple[str, Path]]) -> list[Capability]:
    capabilities: list[Capability] = []
    for source, root in sources:
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("SKILL.md")):
            package = entry.parent
            fields = _frontmatter(entry)
            name = fields.get("name", package.name)
            description = fields.get("description", "")
            category = package.relative_to(root).parts[0] if package != root else ""
            capabilities.append(
                Capability(
                    id=f"{source}:skill:{name}",
                    kind="skill",
                    source=source,
                    name=name,
                    description=description,
                    category=category,
                    path=package,
                )
            )
    return capabilities


def load_mcp_servers(sources: Iterable[tuple[str, Path]]) -> list[Capability]:
    capabilities: list[Capability] = []
    for source, root in sources:
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("server.json")):
            try:
                manifest = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = manifest.get("name", entry.parent.name)
            capabilities.append(
                Capability(
                    id=f"{source}:mcp:{name}",
                    kind="mcp",
                    source=source,
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


def skill_manifest(capability: Capability) -> dict:
    files = []
    for path in sorted(capability.path.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(capability.path).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "hash": f"sha256:{digest}",
                "executable": os.access(path, os.X_OK),
            }
        )
    return {"capability": capability.to_dict(), "files": files}

