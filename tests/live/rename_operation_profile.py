"""Compare an operation profile before and after renaming in a disposable PLN copy."""

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools.renames import SURFACE_COMMAND

FIELDS = {"occupancyType", "hotWaterLoad", "humanHeatGain", "humidity"}


async def run(port: int, guid: str, evidence: Path, disposable_copy: bool) -> None:
    async with ArchicadClient() as client:
        project = await client.tapir(port, "GetProjectInfo")
        if project.get("isUntitled") is not True and not disposable_copy:
            raise RuntimeError("Open a disposable project and explicitly confirm it is a copy.")
        product = await client.command(port, "GetProductInfo")
        available = await client.command(port, "IsAddOnCommandAvailable", SURFACE_COMMAND)
        if available.get("isAvailable") is not True:
            raise RuntimeError("Load the candidate add-on before running this test.")
        parameters = {"attributeIds": [{"attributeId": {"guid": guid}}]}
        before = await client.command(port, "GetOperationProfileAttributes", parameters)
        (row,) = before["attributes"]
        profile = row.get("operationProfileAttribute", {})
        if (
            not FIELDS <= profile.keys()
            or profile.get("attributeId", {}).get("guid", "").casefold() != guid.casefold()
        ):
            raise RuntimeError("The requested profile or its comparison fields are missing.")
        if await client.tapir(port, "GetProjectInfo") != project:
            raise RuntimeError("The target changed before the write.")
        new_name = f"LAB Operation Profile Test {uuid4().hex[:8]}"
        expected = deepcopy(before)
        expected["attributes"][0]["operationProfileAttribute"]["name"] = new_name
        record = {"product": product, "port": port, "guid": guid, "before": before}
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
        try:
            record["write"] = await client.own_addon(
                port,
                "RenameAttributes",
                {
                    "attributeType": "OperationProfile",
                    "renames": [{"guid": guid, "newName": new_name}],
                },
            )
        finally:
            try:
                record["after"] = await client.command(
                    port, "GetOperationProfileAttributes", parameters
                )
            finally:
                evidence.write_text(json.dumps(record, indent=2), encoding="utf-8")
        if record["after"] != expected or record["write"]["results"][0]["success"] is not True:
            raise RuntimeError(f"Rename/readback failed. Inspect {evidence}; do not retry blindly.")
        print(f"Only the name changed in the official JSON. Evidence: {evidence}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--guid", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--disposable-copy", action="store_true", help="Confirm a saved PLN is a disposable copy."
    )
    args = parser.parse_args()
    asyncio.run(run(args.port, args.guid, args.evidence, args.disposable_copy))
