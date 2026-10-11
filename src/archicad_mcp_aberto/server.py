"""MCP server entry point (stdio)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from archicad_mcp_aberto.connection import ArchicadClient, ports_from_env
from archicad_mcp_aberto.tools import read, write

INSTRUCTIONS = """\
Archicad MCP (read tools and safe wall and slab creation).
- Call discover_archicad first. It lists open instances with port, version, Tapir state
  and project name.
- With several instances open, ask the user which project to use and pass its port.
  Never pick the first one. Ports are not permanent identities.
- Lengths are in meters and angles in radians (SI), whatever the project display units.
- "busy" (error 4001) means Archicad is in user input. Ask the user to finish, then retry.
  It does not mean an add-on is missing.
- Tools that say "requires Tapir" need the free Tapir add-on loaded (see tapir_status).
- Wall and slab writes dry-run by default. Show the plan to the user before applying, then
  repeat the same inputs with dry_run=false, the explicit port and confirmation_token.
  Tokens expire after ten minutes, work only in this session and can be consumed once.
- Receipts are local. No tool saves the Archicad project. After any unknown outcome,
  inspect the model before preparing a new plan; never blindly retry a write.
"""

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
WRITE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}


def create_server(client_factory: Callable[[], ArchicadClient] | None = None) -> FastMCP:
    factory = client_factory or (lambda: ArchicadClient(ports=ports_from_env()))

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
        async with factory() as client:
            yield {"client": client}

    mcp = FastMCP("archicad-mcp-aberto", instructions=INSTRUCTIONS, lifespan=lifespan)

    def client_of(ctx: Context) -> ArchicadClient:
        return ctx.request_context.lifespan_context["client"]

    @mcp.tool(annotations=READ_ONLY)
    async def discover_archicad(ctx: Context) -> dict:
        """List open Archicad instances: port, version, Tapir state, project name,
        element count and selection count. Changes nothing."""
        return await read.discover_archicad(client_of(ctx))

    @mcp.tool(annotations=READ_ONLY)
    async def list_elements(
        ctx: Context,
        port: int | None = None,
        element_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """List element GUIDs, optionally of one official type (Wall, Slab, Object, ...).
        Pages of up to 500."""
        return await read.list_elements(client_of(ctx), port, element_type, offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    async def get_selection(ctx: Context, port: int | None = None) -> dict:
        """Read the current selection without changing it."""
        return await read.get_selection(client_of(ctx), port)

    @mcp.tool(annotations=READ_ONLY)
    async def list_properties(
        ctx: Context, port: int | None = None, offset: int = 0, limit: int = 100
    ) -> dict:
        """List property definitions and their GUIDs. Pages of up to 200."""
        return await read.list_properties(client_of(ctx), port, offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    async def get_properties(
        ctx: Context,
        element_guids: list[str],
        property_guids: list[str],
        port: int | None = None,
    ) -> dict:
        """Read property values: up to 100 elements and 30 properties per call.
        Errors are reported per item. Save the project first on Archicad 29: some
        builds have crashed on large property reads."""
        return await read.get_properties(client_of(ctx), element_guids, property_guids, port)

    @mcp.tool(annotations=READ_ONLY)
    async def tapir_status(ctx: Context) -> dict:
        """Check in each instance whether the Tapir add-on is loaded, and its version."""
        return await read.tapir_status(client_of(ctx))

    @mcp.tool(annotations=READ_ONLY)
    async def get_project_info(ctx: Context, port: int | None = None) -> dict:
        """Project name, path and Teamwork state. Requires Tapir."""
        return await read.get_project_info(client_of(ctx), port)

    @mcp.tool(annotations=READ_ONLY)
    async def get_stories(ctx: Context, port: int | None = None) -> dict:
        """Stories and their levels. Requires Tapir."""
        return await read.get_stories(client_of(ctx), port)

    @mcp.tool(annotations=READ_ONLY)
    async def get_element_details(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        fields: list[str] | None = None,
    ) -> dict:
        """BIM details of up to 100 elements. Requires Tapir. Fields: type, id, floorIndex,
        layerIndex, drawIndex, details, hotlinkId, floorPlanPolygons. floorPlanPolygons is
        slow and only returned when asked for."""
        return await read.get_element_details(client_of(ctx), element_guids, port, fields)

    @mcp.tool(annotations=WRITE)
    async def create_walls(
        ctx: Context,
        walls: list[write.WallCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview straight Basic walls (up to 20). All lengths are metres.
        Requires Tapir. Review the preview with the user, then repeat identical inputs
        with dry_run=false, explicit port and confirmation_token. New walls inherit the
        default layer and building material. Returns per-wall results and local receipts;
        verifies geometry after writing. Never saves the project."""
        return await write.create_walls(client_of(ctx), walls, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_slabs(
        ctx: Context,
        slabs: list[write.SlabCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 simple polygon slabs. Metres; level is absolute project Z.
        Requires Tapir. Straight edges, no holes, top reference plane; layer/material
        inherit defaults. Review before applying identical inputs with dry_run=false,
        explicit port and single-use confirmation_token. Verifies each slab and returns
        local receipts. Never saves the project."""
        return await write.create_slabs(client_of(ctx), slabs, port, dry_run, confirmation_token)

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
