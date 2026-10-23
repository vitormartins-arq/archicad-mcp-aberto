"""MCP server entry point (stdio)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP, Image
from mcp.types import TextContent

from archicad_mcp_aberto.connection import ArchicadClient, ports_from_env
from archicad_mcp_aberto.tools import (
    attribute_properties,
    attributes,
    classifications,
    design_options,
    documents,
    drafting,
    edit,
    favorites,
    gateway,
    keynotes,
    locks,
    modify,
    openings,
    project_info,
    property_definitions,
    read,
    write,
)
from archicad_mcp_aberto.tools import classification_systems as classification_systems_tool
from archicad_mcp_aberto.tools import composites as composites_tool
from archicad_mcp_aberto.tools import design_option_create as design_option_create_tool
from archicad_mcp_aberto.tools import drawings as drawings_tool
from archicad_mcp_aberto.tools import grids as grids_tool
from archicad_mcp_aberto.tools import hotlinks as hotlinks_tool
from archicad_mcp_aberto.tools import interior_elevations as interior_elevations_tool
from archicad_mcp_aberto.tools import issues as issues_tool
from archicad_mcp_aberto.tools import labels as labels_tool
from archicad_mcp_aberto.tools import layer_settings as layer_settings_tool
from archicad_mcp_aberto.tools import layers as layers_tool
from archicad_mcp_aberto.tools import layout_book as layout_book_tool
from archicad_mcp_aberto.tools import meshes as meshes_tool
from archicad_mcp_aberto.tools import morphs as morphs_tool
from archicad_mcp_aberto.tools import navigator as navigator_tool
from archicad_mcp_aberto.tools import navigator_moves as navigator_moves_tool
from archicad_mcp_aberto.tools import renames as renames_tool
from archicad_mcp_aberto.tools import roofs as roofs_tool
from archicad_mcp_aberto.tools import scenes as scenes_tool
from archicad_mcp_aberto.tools import sections as sections_tool
from archicad_mcp_aberto.tools import selection as selection_tool
from archicad_mcp_aberto.tools import solids as solids_tool
from archicad_mcp_aberto.tools import stairs as stairs_tool
from archicad_mcp_aberto.tools import stories as stories_tool
from archicad_mcp_aberto.tools import surfaces as surfaces_tool
from archicad_mcp_aberto.tools import texts as texts_tool
from archicad_mcp_aberto.tools import views as views_tool
from archicad_mcp_aberto.tools import voids as voids_tool
from archicad_mcp_aberto.tools import wall_dimensions as wall_dimensions_tool
from archicad_mcp_aberto.tools import zone_categories as zone_categories_tool
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
- "Generate the 3D scenes": read_scene_model, then shoot_3d_scenes (look at every image,
  move or drop the bad ones), then save_3d_scenes, following docs/3D_SCENES.md: mostly
  level one-point interiors, a few two-point, a general isometric and one cut 1.50 m
  above each story. These need the ArchicadMcpAberto add-on (addon/).
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
        """Preview straight walls (up to 20). All lengths are metres.
        Requires Tapir. Review the preview with the user, then repeat identical inputs
        with dry_run=false, explicit port and confirmation_token. Height is always needed,
        thickness too unless `composite` (a wall Composite's name) is given; the wall then
        takes the composite and its total thickness. New walls inherit the default layer
        and building material, or those of `favorite` (a Wall favorite's name). Tapir 1.7.0
        does not keep a favorite's structure, height or linked top: pass the favorite's
        composite to keep it. Returns per-wall results and local receipts; verifies
        geometry after writing. Never saves the project."""
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
        inherit defaults, or come from `favorite` (a Slab favorite; thickness may then be
        left out). Review before applying identical inputs with dry_run=false, explicit
        port and single-use confirmation_token. Verifies each slab and returns local
        receipts. Never saves the project."""
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
        base_level is absolute project Z. With `favorite` (a Column favorite), height and
        section may be left out. Requires Tapir; review then apply identical inputs with
        explicit port and single-use token. Verifies each column; never saves."""
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
        An unknown name fails only that object. `favorite` takes an Object favorite's
        pens, layer and parameters; pass that favorite's own library part. Verifies each
        object; never saves."""
        return await write.create_objects(
            client_of(ctx), objects, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_lamps(
        ctx: Context,
        lamps: list[write.ObjectCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 lamps (Lamp library parts) by exact name, in metres and
        radians, like create_objects. base_level is absolute project Z. Optional Lamp
        `favorite` (pass its own library part). Requires Tapir; apply with explicit port
        and single-use token. Verifies each lamp; never saves."""
        return await write.create_lamps(client_of(ctx), lamps, port, dry_run, confirmation_token)

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
    async def create_zone_categories(
        ctx: Context,
        categories: list[zone_categories_tool.ZoneCategoryCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 50 zone categories: name, optional code and colour (red,
        green, blue from 0 to 1). An existing name is refused, never overwritten; the stamp
        comes from the first zone category. Apply with explicit port and single-use token;
        each is read back. Requires Tapir. Never saves."""
        return await zone_categories_tool.create_zone_categories(
            client_of(ctx), categories, port, dry_run, confirmation_token
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
        """Preview adding up to 20 layouts to the Layout Book: name, master (an
        existing master layout's name; a missing master is refused, never created) and
        optional subset (an existing subset by name or GUID; default the top of the
        book). Size and margins come from the master. A layout name already in the book is
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
        With `favorite` (a Beam favorite), width and height may be left out. Requires
        Tapir, explicit port and single-use token to apply; never saves.
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
    async def create_splines(
        ctx: Context,
        splines: list[drafting.SplineCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 auto-smoothed splines: points (3 to 500, metres; never repeat the
        first), closed (default false), floor_index, optional layer (name) and pen. Requires
        Tapir; apply with explicit port and token; points are read back. Never saves."""
        return await drafting.create_splines(
            client_of(ctx), splines, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_hotspots(
        ctx: Context,
        hotspots: list[drafting.HotspotCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 2D hotspots: position {x, y} in metres, optional height (the
        hotspot's z on its story, metres), floor_index, optional layer (name) and pen.
        Requires Tapir; apply with explicit port and token; each is read back. Never saves."""
        return await drafting.create_hotspots(
            client_of(ctx), hotspots, port, dry_run, confirmation_token
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
    async def modify_morphs(
        ctx: Context,
        morphs: list[modify.MorphModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview edits of up to 50 morphs: size {x, y, z} in metres (box morphs from
        create_morphs only; the corner stays), buildingMaterial and surface by name,
        castShadow, receiveShadow. Move or rotate with move_elements/rotate_elements.
        Requires Tapir; apply with explicit port and token; read back. Never saves."""
        return await modify.modify_morphs(client_of(ctx), morphs, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_keynote_labels(
        ctx: Context,
        labels: list[labels_tool.KeynoteLabelCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 20 keynote labels: keynote_item_guid from list_keynotes and a
        position in metres; content_fields picks Key/Title/Description/Reference (all by
        default). Archicad 28+; the label goes on the story Archicad shows, attached to
        nothing. Requires Tapir; apply with explicit port and token. Never saves."""
        return await labels_tool.create_keynote_labels(
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

    @mcp.tool(annotations=WRITE)
    async def create_meshes(
        ctx: Context,
        meshes: list[meshes_tool.MeshCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 simple 3D terrains. outline x/y/z and base level in
        absolute project metres; explicit floor_index. No holes/arcs/internal contours.
        Default surface without skirt. One-use token and explicit apply port; never saves.
        """
        return await meshes_tool.create_meshes(
            client_of(ctx), meshes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_meshes(
        ctx: Context,
        meshes: list[meshes_tool.MeshModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 20 terrains: absolute base level, skirt_type/depth, ridges,
        show_lines. No boundary/topology changes; preserves story. Explicit apply port,
        one-use token and read-back; never saves.
        """
        return await meshes_tool.modify_meshes(
            client_of(ctx), meshes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_view_settings(
        ctx: Context,
        view_guids: list[str],
        port: int | None = None,
    ) -> dict:
        """Read settings/errors per view (1–100 GUIDs). drawingScale is the denominator
        (100 means 1:100); zoom in metres and rotation in radians. Never writes.
        """
        return await views_tool.get_view_settings(client_of(ctx), view_guids, port)

    @mcp.tool(annotations=WRITE)
    async def set_view_settings(
        ctx: Context,
        changes: list[views_tool.ViewSettingsChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/set drawing_scale denominator and/or existing layer_combination by
        name/GUID for up to 100 PublicViewMap views. Read-back checks settings unchanged
        except requested fields. No guaranteed Navigator Undo; previous values retained.
        Explicit apply port, single-use token and receipt; never saves or publishes.
        """
        return await views_tool.set_view_settings(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_layer_combinations(
        ctx: Context,
        port: int | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
        include_layers: bool = False,
    ) -> dict:
        """List saved layer combinations (GUID/name/index), filter and paginate.
        include_layers adds each saved layer's visibility/lock/wireframe/intersection
        group, or a native error per combination. Never changes state or saves.
        """
        return await layer_settings_tool.list_layer_combinations(
            client_of(ctx), port, query, offset, limit, include_layers
        )

    @mcp.tool(annotations=WRITE)
    async def set_layer_settings(
        ctx: Context,
        changes: list[layer_settings_tool.LayerSettingsChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/set up to 50 existing layer flags: layer name/GUID, hidden, locked,
        wireframe, intersection_group (0–32767). Unspecified fields/name/GUID preserved.
        Protected first layer refused; no guaranteed Undo. Requires explicit apply port
        and one-use token, retains old values and checks read-back. Never saves/deletes.
        """
        return await layer_settings_tool.set_layer_settings(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def add_comment_to_issue(
        ctx: Context,
        comments: list[issues_tool.IssueComment],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/add up to 20 issue comments (issue_guid, text, optional author).
        Explicit apply port, one-use token, per-comment receipt and read-back.
        Never attaches, deletes or saves.
        """
        return await issues_tool.add_comment_to_issue(
            client_of(ctx), comments, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_view_map_folders(
        ctx: Context,
        folders: list[navigator_tool.ViewMapFolder],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 View Map folders with name and existing parent_guid.
        Explicit apply port/token, receipt and tree verification. No guaranteed Undo; never saves.
        """
        return await navigator_tool.create_view_map_folders(
            client_of(ctx), folders, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def clone_to_view_map(
        ctx: Context,
        views: list[navigator_tool.ViewMapClone],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/clone up to 20 Project Map source_guid items into existing parent_guid
        View Map folders. Native settings inherited; no guaranteed Undo. Port/token/receipts,
        tree read-back; never moves, deletes, saves or publishes.
        """
        return await navigator_tool.clone_to_view_map(
            client_of(ctx), views, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_classification_items(
        ctx: Context,
        items: list[classifications.ClassificationItemCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 classification items: system_guid, parent_guid, id,
        name and optional description. Existing system/parent only; duplicate IDs refused.
        Explicit apply port/token, receipts and full item/tree read-back. Never deletes/saves.
        """
        return await classifications.create_classification_items(
            client_of(ctx), items, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_design_options(
        ctx: Context,
        port: int | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        """List Design Option sets, options and combinations. Query filters options by
        id/name/set; pagination applies to options. Requires Archicad 29+ and Tapir 1.7.0.
        Changes nothing.
        """
        return await design_options.list_design_options(client_of(ctx), port, query, offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    async def get_elements_of_design_options(
        ctx: Context, design_option_guids: list[str], port: int | None = None
    ) -> dict:
        """List elements belonging to 1–500 Design Options, preserving native errors per
        option. Requires Archicad 29+ and Tapir 1.7.0. Changes nothing.
        """
        return await design_options.get_elements_of_design_options(
            client_of(ctx), design_option_guids, port
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_design_options_for_elements(
        ctx: Context, element_guids: list[str], port: int | None = None
    ) -> dict:
        """Read the Design Option status of 1–500 elements: linked option, main model,
        missing option or nonexistent element. Archicad 29+ / Tapir 1.7.0. Changes nothing.
        """
        return await design_options.get_design_options_for_elements(
            client_of(ctx), element_guids, port
        )

    @mcp.tool(annotations=WRITE)
    async def create_sections(
        ctx: Context,
        sections: list[sections_tool.SectionCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 straight sections: start and end {x, y} in metres,
        floor_index, a name new in the Project Map, and depth (metres, default 1). The
        section looks to the left of start->end; marker and settings come from the Section
        tool. Each is read back on its story and in the Project Map. Explicit apply port,
        one-use token and receipt; never saves.
        """
        return await sections_tool.create_sections(
            client_of(ctx), sections, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_favorites_from_elements(
        ctx: Context,
        new_favorites: list[favorites.FavoriteFromElement],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 new favorites, each from one existing element:
        element_guid, favorite (a name new for that element's type) and optional folder
        (list of folder names in the Favorites palette). Captures settings,
        classifications, editable property values. Never overwrites a favorite. Each new
        name is read back. Explicit apply port, one-use token and receipt; never saves.
        """
        return await favorites.create_favorites_from_elements(
            client_of(ctx), new_favorites, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def set_attribute_property_values(
        ctx: Context,
        changes: list[attribute_properties.AttributePropertyChange],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/apply up to 100 custom property values on attributes (building
        materials, composites, profiles and others): attribute_guid, property_guid and
        value as display text, in the format the preview shows for the current value.
        Refuses read-only or unavailable properties. Each value is read back as text.
        Explicit apply port, one-use token and receipt; never saves.
        """
        return await attribute_properties.set_attribute_property_values(
            client_of(ctx), changes, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_interior_elevations(
        ctx: Context,
        interior_elevations: list[interior_elevations_tool.InteriorElevationCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 interior elevations: nodes (2 to 50 {x, y} points in
        metres, one segment per consecutive pair), closed (repeat the first point),
        floor_index, a name new in the Project Map, optional reference_id and depth
        (metres, default 1). Each segment looks to the left of its direction, so a room's
        corners in anticlockwise order look at its walls from inside. Read back on the
        story and in the Project Map. Explicit apply port, one-use token and receipt;
        never saves.
        """
        return await interior_elevations_tool.create_interior_elevations(
            client_of(ctx), interior_elevations, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_keynotes(ctx: Context, port: int | None = None) -> dict:
        """Keynote folders and items (Archicad 28+): GUID, parent folder GUID, key path,
        key, title, description and reference. Requires Tapir."""
        return await keynotes.list_keynotes(client_of(ctx), port)

    @mcp.tool(annotations=WRITE)
    async def create_keynote_folders(
        ctx: Context,
        folders: list[keynotes.KeynoteFolderCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 keynote folders: key (new in the whole keynote tree),
        title and optional parent_folder_guid from list_keynotes (root otherwise). Only
        adds. Read back by GUID. Explicit apply port, one-use token and receipt; never
        saves."""
        return await keynotes.create_keynote_folders(
            client_of(ctx), folders, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_keynote_items(
        ctx: Context,
        items: list[keynotes.KeynoteItemCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 100 keynote items: key (new in the whole keynote tree),
        optional title, description, reference and parent_folder_guid from list_keynotes
        (root otherwise). Only adds. Read back by GUID. Explicit apply port, one-use token
        and receipt; never saves."""
        return await keynotes.create_keynote_items(
            client_of(ctx), items, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_morphs(
        ctx: Context,
        morphs: list[morphs_tool.MorphCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 box morphs: base corner x/y/z in absolute project metres,
        positive size_x/size_y/size_z and explicit floor_index. Material and display take
        the Morph defaults. Reads back story, origin, axes and 3D box. Explicit apply port,
        one-use token and receipt; never saves."""
        return await morphs_tool.create_morphs(
            client_of(ctx), morphs, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_stairs(
        ctx: Context,
        stairs: list[stairs_tool.StairCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 20 straight stairs: a start-end baseline in metres,
        base_level (absolute Z) and explicit floor_index. Optional total_height,
        flight_width, risers and `favorite` (a Stair favorite's name); what is left out
        comes from the Stair tool defaults or the favorite. Create on the story Archicad
        shows. Reads back type, story and 3D box. Explicit apply port, one-use token and
        receipt; never saves."""
        return await stairs_tool.create_stairs(
            client_of(ctx), stairs, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_wall_thickness_dimensions(
        ctx: Context,
        dimensions: list[wall_dimensions_tool.WallThicknessDimension],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 associative thickness dimensions on existing editable
        walls (wall_guid), one per wall, on the wall's story. Optional reference_point and
        direction in plan metres; default crosses the wall's middle. Explicit apply port,
        one-use token and receipt; never saves."""
        return await wall_dimensions_tool.create_wall_thickness_dimensions(
            client_of(ctx), dimensions, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_associative_dimensions(
        ctx: Context,
        dimensions: list[wall_dimensions_tool.WallPointsDimension],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 linear dimensions between wall ends: points
        [{wall_guid, end: start|end}] (2 to 20, straight walls on one story),
        reference_point the line passes through, optional direction (default the first
        wall's). Linked to the walls; read back point by point. Explicit apply port,
        one-use token and receipt; never saves."""
        return await wall_dimensions_tool.create_associative_dimensions(
            client_of(ctx), dimensions, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_openings(
        ctx: Context,
        openings: list[voids_tool.OpeningVoid],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/create up to 50 rectangular Opening-tool openings (Archicad 26+) in
        existing editable walls or slabs (owner_guid): base_point x/y/z in absolute project
        metres, z being the bottom edge, plus positive width and height. Other settings take
        the Opening tool defaults. Reads back the type and the host's connected openings.
        Explicit apply port, one-use token and receipt; never saves."""
        return await voids_tool.create_openings(
            client_of(ctx), openings, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def read_scene_model(
        ctx: Context,
        port: int | None = None,
        min_z: float | None = None,
        max_z: float | None = None,
    ) -> dict:
        """Plan 3D scenes: rooms (zone name, number, area, 3D box, suggested cameras) and
        boxes of walls, columns, objects, doors, windows and curtain walls; min_z/max_z
        keep one height band. Official API only. Rules in docs/3D_SCENES.md."""
        return await scenes_tool.read_scene_model(client_of(ctx), port, min_z, max_z)

    @mcp.tool(annotations=VIEW, structured_output=False)
    async def shoot_3d_scenes(
        ctx: Context,
        scenes: list[scenes_tool.Scene],
        port: int | None = None,
        image_format: Literal["jpg", "png"] = "jpg",
    ) -> list:
        """Set up to 8 scenes in the 3D window and return their images to judge: name,
        then perspective (camera, target, view_cone in radians, two_point; target.z left
        out keeps it level) or parallel (azimuth) with optional cut_height. Puts the 3D
        camera and cut back. Changes no element. Needs the ArchicadMcpAberto add-on."""
        report, images = await scenes_tool.shoot_3d_scenes(
            client_of(ctx), scenes, port, image_format
        )
        content: list = [TextContent(type="text", text=json.dumps(report, ensure_ascii=False))]
        for name, data in images:
            content.append(TextContent(type="text", text=name))
            content.append(Image(data=data, format="jpeg" if image_format == "jpg" else "png"))
        return content

    @mcp.tool(annotations=WRITE)
    async def save_3d_scenes(
        ctx: Context,
        scenes: list[scenes_tool.Scene],
        folder_path: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/save up to 60 scenes (shoot_3d_scenes shape) as View Map views in
        folder_path + each scene's folder (one per room); folders are created when missing.
        Apply identical inputs with explicit port and one-use token. Puts the 3D window
        back. Outside Undo; never saves the project. Needs the ArchicadMcpAberto add-on."""
        return await scenes_tool.save_3d_scenes(
            client_of(ctx), scenes, folder_path, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_composites(
        ctx: Context,
        composites: list[composites_tool.CompositeCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 composites: name, use_with (Wall, Slab, Roof, Shell)
        and up to 20 skins, each a building material by name, thickness in metres, type
        (Core, Finish, Other) and frame pen. Separators use separator_line (default: the
        first line type) and separator_pen. An existing name is refused, never
        overwritten. Apply with explicit port and single-use token; each is read back.
        Requires Tapir. Never saves."""
        return await composites_tool.create_composites(
            client_of(ctx), composites, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_drawings(
        ctx: Context,
        drawings: list[drawings_tool.DrawingCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview placing up to 20 views on layouts as Drawings: view (a View Map view
        name, or a Navigator item GUID from get_navigator_tree), layout (a Layout Book
        layout name or GUID), position (the Drawing's centre on the layout, metres of
        paper), optional name and angle. Folders, layouts and placed Drawings are refused.
        Apply with explicit port and single-use token; each is found on its layout after.
        Requires Tapir. Never saves."""
        return await drawings_tool.create_drawings(
            client_of(ctx), drawings, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def add_stories(
        ctx: Context,
        stories: list[stories_tool.StoryCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 stories: name, absolute level in metres and optional
        show_on_sections. Each goes above the top story or below the bottom one
        (basements); levels between stories are refused. Existing stories are kept as
        they are; structure_after shows every height. Apply with explicit port and
        single-use token; read back by GetStories. Requires Tapir. Never saves."""
        return await stories_tool.add_stories(
            client_of(ctx), stories, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_design_options(
        ctx: Context,
        sets: list[str] | None = None,
        options: list[design_option_create_tool.OptionCreate] | None = None,
        combinations: list[design_option_create_tool.CombinationCreate] | None = None,
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding design option sets (names), options ({name, id, set}: an
        existing set or one of sets) and combinations ({name, options: option ids}), up
        to 20 of each, in that order. Existing names and ids are refused; nothing is
        changed and no element is moved. Apply with explicit port and single-use token;
        all read back. Requires Tapir and Archicad 29+. Never saves."""
        return await design_option_create_tool.create_design_options(
            client_of(ctx), sets, options, combinations, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def move_to_design_options(
        ctx: Context,
        moves: list[design_option_create_tool.OptionMove],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview putting up to 100 elements in a design option: {element_guid, option}
        with the option's string id (list_design_options), or option null for the main
        model. The preview shows from and to. Apply with explicit port and single-use
        token; each is read back. Requires Tapir and Archicad 29+. Never saves."""
        return await design_option_create_tool.move_to_design_options(
            client_of(ctx), moves, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_solid_operations(
        ctx: Context,
        links: list[solids_tool.SolidLink],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview up to 50 solid element operations: target_guid, operator_guid,
        operation (Subtraction, SubtractionUpwards, SubtractionDownwards, Intersection,
        Addition), inherit_operator_attributes, skip_polygon_holes. Both elements must be
        editable; an existing link is refused. Apply with explicit port and single-use
        token; each link is read back. Requires Tapir. Never saves."""
        return await solids_tool.create_solid_operations(
            client_of(ctx), links, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def trim_to_roof(
        ctx: Context,
        element_guids: list[str],
        roof_guid: str,
        keep: Literal["KeepInside", "KeepOutside", "KeepAll"] = "KeepInside",
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview trimming up to 100 editable elements (walls, columns, beams...) with
        one roof or shell, keeping the part inside (below), outside or all. An existing
        trim by that roof is refused. Apply with explicit port and single-use token; each
        trim is read back. Requires Tapir. Never saves."""
        return await solids_tool.trim_to_roof(
            client_of(ctx), element_guids, roof_guid, keep, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def remove_solid_operations(
        ctx: Context,
        links: list[solids_tool.LinkPair],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview removing up to 50 existing solid element operations: target_guid and
        operator_guid. Both elements must be editable and the link must exist; the
        elements stay. Apply with explicit port and single-use token; each removal is
        read back. Requires Tapir. Never saves."""
        return await solids_tool.remove_solid_operations(
            client_of(ctx), links, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def remove_trims(
        ctx: Context,
        element_guids: list[str],
        roof_guid: str,
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview removing the trim of one roof or shell from up to 100 editable elements
        it trims; the elements stay. Apply with explicit port and single-use token; each
        removal is read back. Requires Tapir. Never saves."""
        return await solids_tool.remove_trims(
            client_of(ctx), element_guids, roof_guid, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def modify_lamps(
        ctx: Context,
        lamps: list[modify.LampModify],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview/edit up to 50 lamps: origin {x, y}, level from its story, dimensions
        {x, y, z} in metres (z through ZZYZX) and lightIsOn. Refuses a level that changes
        story, locked and hotlinked lamps; verifies fields and never saves. Requires
        Tapir."""
        return await modify.modify_lamps(client_of(ctx), lamps, port, dry_run, confirmation_token)

    @mcp.tool(annotations=WRITE)
    async def create_classification_systems(
        ctx: Context,
        systems: list[classification_systems_tool.SystemCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 10 classification systems: name, version, description,
        source, date (YYYY-MM-DD, today if omitted) and items, a tree of {id, name,
        description, children} with at least one item. A name and version already used is
        refused. Apply with explicit port and single-use token; the system and its whole
        tree are read back. create_classification_items adds items to an existing system.
        Requires Tapir. Never saves."""
        return await classification_systems_tool.create_classification_systems(
            client_of(ctx), systems, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def update_drawings(
        ctx: Context,
        layouts: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview updating every Drawing on up to 20 layouts (name or GUID) from its
        source view, as Update Drawing does (Archicad 27+). The preview lists the
        Drawings; a layout without Drawings is refused. Apply with explicit port and
        single-use token. Archicad has no read-back of the update, so the receipt stays
        unverified. Requires Tapir. Never saves."""
        return await drawings_tool.update_drawings(
            client_of(ctx), layouts, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_surfaces(
        ctx: Context,
        surfaces: list[surfaces_tool.SurfaceCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 50 surfaces, each a copy of an existing surface
        (based_on, by name) with a new name and optional color {red, green, blue} 0..1,
        transparency 0..100, material_type (General, Simple, Matte, Metal, Plastic,
        Glass, Glowing, Constant) and keep_texture. An existing name is refused. Apply
        with explicit port and single-use token; every field is read back. Requires
        Tapir. Never saves."""
        return await surfaces_tool.create_surfaces(
            client_of(ctx), surfaces, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_grid_elements(
        ctx: Context, port: int | None = None, include_parameters: bool = False
    ) -> dict:
        """List every grid line (Grid Tool element): start, end, angle, length, story,
        layer index and library part; include_parameters adds the GDL parameters and the
        Grid Tool defaults. Needs the ArchicadMcpAberto add-on."""
        return await grids_tool.list_grid_elements(client_of(ctx), port, include_parameters)

    @mcp.tool(annotations=WRITE)
    async def create_grid_elements(
        ctx: Context,
        grids: list[grids_tool.GridCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview drawing up to 50 grid lines, each from start to end {x, y} on
        floor_index, with optional layer (name) and GDL parameters [{name, value}] such as
        the bubble text (names from list_grid_elements with include_parameters). The
        length comes from the points. Apply with explicit port and single-use token; one
        Undo step, every line read back. Needs the ArchicadMcpAberto add-on. Never saves."""
        return await grids_tool.create_grid_elements(
            client_of(ctx), grids, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def move_navigator_items(
        ctx: Context,
        map: Literal["view_map", "layout_book"],
        moves: list[navigator_moves_tool.Move],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview moving up to 50 items: in the View Map, views and folders into a folder;
        in the Layout Book, layouts and subsets into a subset or the top of the book.
        item and folder are names or GUIDs (a repeated name needs the GUID). An item
        already in the folder, or a folder into itself, is refused. Apply with explicit
        port and single-use token; one move at a time, each read back. Requires Tapir.
        Never saves."""
        return await navigator_moves_tool.move_navigator_items(
            client_of(ctx), map, moves, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def update_favorites_from_elements(
        ctx: Context,
        favorites_to_update: list[favorites.FavoriteUpdate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview overwriting up to 50 EXISTING favorites, each with the settings,
        classifications and property values of one element of the favorite's type
        (element_guid, favorite). The old settings are not kept: copy them first with
        create_favorites_from_elements if they matter. Apply with explicit port and
        single-use token. Tapir cannot read a favorite's settings, so the receipt stays
        unverified. Requires Tapir. Never saves."""
        return await favorites.update_favorites_from_elements(
            client_of(ctx), favorites_to_update, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def create_layout_subsets(
        ctx: Context,
        subsets: list[layout_book_tool.SubsetCreate],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview adding up to 20 Layout Book subsets: name, parent (an existing subset
        by name or GUID; omitted for the top of the book), optional own ID prefix and
        numbering (abc, ABC, 1, 01, 001, 0001, noID). A name already under that parent
        is refused. Apply with explicit port and single-use token; each is read back in
        the Layout Book. create_layouts takes the subset to put layouts in. Requires
        Tapir. Never saves."""
        return await layout_book_tool.create_layout_subsets(
            client_of(ctx), subsets, port, dry_run, confirmation_token
        )

    @mcp.tool(annotations=WRITE)
    async def place_hotlinks(
        ctx: Context,
        placements: list[hotlinks_tool.HotlinkPlace],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        """Preview placing up to 20 hotlink modules: source_path (absolute .mod or .pln
        path on the Archicad computer), origin {x, y, z?} in metres, floor_index, angle
        (radians), mirrored, optional node name and single_story (one source story).
        A node for the same file is reused. Apply with explicit port and single-use
        token; each instance is read back. Requires Tapir. Never saves."""
        return await hotlinks_tool.place_hotlinks(
            client_of(ctx), placements, port, dry_run, confirmation_token
        )

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
