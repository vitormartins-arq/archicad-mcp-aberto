"""Read project attributes through Tapir; never change attributes or the model."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

CUT_FILL_FIELDS = ["cutFillIndex", "cutFillPen", "cutFillBackgroundPen"]
BATCH_SIZE = 100


async def list_building_materials(
    client: ArchicadClient, port: int | None = None, attribute_guids: list[str] | None = None
) -> dict:
    """List GUID, index, name and cut-fill index/foreground/background pens.

    Requires Tapir 1.7.0. None lists all; [] returns none. GUID filters preserve order
    and per-attribute errors, with duplicates removed. Reads details in batches of 100.
    cutFill is the fill attribute index, not a polygon or a statement about visibility.
    """
    guids = (
        list(dict.fromkeys(str(UUID(g)).upper() for g in attribute_guids))
        if attribute_guids is not None
        else None
    )
    port = await resolve_port(client, port)
    if guids is None:
        headers = await client.tapir(
            port, "GetAttributesByType", {"attributeType": "BuildingMaterial"}
        )
        guids = [str(UUID(row["attributeId"]["guid"])).upper() for row in headers["attributes"]]
    materials = []
    for offset in range(0, len(guids), BATCH_SIZE):
        batch = guids[offset : offset + BATCH_SIZE]
        response = await client.tapir(
            port,
            "GetBuildingMaterials",
            {
                "attributeIds": [{"attributeId": {"guid": g}} for g in batch],
                "fields": CUT_FILL_FIELDS,
            },
        )
        rows = response["buildingMaterials"]
        if len(rows) != len(batch):
            raise ValueError("Unexpected building material response cardinality.")
        for guid, row in zip(batch, rows, strict=True):
            if "error" in row:
                materials.append({"guid": guid, "error": row["error"]})
                continue
            if str(UUID(row["attributeId"]["guid"])).upper() != guid:
                raise ValueError("Building material response GUID does not match the request.")
            materials.append(
                {
                    "guid": guid,
                    "index": row["index"],
                    "name": row["name"],
                    "cutFill": row["cutFillIndex"],
                    "cutFillPen": row["cutFillPen"],
                    "cutFillBackgroundPen": row["cutFillBackgroundPen"],
                }
            )
    return {"port": port, "total": len(materials), "buildingMaterials": materials}
