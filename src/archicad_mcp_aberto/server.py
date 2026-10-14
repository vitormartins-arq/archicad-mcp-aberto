"""MCP server entry point (stdio)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from archicad_mcp_aberto.connection import ArchicadClient, ports_from_env
from archicad_mcp_aberto.tools import (
    attributes,
    classifications,
    documents,
    drafting,
    edit,
    favorites,
    gateway,
    locks,
    modify,
    openings,
    project_info,
    property_definitions,
    read,
    write,
)
from archicad_mcp_aberto.tools import issues as issues_tool
from archicad_mcp_aberto.tools import labels as labels_tool
from archicad_mcp_aberto.tools import layers as layers_tool
from archicad_mcp_aberto.tools import navigator as navigator_tool
from archicad_mcp_aberto.tools import renames as renames_tool
from archicad_mcp_aberto.tools import roofs as roofs_tool
from archicad_mcp_aberto.tools import selection as selection_tool
from archicad_mcp_aberto.tools import texts as texts_tool
from archicad_mcp_aberto.tools import zones as zones_tool

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
# Changes only what the user sees (selection, highlight), never the model.
VIEW = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
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
    async def list_classifications(
        ctx: Context,
        system: str | None = None,
        port: int | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        """Without system: the project's classification systems. With system (GUID or
        name): its items as a flat tree (guid, id code, name, parent_guid, depth); query
        filters id or name. Pages up to 500."""
        return await classifications.list_classifications(
            client_of(ctx), system, port, query, offset, limit
        )

    @mcp.tool(annotations=WRITE)
    async def set_classifications(
        ctx: Context,
        changes: list[classifications.ClassificationChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview classifying up to 100 elements: element_guid, system (GUID or name) and
        item (GUID, id code or name; null removes the classification in that system).
        Ambiguous names are refused. Preview shows current and new items; apply identical
        inputs with explicit port and single-use token; each is read back. Never saves."""
        return await classifications.set_classifications(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_layers(ctx: Context, port: int | None = None) -> dict:
        """List the project's layers: guid, index, name, hidden, locked, wireframe and
        intersection group. Requires Tapir."""
        return await layers_tool.list_layers(client_of(ctx), port)

    @mcp.tool(annotations=WRITE)
    async def create_layers(
        ctx: Context,
        layers: list[layers_tool.LayerCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 50 layers: name, optional hidden, locked, wireframe and
        intersection_group. A name the project already has is refused, never overwritten.
        Apply identical inputs with explicit port and single-use token; each layer is read
        back. Requires Tapir. Never saves."""
        return await layers_tool.create_layers(
            client_of(ctx), layers, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def set_element_layers(
        ctx: Context,
        changes: list[layers_tool.LayerMove],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview moving up to 100 editable elements to existing layers: element_guid and
        layer (name). Unknown or ambiguous names are refused. Preview shows current and new
        layer; apply identical inputs with explicit port and single-use token; each element
        is read back. Requires Tapir. Never saves."""
        return await layers_tool.set_element_layers(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=VIEW)
    async def select_elements(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        mode: Literal["replace", "add", "remove"] = "replace",
    ) -> dict:
        """Change the selection in Archicad: replace (an empty list clears it), add or
        remove up to 100 elements. Does not change the model; reports what ended selected.
        Requires Tapir."""
        return await selection_tool.select_elements(client_of(ctx), element_guids, port, mode)

    @mcp.tool(annotations=VIEW)
    async def highlight_elements(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        color: list[int] | None = None,
        wireframe_3d: bool | None = None,
    ) -> dict:
        """Highlight up to 100 elements in one color [r, g, b] or [r, g, b, a] (0-255,
        default red); an empty list clears the highlight. wireframe_3d shows the rest as
        wireframe in 3D. Does not change the model. Requires Tapir."""
        return await selection_tool.highlight_elements(
            client_of(ctx), element_guids, port, color, wireframe_3d
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_element_groups(
        ctx: Context, element_guids: list[str], port: int | None = None
    ) -> dict:
        """For up to 100 elements: the group that directly holds each one (null when
        ungrouped) and the members of those groups. Requires Tapir."""
        return await selection_tool.get_element_groups(client_of(ctx), element_guids, port)

    @mcp.tool(annotations=WRITE)
    async def create_groups(
        ctx: Context,
        groups: list[selection_tool.GroupCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview grouping elements: up to 20 groups, each with 2 or more element_guids
        (100 in all). Elements already in a group, locked or missing are refused. Apply
        identical inputs with explicit port and single-use token; each group's members
        are read back. Requires Tapir. Never saves."""
        return await selection_tool.create_groups(
            client_of(ctx), groups, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_project_info_fields(ctx: Context, port: int | None = None) -> dict:
        """Project Info fields (File > Info > Project Info) that title blocks show:
        id, visible name and value. Requires Tapir."""
        return await project_info.get_project_info_fields(client_of(ctx), port)

    @mcp.tool(annotations=WRITE)
    async def set_project_info_fields(
        ctx: Context,
        changes: list[project_info.ProjectInfoChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview setting up to 30 Project Info values: field (id, or visible name) and
        value (an empty value clears the field). Preview shows current and new values;
        apply identical inputs with explicit port and single-use token; every field is
        read back. Requires Tapir. Never saves."""
        return await project_info.set_project_info_fields(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_favorites(ctx: Context, element_type: str, port: int | None = None) -> dict:
        """Favorite names for one element type as Tapir names it (Wall, Slab, Column,
        Beam, Window, Door, Object, Zone, Roof and so on). Requires Tapir."""
        return await favorites.list_favorites(client_of(ctx), element_type, port)

    @mcp.tool(annotations=WRITE)
    async def apply_favorites(
        ctx: Context,
        changes: list[favorites.FavoriteApply],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview applying favorites to up to 50 editable elements: element_guid and
        favorite (a name of that element's type). Applies settings, classifications,
        categories and properties, never geometry. Apply identical inputs with explicit
        port and single-use token. Results stay unverified: check them in Archicad.
        Requires Tapir. Never saves."""
        return await favorites.apply_favorites(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def lock_elements(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview locking up to 100 elements (Edit > Locking; manual lock, not Teamwork).
        Missing, hotlinked or already locked elements are refused. Apply identical inputs
        with explicit port and single-use token; editability is read back. Requires Tapir.
        Never saves."""
        return await locks.lock_elements(
            client_of(ctx), element_guids, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def unlock_elements(
        ctx: Context,
        element_guids: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview unlocking up to 100 locked elements (manual lock, not Teamwork).
        Elements that are already editable or sit on a locked layer are refused. Apply
        identical inputs with explicit port and single-use token; editability is read
        back. Requires Tapir. Never saves."""
        return await locks.unlock_elements(
            client_of(ctx), element_guids, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def update_zones(
        ctx: Context,
        port: int | None = None,
        keep_stamp_position: bool = True,
        undo_top_trim: bool = False,
        undo_bottom_trim: bool = False,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview Update Zones: recalculates every zone of the project (geometry, stamps,
        connected elements); there is no per-zone choice. Apply identical inputs with
        explicit port and single-use token. Zones are counted before and after; check
        areas in Archicad. Requires Tapir. Never saves."""
        return await zones_tool.update_zones(
            client_of(ctx),
            port,
            keep_stamp_position,
            undo_top_trim,
            undo_bottom_trim,
            dry_run,
            confirmation_token,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_property_groups(ctx: Context, port: int | None = None) -> dict:
        """Property groups (Options > Property Manager): GUID, name, description, whether
        it is custom and how many properties it holds. Requires Tapir."""
        return await property_definitions.list_property_groups(client_of(ctx), port)

    @mcp.tool(annotations=WRITE)
    async def create_property_groups(
        ctx: Context,
        groups: list[property_definitions.PropertyGroupCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 empty custom property groups (name, description). An
        existing group name is refused. Apply identical inputs with explicit port and
        single-use token; each group is read back. Requires Tapir. Never saves."""
        return await property_definitions.create_property_groups(
            client_of(ctx), groups, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_properties(
        ctx: Context,
        properties: list[property_definitions.PropertyCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 50 custom properties to existing custom groups: name,
        group (name or GUID), type (number, integer, string, boolean, length, area,
        volume, angle, their List forms, singleEnum, multiEnum), optional description,
        editable, default (meters, radians; enum defaults are option names),
        enum_values for enums, and available_for (classification items by GUID, id or name) or
        available_for_system (every item of one system). Names already in the group are
        refused. Apply identical inputs with explicit port and single-use token; each
        property is read back. Requires Tapir. Never saves."""
        return await property_definitions.create_properties(
            client_of(ctx), properties, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_worksheets(
        ctx: Context,
        worksheets: list[documents.ViewpointCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 empty independent worksheets to the Project Map:
        name and reference_id. One with the same name and ID is refused. Apply identical
        inputs with explicit port and single-use token; each is found back in the
        Navigator. Requires Tapir. Never saves."""
        return await documents.create_worksheets(
            client_of(ctx), worksheets, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_details(
        ctx: Context,
        details: list[documents.ViewpointCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 empty independent details to the Project Map: name
        and reference_id. One with the same name and ID is refused. Apply identical
        inputs with explicit port and single-use token; each is found back in the
        Navigator. Requires Tapir. Never saves."""
        return await documents.create_details(
            client_of(ctx), details, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_layouts(
        ctx: Context,
        layouts: list[documents.LayoutCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 layouts to the Layout Book: name and master (an
        existing master layout's name; a missing master is refused, never created).
        Size and margins come from the master. A layout name already in the book is
        refused. Apply identical inputs with explicit port and single-use token; each
        is found back in the Navigator. Requires Tapir. Never saves."""
        return await documents.create_layouts(
            client_of(ctx), layouts, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def rename_items(
        ctx: Context,
        kind: renames_tool.Kind,
        renames: list[renames_tool.Rename] | None = None,
        find: str | None = None,
        replace: str | None = None,
        scope: str | None = None,
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview renaming template items of one kind: view_map, project_map or
        layout_book items, favorites, classification_systems, classification_items (id
        and name), custom property_groups and properties, building_materials,
        layers (surfaces are refused: Tapir changed their texture), layer_combinations
        (layer states are kept and read back) or
        attribute_folders (scope = attribute type, e.g. Layer). Either find + replace on
        every name (replace "" removes the text) or renames, a list of exact {old, new}
        names. scope narrows classification_items to a system, properties to a group,
        favorites to an element type. Items keep their
        GUID; names that would clash are refused; up to 500 per call. Apply identical
        inputs with explicit port and single-use token; every name is read back.
        Requires Tapir. Never saves."""
        return await renames_tool.rename_items(
            client_of(ctx),
            kind,
            [r.model_dump() for r in renames] if renames is not None else None,
            find,
            replace,
            scope,
            port,
            dry_run,
            confirmation_token,
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

    @mcp.tool(annotations=WRITE)
    async def rotate_elements(
        ctx: Context,
        rotations: list[edit.ElementRotation],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Rotate up to 50 elements without copies. XY centres in metres; angles in radians.
        Requires Tapir. Preview/token/explicit port/receipts; no saving or unlocking.
        """
        return await edit.rotate_elements(
            client_of(ctx), rotations, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_gdl_parameters(
        ctx: Context, element_guids: list[str], port: int | None = None
    ) -> dict:
        """Read GDL parameter values/types/flags for up to 100 Objects. Requires Tapir."""
        return await read.get_gdl_parameters(client_of(ctx), element_guids, port)

    @mcp.tool(annotations=WRITE)
    async def set_gdl_parameters(
        ctx: Context,
        changes: list[edit.GDLChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/change existing scalar Object parameters; requires explicit port/token.
        Refuses fixed/hidden/locked parameters; verifies each value. Never saves.
        """
        return await edit.set_gdl_parameters(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_walls(
        ctx: Context,
        walls: list[edit.WallModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 straight walls: height/thickness/base/endpoints in metres.
        Refuses locked/hotlinked/curved/trapezoidal walls; verifies fields and never saves.
        """
        return await edit.modify_walls(client_of(ctx), walls, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def modify_slabs(
        ctx: Context,
        slabs: list[modify.SlabModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 slabs: thickness (Basic only) and level, metres from the
        slab's story. Refuses a level that would move it to another story, locked and
        hotlinked slabs; verifies fields and never saves.
        """
        return await modify.modify_slabs(client_of(ctx), slabs, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def modify_columns(
        ctx: Context,
        columns: list[modify.ColumnModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 columns: origin, bottomOffset, height, width, depth in
        metres. Height unlinks the top story; round/linked sections take one size.
        Refuses locked/hotlinked columns; verifies fields and never saves.
        """
        return await modify.modify_columns(
            client_of(ctx), columns, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_beams(
        ctx: Context,
        beams: list[modify.BeamModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 straight beams: begCoordinate, endCoordinate, level (from
        its story), width, height in metres. Refuses curved, zero-length, locked and
        hotlinked beams; verifies fields and never saves.
        """
        return await modify.modify_beams(client_of(ctx), beams, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def modify_windows(
        ctx: Context,
        windows: list[modify.OpeningModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 windows in walls: width, height, sillHeight, centerOffset
        (along the wall from its start), metres. Refuses offsets past the wall end,
        locked/hotlinked windows; verifies fields and never saves.
        """
        return await modify.modify_windows(
            client_of(ctx), windows, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_doors(
        ctx: Context,
        doors: list[modify.OpeningModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 doors in walls: width, height, sillHeight, centerOffset
        (along the wall from its start), metres. Refuses offsets past the wall end,
        locked/hotlinked doors; verifies fields and never saves.
        """
        return await modify.modify_doors(client_of(ctx), doors, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def modify_objects(
        ctx: Context,
        objects: list[modify.ObjectModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 objects: origin {x, y}, level from its story and
        dimensions {x, y, z} in metres. Refuses a level that changes story, locked and
        hotlinked objects; verifies fields and never saves.
        """
        return await modify.modify_objects(
            client_of(ctx), objects, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_roofs(
        ctx: Context,
        roofs: list[roofs_tool.RoofCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 roofs from simple polygons; metres, radians, absolute level.
        pivot_line + angle makes one plane rising on the line's left; without them a
        multi-plane roof on the polygon (optional levels, eaves_overhang). Requires Tapir;
        apply identical inputs with explicit port and single-use token. Never saves."""
        return await roofs_tool.create_roofs(
            client_of(ctx), roofs, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_texts(
        ctx: Context,
        texts: list[texts_tool.TextCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 plain texts: position in metres on a story, angle in radians,
        optional height_mm (paper millimetres) and justification; style from the Text
        tool default. Requires Tapir; apply with explicit port and token. Never saves."""
        return await texts_tool.create_texts(
            client_of(ctx), texts, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_lines(
        ctx: Context,
        lines: list[drafting.LineCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 straight 2D lines: start and end {x, y} in metres, floor_index,
        optional layer (name) and pen (index). Requires Tapir; apply identical inputs with
        explicit port and single-use token; each is read back. Never saves."""
        return await drafting.create_lines(client_of(ctx), lines, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_polylines(
        ctx: Context,
        polylines: list[drafting.PolylineCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 straight-segment polylines: points (2 to 500, metres; repeat the
        first point to close), floor_index, optional layer (name) and pen. Requires Tapir;
        apply with explicit port and token; the plan box is checked. Never saves."""
        return await drafting.create_polylines(
            client_of(ctx), polylines, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_arcs(
        ctx: Context,
        arcs: list[drafting.ArcCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 circular arcs: center, radius (metres), start_angle and end_angle
        (radians, counter-clockwise), floor_index, optional layer and pen. Requires Tapir;
        apply with explicit port and token; each is read back. Never saves."""
        return await drafting.create_arcs(client_of(ctx), arcs, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_circles(
        ctx: Context,
        circles: list[drafting.CircleCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 full circles: center and radius in metres, floor_index, optional
        layer and pen. Requires Tapir; apply with explicit port and token. Never saves."""
        return await drafting.create_circles(
            client_of(ctx), circles, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_fills(
        ctx: Context,
        fills: list[drafting.FillCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 fills (hatches) on simple polygons: outline (metres), floor_index,
        optional layer, fill (name, e.g. a hatch pattern), pen (fill) and contour_pen.
        Requires Tapir; apply with explicit port and token; the plan box is checked."""
        return await drafting.create_fills(client_of(ctx), fills, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_labels(
        ctx: Context,
        labels: list[labels_tool.LabelCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 text labels. element_guid attaches the label to that element
        (on its story); a free label needs position (metres) and floor_index. Optional
        height_mm (paper millimetres); style from the Label tool default. Requires Tapir;
        apply with explicit port and token. Never saves."""
        return await labels_tool.create_labels(
            client_of(ctx), labels, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_roofs(
        ctx: Context,
        roofs: list[modify.RoofModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 multi-plane roofs: thickness (Basic), level from its
        story, eavesOverhang, levels {height, angle}; metres, radians. Refuses
        single-plane, locked and hotlinked roofs; verifies fields and never saves.
        """
        return await modify.modify_roofs(client_of(ctx), roofs, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def modify_texts(
        ctx: Context,
        texts: list[modify.TextModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 texts: text, position (metres, stays on its story),
        angle (radians), heightMm (paper mm) and justification. Refuses locked and
        hotlinked texts; verifies fields and never saves.
        """
        return await modify.modify_texts(client_of(ctx), texts, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_windows(
        ctx: Context,
        windows: list[openings.OpeningCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 windows in existing straight walls, in metres. center_offset is
        along the wall from its start; width/height/sill_height are optional. The Window
        tool default or an existing favorite_name decides the library part. Requires Tapir;
        apply identical inputs with explicit port and single-use token. Never saves."""
        return await openings.create_windows(
            client_of(ctx), windows, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_doors(
        ctx: Context,
        doors: list[openings.OpeningCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 doors in existing straight walls, in metres. center_offset is
        along the wall from its start; width/height/sill_height are optional. The Door
        tool default or an existing favorite_name decides the library part. Requires Tapir;
        apply identical inputs with explicit port and single-use token. Never saves."""
        return await openings.create_doors(client_of(ctx), doors, port, dry_run, confirmation_token)

    @mcp.tool(annotations=READ_ONLY)
    async def run_read_command(
        ctx: Context,
        command: str,
        parameters: dict[str, Any] | None = None,
        port: int | None = None,
    ) -> dict:
        """Run one read-only command from a closed list and return the raw response.
        command is 'API.<Command>' (official JSON API) or 'Tapir.<Command>' (Tapir add-on),
        e.g. 'Tapir.GetHotlinks'; parameters are sent unchanged. Writes, saves and unlisted
        commands are refused; see docs/GATEWAY.md. Prefer the dedicated tools when one fits."""
        return await gateway.run_read_command(client_of(ctx), command, parameters, port)

    @mcp.tool(annotations=WRITE)
    async def modify_labels(
        ctx: Context,
        labels: list[modify.LabelModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 Text labels: text and height_mm (paper mm).
        Tapir 1.7.0 cannot change label position/story here. Symbol labels and unsupported
        fields are refused. Explicit port and single-use token to apply; never saves.
        """
        return await modify.modify_labels(client_of(ctx), labels, port, dry_run, confirmation_token)

    @mcp.tool(annotations=READ_ONLY)
    async def list_issues(
        ctx: Context,
        port: int | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        """List issues (GUID, name, tagText and native metadata), filtered and paginated."""
        return await issues_tool.list_issues(client_of(ctx), port, query, offset, limit)

    @mcp.tool(annotations=WRITE)
    async def create_issues(
        ctx: Context,
        issues: list[issues_tool.IssueCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 issues with name and optional tagText. Single-use
        confirmation and explicit apply port; receipt and read-back. Never saves or deletes.
        """
        return await issues_tool.create_issues(
            client_of(ctx), issues, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def attach_elements_to_issue(
        ctx: Context,
        issue_guid: str,
        element_guids: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/attach 1–100 existing elements to an issue as Highlight only.
        No Creation/Deletion/Modification marking; explicit apply port and single-use
        confirmation, per-element receipt and read-back. Never saves or deletes.
        """
        return await issues_tool.attach_elements_to_issue(
            client_of(ctx), issue_guid, element_guids, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_navigator_tree(
        ctx: Context,
        navigator_map: navigator_tool.NavigatorMap = "ProjectMap",
        port: int | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
        publisher_set_name: str | None = None,
    ) -> dict:
        """Read ProjectMap, PublicViewMap, LayoutBook or one PublisherSets tree.
        Flattened GUID/name/type/parent/depth, root included. Query matches name/type/uiId
        before pagination. For PublisherSets, pass an exact publisher_set_name or get
        only the first native set. Never writes, saves or publishes.
        """
        return await navigator_tool.get_navigator_tree(
            client_of(ctx), navigator_map, port, query, offset, limit, publisher_set_name
        )

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
