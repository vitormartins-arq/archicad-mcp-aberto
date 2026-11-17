"""Compare every official JSON surface field in a disposable untitled project."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools.renames import SURFACE_COMMAND


async def run(port: int, guid: str, evidence: Path) -> None:
    async with ArchicadClient() as client:
        product = await client.command(port, "GetProductInfo")
        project = await client.tapir(port, "GetProjectInfo")
        if project.get("isUntitled") is not True:
            raise RuntimeError("Use a new, disposable, untitled Archicad project.")
        available = await client.command(port, "IsAddOnCommandAvailable", SURFACE_COMMAND)
        if available.get("isAvailable") is not True:
            raise RuntimeError("The test build of RenameAttributes is not loaded.")
        parameters = {"attributeIds": [{"attributeId": {"guid": guid}}]}
        before = await client.command(port, "GetSurfaceAttributes", parameters)
        rows = before["attributes"]
        if len(rows) != 1 or not rows[0].get("surfaceAttribute", {}).get("texture"):
            raise RuntimeError("Select the GUID of one surface with a texture.")
        if await client.tapir(port, "GetProjectInfo") != project:
            raise RuntimeError("The target changed before the write.")
        new_name = f"LAB Rename Test {uuid4().hex[:8]}"
        expected = json.loads(json.dumps(before))
        expected["attributes"][0]["surfaceAttribute"]["name"] = new_name
        record = {"product": product, "port": port, "guid": guid, "before": before}
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
        try:
            record["write"] = await client.own_addon(
                port,
                "RenameAttributes",
                {"attributeType": "Surface", "renames": [{"guid": guid, "newName": new_name}]},
            )
        finally:
            try:
                record["after"] = await client.command(port, "GetSurfaceAttributes", parameters)
            finally:
                evidence.write_text(json.dumps(record, indent=2), encoding="utf-8")
        if record["after"] != expected or record["write"]["results"][0]["success"] is not True:
            raise RuntimeError(f"Rename/readback failed. Inspect {evidence}; do not retry blindly.")
        print(f"Only the name changed. Evidence: {evidence}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--guid", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.port, args.guid, args.evidence))
