"""Native associative angular dimensions. Coordinates in metres, angles in radians."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write


class AngleReference(write.InputModel):
    element_guid: str
    in_index: int
    neig_id: int

    @field_validator("element_guid")
    @classmethod
    def guid(cls, value):
        return str(UUID(value)).upper()


class AngleDimensionCreate(write.InputModel):
    favorite: Annotated[str, Field(min_length=1, max_length=255)]
    floor_index: Annotated[int, Field(ge=-32768, le=32767)]
    position: write.Point
    references: Annotated[list[AngleReference], Field(min_length=4, max_length=4)]


def payload(d):
    return {
        "favorite": d.favorite,
        "floorIndex": d.floor_index,
        "position": d.position.model_dump(),
        "references": [
            {"elementGuid": r.element_guid, "inIndex": r.in_index, "neigId": r.neig_id}
            for r in d.references
        ],
    }


async def get_angle_dimensions(client, port=None, guids=None):
    params = {}
    if guids is not None:
        if not 1 <= len(guids) <= 100:
            raise ValueError("Pass 1..100 dimension GUIDs.")
        params["guids"] = [str(UUID(g)).upper() for g in guids]
    port = await resolve_port(client, port)
    result = await grids._addon(client, port, "GetAngleDimensions", params)
    if not isinstance(result.get("dimensions"), list):
        raise ValueError("Invalid native angular response.")
    return {"port": port, **result}


async def _plan(client, dimensions, port, operation):
    port = await resolve_port(client, port)
    native = await grids._addon(
        client, port, "PlanAngleDimensions", {"dimensions": [payload(d) for d in dimensions]}
    )
    rows = native.get("items")
    if (
        not isinstance(rows, list)
        or len(rows) != len(dimensions)
        or not isinstance(native.get("context"), dict)
    ):
        raise ValueError("Incomplete native angular plan.")
    items = []
    for i, (d, row) in enumerate(zip(dimensions, rows, strict=True)):
        refs = row.get("references", [])
        if row.get("type") != "AngleDimension" or len(refs) != 4:
            raise ValueError("Native angular references missing.")
        for source, reference in zip(d.references, refs, strict=True):
            if (
                reference.get("elementGuid", "").upper() != source.element_guid
                or reference.get("inIndex") != source.in_index
            ):
                raise ValueError("Native angular association mismatch.")
        items.append(
            {
                "index": i,
                "status": "ready",
                "parameters": payload(d),
                "expected": row,
                "duplicate_guids": row.get("existingGuids", []),
            }
        )
    return {
        "operation": operation,
        "target": {"port": port, "project": native["context"]},
        "native_plan": native,
        "items": items,
    }


async def _dispatch(client, receipt):
    await _dispatch_native(client, receipt, "CreateAngleDimensions", get_angle_dimensions)


async def _dispatch_native(client, receipt, command, reader):
    port = receipt["target"]["port"]
    try:
        result = await grids._addon(
            client,
            port,
            command,
            {
                "dimensions": [i["parameters"] for i in receipt["items"]],
                "expectedPlan": receipt["native_plan"],
            },
            timeout=receipt["write_timeout_seconds"],
        )
    except (ArchicadError, ValueError) as exc:
        for item in receipt["items"]:
            item.update(status="unknown", error=str(exc))
            if isinstance(exc, ArchicadError):
                item["native_error"] = exc.detail
        return
    rows = result.get("dimensions", [])
    if not isinstance(rows, list) or len(rows) != len(receipt["items"]):
        for item in receipt["items"]:
            item.update(status="unknown", error="Unexpected result count; do not retry.")
        return
    for item, row in zip(receipt["items"], rows, strict=True):
        ids = row.get("existingGuids", []) if row.get("status") == "existing" else [row.get("guid")]
        if len(ids) != 1:
            item.update(status="verification_failed", error="Ambiguous native result.")
            continue
        try:
            guid = str(UUID(ids[0])).upper()
            item.update(element_guid=guid, status="unverified")
            found = await reader(client, port, [guid])
            actual = found["dimensions"]
            if len(actual) != 1 or str(actual[0].get("guid", "")).upper() != guid:
                raise ValueError("Read-back returned another dimension.")
            expected = {
                k: v for k, v in item["expected"].items() if k not in {"guid", "existingGuids"}
            }
            problems = write._mismatches(expected, actual[0])
            item.update(
                status="verification_failed" if problems else "verified",
                readback=actual[0],
                mismatches=problems,
            )
            item["verification_scope"] = (
                "Native type, reference identities, measured value, position and favorite style. "
                "Rebuild/edit/visual acceptance pending."
            )
        except (ArchicadError, ValueError, TypeError, AttributeError) as exc:
            item.update(status="unverified", error=str(exc))


async def create_angle_dimensions(
    client, dimensions, port=None, dry_run=True, confirmation_token=None
):
    if not 1 <= len(dimensions) <= 20:
        raise ValueError("Pass 1..20 angular dimensions.")
    validated = [
        d if isinstance(d, AngleDimensionCreate) else AngleDimensionCreate.model_validate(d)
        for d in dimensions
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_angle_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
