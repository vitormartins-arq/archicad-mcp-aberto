"""Create new complex profiles from copied or caller-authored geometry (Tapir 1.7.0)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drafting, write

MAX_ITEMS = 20
Name = Annotated[str, Field(min_length=1, max_length=255)]


class ProfileContour(write.InputModel):
    points: Annotated[list[write.Point], Field(min_length=3, max_length=500)]

    @model_validator(mode="after")
    def valid_polygon(self) -> ProfileContour:
        # Reuse the create_slabs polygon checks, including self-intersections. Profile
        # coordinates are local metres and Tapir closes every contour automatically.
        polygon = write.SlabCreate(outline=self.points, floor_index=0, thickness=1.0, level=0.0)
        self.points = polygon.outline
        return self


class ProfileSkin(write.InputModel):
    contours: Annotated[list[ProfileContour], Field(min_length=1, max_length=50)]
    building_material: Name
    contour_pen: Annotated[int, Field(ge=1, le=255)] | None = None
    is_core: bool | None = None
    is_finish: bool | None = None
    visible_cut_end_lines: bool | None = None
    cut_end_line_pen: Annotated[int, Field(ge=1, le=255)] | None = None


class ProfileCreate(write.InputModel):
    name: Name
    source_profile: Name | None = None
    skins: Annotated[list[ProfileSkin], Field(min_length=1, max_length=50)] | None = None
    walls: bool | None = None
    beams: bool | None = None
    columns: bool | None = None
    handrails: bool | None = None
    objects: bool | None = None

    @field_validator("name", "source_profile")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value != value.strip():
            raise ValueError("profile names must not have outer whitespace")
        return value

    @model_validator(mode="after")
    def has_geometry(self) -> ProfileCreate:
        if self.source_profile is None and self.skins is None:
            raise ValueError("source_profile, skins, or both are required")
        return self


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    catalog = await drafting._attributes(client, port, "Profile")
    existing = {row["name"].casefold() for row in catalog}
    seen = set()
    items = []
    mapping = {
        "walls": "wallType",
        "beams": "beamType",
        "columns": "coluType",
        "handrails": "handrailType",
        "objects": "otherGDLObjectType",
    }
    material_catalog = None
    for index, entry in enumerate(entries):
        key = entry.name.casefold()
        if key in existing:
            raise ValueError(f"Profile {entry.name!r} already exists; nothing is overwritten.")
        if key in seen:
            raise ValueError(f"Profile {entry.name!r} appears twice.")
        sources = []
        if entry.source_profile is not None:
            sources = [
                r for r in catalog if r["name"].casefold() == entry.source_profile.casefold()
            ]
            if len(sources) != 1:
                problem = "is ambiguous" if sources else "does not exist"
                raise ValueError(f"Source profile {entry.source_profile!r} {problem}.")
        seen.add(key)
        payload = {"name": entry.name}
        if sources:
            payload["sourceAttributeId"] = {"attributeId": sources[0]["attributeId"]}
        if entry.skins:
            if material_catalog is None:
                material_catalog = await drafting._attributes(client, port, "BuildingMaterial")
            new_skins = []
            for skin_index, skin in enumerate(entry.skins):
                material = drafting._named(
                    material_catalog,
                    skin.building_material,
                    f"Profile {entry.name!r} skin {skin_index} building material",
                )
                native = {
                    "contours": [
                        {"polygonCoordinates": [point.model_dump() for point in contour.points]}
                        for contour in skin.contours
                    ],
                    "buildingMaterialId": {"attributeId": material["attributeId"]},
                }
                for field, native_field in (
                    ("contour_pen", "contourPen"),
                    ("is_core", "isCore"),
                    ("is_finish", "isFinish"),
                    ("visible_cut_end_lines", "visibleCutEndLines"),
                    ("cut_end_line_pen", "cutEndLinePen"),
                ):
                    value = getattr(skin, field)
                    if value is not None:
                        native[native_field] = value
                new_skins.append(native)
            payload["newSkins"] = new_skins
        for field, native in mapping.items():
            value = getattr(entry, field)
            if value is not None:
                payload[native] = value
        items.append(
            {
                "index": index,
                "status": "ready",
                "source_name": sources[0]["name"] if sources else None,
                "source_guid": sources[0]["attributeId"]["guid"] if sources else None,
                "parameters": payload,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateProfiles",
            {"profileDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        return
    rows = raw.get("attributeIds")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        identifier = row.get("attributeId") if isinstance(row, dict) else None
        try:
            guid = str(UUID(identifier["guid"])).upper()
        except (TypeError, KeyError, ValueError):
            if isinstance(row, dict) and "error" in row:
                item.update(status="failed", error=row["error"])
            else:
                item.update(status="unknown", error="Missing profile ID or error.")
        else:
            item.update(status="unverified", profile_guid=guid)
            created.append(item)
    if not created:
        return
    try:
        response = await client.tapir(
            port,
            "GetProfiles",
            {
                "attributeIds": [
                    {"attributeId": {"guid": item["profile_guid"]}} for item in created
                ],
                "fields": [
                    "wallType",
                    "beamType",
                    "coluType",
                    "handrailType",
                    "otherGDLObjectType",
                    "skins",
                    "skinOutlines",
                ],
            },
            timeout=timeout,
        )
        after = response.get("profiles")
        if not isinstance(after, list) or len(after) != len(created):
            raise ValueError("Unexpected profile verification cardinality.")
        for item, row in zip(created, after, strict=True):
            item["after"] = row
            expected = {
                k: v
                for k, v in item["parameters"].items()
                if k not in {"sourceAttributeId", "newSkins"}
            }
            differences = write._mismatches(expected, row)
            new_skins = item["parameters"].get("newSkins", [])
            actual_skins = row.get("skins")
            if new_skins and (
                not isinstance(actual_skins, list) or len(actual_skins) < len(new_skins)
            ):
                differences.append("skins")
            elif new_skins:
                for skin_index, (wanted, actual) in enumerate(
                    zip(new_skins, actual_skins[-len(new_skins) :], strict=True)
                ):
                    prefix = f"skins[{skin_index}]"
                    if actual.get("buildingMaterialId") != wanted["buildingMaterialId"]:
                        differences.append(f"{prefix}.buildingMaterialId")
                    wanted_coords = [{"x": 0.0, "y": 0.0}]
                    wanted_ends = [0]
                    for contour in wanted["contours"]:
                        points = contour["polygonCoordinates"]
                        wanted_coords.extend(points)
                        wanted_coords.append(points[0])
                        wanted_ends.append(len(wanted_coords) - 1)
                    if not write._same_polygon(wanted_coords, actual.get("outlineCoords")):
                        differences.append(f"{prefix}.outlineCoords")
                    if actual.get("outlineSubPolyEnds") != wanted_ends:
                        differences.append(f"{prefix}.outlineSubPolyEnds")
            item["status"] = "verification_failed" if differences else "verified"
            if differences:
                item["mismatches"] = differences
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def create_profiles(
    client: ArchicadClient,
    profiles: list[dict | ProfileCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 profiles from copied geometry and/or polygon skins."""
    if not 1 <= len(profiles) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} profiles.")
    entries = [
        p if isinstance(p, ProfileCreate) else ProfileCreate.model_validate(p) for p in profiles
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_profiles",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
