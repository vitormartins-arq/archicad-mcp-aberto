"""MCP server entry point (stdio)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from archicad_mcp_aberto.connection import ArchicadClient, ports_from_env
from archicad_mcp_aberto.tools import attributes, read, write

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

    @mcp.tool(annotations=READ_ONLY)
    async def get_bounding_boxes(
        ctx: Context,
        element_ids: list[str],
        port: int | None = None,
        mode: Literal["2d", "3d"] = "2d",
    ) -> dict:
        """Read 2D/3D boxes in metres for 1 to 500 GUIDs; errors per element.
        Official JSON API, no Tapir required. Changes nothing."""
        return await read.get_bounding_boxes(client_of(ctx), element_ids, port, mode)

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

    @mcp.tool(annotations=READ_ONLY)
    async def list_building_materials(
        ctx: Context, port: int | None = None, attribute_guids: list[str] | None = None
    ) -> dict:
        """List material GUID/index/name and cut-fill index/foreground/background pens.
        Requires Tapir 1.7.0. Optional GUID filter; changes nothing."""
        return await attributes.list_building_materials(client_of(ctx), port, attribute_guids)

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

    @mcp.tool(annotations=WRITE)
    async def create_columns(
        ctx: Context,
        columns: list[write.ColumnCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 straight rectangular/circular columns, in metres.
        base_level is absolute project Z. Requires Tapir; review then apply identical
        inputs with explicit port and single-use token. Verifies each column; never saves."""
        return await write.create_columns(
            client_of(ctx), columns, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_objects(
        ctx: Context,
        objects: list[write.ObjectCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 library part objects by exact name, in metres and radians.
        base_level is absolute project Z; size stays the part's default. Requires Tapir;
        review then apply identical inputs with explicit port and single-use token.
        An unknown name fails only that object. Verifies each object; never saves."""
        return await write.create_objects(
            client_of(ctx), objects, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def move_elements(
        ctx: Context,
        moves: list[write.ElementMove],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview moving up to 50 elements, each by its own vector {x, y, z} in metres.
        Never copies. Refuses hotlinked or unknown elements. Review, then apply identical
        inputs with explicit port and single-use token; checks each box moved; never saves."""
        return await write.move_elements(client_of(ctx), moves, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def set_property_values(
        ctx: Context,
        changes: list[write.PropertyChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview setting up to 100 property values: element_guid, property_guid, value.
        Text, number, integer, boolean, length, area, volume or angle; lists and enums are
        refused. Preview shows current and new values; apply identical inputs with explicit
        port and single-use token; every value is read back. Never saves."""
        return await write.set_property_values(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def find_elements(
        ctx: Context,
        port: int | None = None,
        element_type: str | None = None,
        floor_index: int | None = None,
        layer_index: int | None = None,
        property_guid: str | None = None,
        operator: Literal["equal", "contains", "greater", "less"] = "equal",
        value: str | int | float | bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Filter type/story/layer and scalar properties; pages up to 500, batches of 100."""
        return await read.find_elements(
            client_of(ctx),
            port,
            element_type,
            floor_index,
            layer_index,
            property_guid,
            operator,
            value,
            offset,
            limit,
        )

    @mcp.tool(annotations=WRITE)
    async def delete_elements(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Delete up to 50 editable elements, only in an untitled test project. Requires Tapir.
        Preview then apply with explicit port and single-use token. Never saves or unlocks.
        """
        return await write.delete_elements(
            client_of(ctx), element_guids, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_beams(
        ctx: Context,
        beams: list[write.BeamCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview straight rectangular beams, up to 20. Metres; level is absolute Z.
        Requires Tapir, explicit port and single-use token to apply; never saves.
        """
        return await write.create_beams(client_of(ctx), beams, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_zones(
        ctx: Context,
        zones: list[write.ZoneCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 manual zones with simple polygons in metres, name/number/story.
        Requires Tapir and explicit port/single-use token to apply. Never saves.
        """
        return await write.create_zones(client_of(ctx), zones, port, dry_run, confirmation_token)

    @mcp.tool(annotations=READ_ONLY)
    async def list_library_parts(
        ctx: Context,
        port: int | None = None,
        name_contains: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """List available library part names/GUIDs/types. Requires Tapir; no model changes.
        Pages up to 500; optional name substring and partial-inventory diagnostics.
        """
        return await read.list_library_parts(client_of(ctx), port, name_contains, offset, limit)

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
