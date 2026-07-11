from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillProvider
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from .catalog import Catalog
from .models import Capability, Tap
from .packages import package_file_allowed, package_manifest
from .sources import (
    load_capabilities,
    load_taps,
)


def build_runtime() -> tuple[Catalog, list[Tap]]:
    taps = load_taps()
    return Catalog(load_capabilities(taps)), taps


def create_server(catalog: Catalog | None = None, taps: list[Tap] | None = None) -> FastMCP:
    if catalog is None:
        catalog, discovered_taps = build_runtime()
        taps = taps or discovered_taps
    taps = taps or []
    inventory = _tap_inventory(catalog, taps)

    mcp = FastMCP("Taproom")
    for capability in catalog.capabilities:
        if capability.kind != "skill":
            continue
        skill_server = FastMCP(capability.id)
        skill_server.add_provider(SkillProvider(capability.path, supporting_files="template"))
        mcp.mount(skill_server, namespace=f"{capability.tap}~{capability.locator}")

    @mcp.tool
    def list_taps() -> list[dict]:
        """List configured taps, their visibility, sources, and capability counts."""
        return inventory

    @mcp.tool
    def search_capabilities(
        query: str,
        kind: str | None = None,
        tap: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find skills or MCP servers by describing the capability you need."""
        if kind not in (None, "skill", "mcp"):
            raise ValueError("kind must be 'skill', 'mcp', or omitted")
        return catalog.search(query, kind=kind, tap=tap, limit=limit)

    @mcp.tool
    def inspect_capability(capability_id: str) -> dict:
        """Return metadata, package files, and dependency planning for one capability."""
        capability = catalog.get(capability_id)
        if capability is None:
            raise ValueError(f"Unknown capability: {capability_id}")
        return package_manifest(capability)

    @mcp.tool
    def plan_mcp_server(capability_id: str) -> dict:
        """Return files, dependencies, host requirements, environment, and launch details for an MCP server."""
        capability = catalog.get(capability_id)
        if capability is None or capability.kind != "mcp":
            raise ValueError(f"Unknown MCP capability: {capability_id}")
        return package_manifest(capability)

    @mcp.custom_route("/api/v1/search", methods=["GET"])
    async def api_search(request: Request):
        query = request.query_params.get("q", "")
        kind = request.query_params.get("kind") or None
        tap = request.query_params.get("tap") or None
        try:
            limit = int(request.query_params.get("limit", "5"))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        if kind not in (None, "skill", "mcp"):
            return JSONResponse({"error": "kind must be skill or mcp"}, status_code=400)
        return JSONResponse({"results": catalog.search(query, kind=kind, tap=tap, limit=limit)})

    @mcp.custom_route("/api/v1/taps", methods=["GET"])
    async def api_taps(request: Request):
        return JSONResponse({"taps": inventory})

    @mcp.custom_route("/api/v1/capabilities/{tap}/{kind}/{locator}", methods=["GET"])
    async def api_capability(request: Request):
        capability = _route_capability(catalog, request)
        if capability is None:
            return JSONResponse({"error": "capability not found"}, status_code=404)
        return JSONResponse(package_manifest(capability))

    @mcp.custom_route(
        "/api/v1/packages/{tap}/{kind}/{locator}/files/{file_path:path}",
        methods=["GET"],
    )
    async def api_package_file(request: Request):
        parts = request.path_params
        capability = catalog.get(f"{parts['tap']}:{parts['kind']}:{parts['locator']}")
        return _file_response(capability, parts["file_path"])

    return mcp


def _file_response(capability: Capability | None, file_path: str):
    if capability is None:
        return JSONResponse({"error": "capability not found"}, status_code=404)
    relative = Path(file_path)
    if relative.is_absolute() or ".." in relative.parts:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    source = capability.path / relative
    if not package_file_allowed(capability.path, source):
        return JSONResponse({"error": "file not found"}, status_code=404)
    target = source.resolve()
    try:
        target.relative_to(capability.path.resolve())
    except ValueError:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"error": "file not found"}, status_code=404)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


def _route_capability(catalog: Catalog, request: Request) -> Capability | None:
    parts = request.path_params
    return catalog.get(f"{parts['tap']}:{parts['kind']}:{parts['locator']}")


def _tap_inventory(catalog: Catalog, taps: list[Tap]) -> list[dict]:
    configured = {tap.name: tap for tap in taps}
    names = sorted(set(configured) | {item.tap for item in catalog.capabilities})
    inventory = []
    for name in names:
        tap = configured.get(name)
        capabilities = [item for item in catalog.capabilities if item.tap == name]
        inventory.append(
            {
                "name": name,
                "visibility": tap.visibility if tap else "unspecified",
                "sources": [
                    {"name": source.name, "kind": source.kind}
                    for source in (tap.sources if tap else ())
                ],
                "skills": sum(item.kind == "skill" for item in capabilities),
                "mcp_servers": sum(item.kind == "mcp" for item in capabilities),
            }
        )
    return inventory


mcp = create_server()


def main() -> None:
    host = os.environ.get("TAPROOM_HOST", "127.0.0.1")
    port = int(os.environ.get("TAPROOM_PORT", "8768"))
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
