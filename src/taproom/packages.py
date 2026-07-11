from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

from .models import Capability


PEP723 = re.compile(r"(?ms)^# /// script\s*$\n(?P<body>.*?)^# ///\s*$")
EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def package_manifest(capability: Capability) -> dict:
    result = {
        "capability": capability.to_dict(),
        "files": _files(capability.path),
    }
    if capability.kind == "mcp":
        result["plan"] = _mcp_plan(capability)
    return result


def _files(root: Path) -> list[dict]:
    files = []
    for path in sorted(root.rglob("*")):
        if not package_file_allowed(root, path) or not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                "executable": os.access(path, os.X_OK),
            }
        )
    return files


def package_file_allowed(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if path.is_symlink() or any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
        return False
    name = relative.name
    if name in {".DS_Store", ".envrc"} or name.endswith((".env", ".pyc", ".pyo")):
        return False
    if name.startswith(".env.") and name not in {".env.example", ".env.sample"}:
        return False
    return True


def _mcp_plan(capability: Capability) -> dict:
    manifest = capability.metadata
    declared = isinstance(manifest.get("requirements"), dict)
    unresolved = []
    if not declared:
        unresolved.append(
            "server.json has no structured requirements; review README and package files before activation"
        )
    if not isinstance(manifest.get("launch"), dict):
        unresolved.append("server.json has no launch configuration")
    return {
        "runtime": manifest.get("runtime"),
        "transport": manifest.get("transport"),
        "launch": manifest.get("launch"),
        "auth": manifest.get("auth"),
        "env": manifest.get("env", []),
        "requirements_declared": declared,
        "requirements": manifest.get("requirements", {}),
        "detected_dependencies": _dependencies(capability.path),
        "unresolved": unresolved,
    }


def _dependencies(root: Path) -> dict:
    python: set[str] = set()
    node: set[str] = set()
    files: list[str] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        files.append("pyproject.toml")
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
            python.update(project.get("dependencies", []))
        except (OSError, tomllib.TOMLDecodeError):
            pass

    package_json = root / "package.json"
    if package_json.is_file():
        files.append("package.json")
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            for group in ("dependencies", "optionalDependencies"):
                node.update(f"{name}@{version}" for name, version in package.get(group, {}).items())
        except (OSError, json.JSONDecodeError):
            pass

    for lockfile in ("uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"):
        if (root / lockfile).is_file():
            files.append(lockfile)

    for script in sorted(root.glob("*.py")):
        try:
            match = PEP723.search(script.read_text(encoding="utf-8"))
            if not match:
                continue
            body = "\n".join(line.removeprefix("# ").removeprefix("#") for line in match.group("body").splitlines())
            metadata = tomllib.loads(body)
            python.update(metadata.get("dependencies", []))
            files.append(script.name)
        except (OSError, tomllib.TOMLDecodeError):
            continue

    if (root / "README.md").is_file():
        files.append("README.md")
    return {
        "python": sorted(python),
        "node": sorted(node),
        "files": sorted(set(files)),
    }
