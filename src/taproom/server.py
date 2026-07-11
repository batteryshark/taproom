from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from .catalog import Catalog
from .models import Capability
from .sources import (
    default_mcp_sources,
    default_skill_sources,
    load_mcp_servers,
    load_skills,
    skill_manifest,
)


def build_catalog() -> tuple[Catalog, list[tuple[str, Path]]]:
    skill_sources = default_skill_sources()
    capabilities = load_skills(skill_sources) + load_mcp_servers(default_mcp_sources())
    return Catalog(capabilities), skill_sources


def create_server(catalog: Catalog | None = None, skill_sources: list[tuple[str, Path]] | None = None) -> FastMCP:
    if catalog is None or skill_sources is None:
        discovered_catalog, discovered_sources = build_catalog()
        catalog = catalog or discovered_catalog
        skill_sources = skill_sources or discovered_sources

    mcp = FastMCP("Taproom")
    # FastMCP discovers immediate child skill directories. SkillTap permits
    # arbitrary category/group nesting, so expose every discovered package's
    # parent as a provider root while preserving source precedence.
    roots: list[Path] = []
    seen_roots: set[Path] = set()
    for _, source_root in skill_sources:
        if not source_root.is_dir():
            continue
        for main_file in sorted(source_root.rglob("SKILL.md")):
            provider_root = main_file.parent.parent.resolve()
            if provider_root not in seen_roots:
                seen_roots.add(provider_root)
                roots.append(provider_root)
    if roots:
        mcp.add_provider(SkillsDirectoryProvider(roots=roots, supporting_files="template"))

    @mcp.tool
    def search_capabilities(query: str, kind: str | None = None, limit: int = 5) -> list[dict]:
        """Find skills or MCP servers by describing the capability you need."""
        if kind not in (None, "skill", "mcp"):
            raise ValueError("kind must be 'skill', 'mcp', or omitted")
        return catalog.search(query, kind=kind, limit=limit)

    @mcp.tool
    def inspect_capability(capability_id: str) -> dict:
        """Return metadata and, for skills, a file manifest for one capability."""
        capability = catalog.get(capability_id)
        if capability is None:
            raise ValueError(f"Unknown capability: {capability_id}")
        if capability.kind == "skill":
            return skill_manifest(capability)
        return capability.to_dict()

    @mcp.custom_route("/api/v1/search", methods=["GET"])
    async def api_search(request: Request):
        query = request.query_params.get("q", "")
        kind = request.query_params.get("kind") or None
        try:
            limit = int(request.query_params.get("limit", "5"))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        if kind not in (None, "skill", "mcp"):
            return JSONResponse({"error": "kind must be skill or mcp"}, status_code=400)
        return JSONResponse({"results": catalog.search(query, kind=kind, limit=limit)})

    @mcp.custom_route("/api/v1/capabilities/{source}/{kind}/{name}", methods=["GET"])
    async def api_capability(request: Request):
        capability = _route_capability(catalog, request)
        if capability is None:
            return JSONResponse({"error": "capability not found"}, status_code=404)
        if capability.kind == "skill":
            return JSONResponse(skill_manifest(capability))
        return JSONResponse(capability.to_dict())

    @mcp.custom_route("/api/v1/skills/{source}/{name}/files/{file_path:path}", methods=["GET"])
    async def api_skill_file(request: Request):
        capability = catalog.get(f"{request.path_params['source']}:skill:{request.path_params['name']}")
        if capability is None:
            return JSONResponse({"error": "skill not found"}, status_code=404)
        relative = Path(request.path_params["file_path"])
        if relative.is_absolute() or ".." in relative.parts:
            return JSONResponse({"error": "invalid path"}, status_code=400)
        target = (capability.path / relative).resolve()
        try:
            target.relative_to(capability.path.resolve())
        except ValueError:
            return JSONResponse({"error": "invalid path"}, status_code=400)
        if not target.is_file():
            return JSONResponse({"error": "file not found"}, status_code=404)
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return FileResponse(target, media_type=media_type)

    return mcp


def _route_capability(catalog: Catalog, request: Request) -> Capability | None:
    parts = request.path_params
    return catalog.get(f"{parts['source']}:{parts['kind']}:{parts['name']}")


mcp = create_server()


def main() -> None:
    host = os.environ.get("TAPROOM_HOST", "127.0.0.1")
    port = int(os.environ.get("TAPROOM_PORT", "8768"))
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
