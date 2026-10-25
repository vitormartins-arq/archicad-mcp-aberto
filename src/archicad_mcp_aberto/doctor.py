"""Command-line installation diagnostics for Archicad MCP Aberto."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from archicad_mcp_aberto import __version__
from archicad_mcp_aberto.connection import ArchicadClient, discover, ports_from_env
from archicad_mcp_aberto.connection.errors import ArchicadError

OWN_ADDON_PROBE = {
    "addOnCommandId": {
        "commandNamespace": "ArchicadMcpAberto",
        "commandName": "Get3DCamera",
    }
}


async def _own_addon_state(client: ArchicadClient, port: int) -> dict[str, Any]:
    try:
        result = await client.command(port, "IsAddOnCommandAvailable", OWN_ADDON_PROBE)
    except ArchicadError as exc:
        return {"loaded": None, "detail": str(exc)}
    available = result.get("isAvailable")
    if not isinstance(available, bool):
        return {"loaded": None, "detail": "Archicad returned no isAvailable flag."}
    return {"loaded": available}


async def build_report(client: ArchicadClient) -> dict[str, Any]:
    """Inspect local connectivity and add-ons without changing the project or view."""
    instances = []
    for instance in await discover(client):
        item = dict(instance)
        if item.get("status") == "ready":
            item["companion_addon"] = await _own_addon_state(client, item["port"])
        instances.append(item)
    problems = []
    if not instances:
        problems.append(
            {
                "code": "archicad_not_found",
                "action": "Open Archicad with a project, then run the doctor again.",
            }
        )
    for item in instances:
        port = item["port"]
        if item.get("status") == "busy":
            problems.append(
                {
                    "code": "archicad_busy",
                    "port": port,
                    "action": "Finish the open dialog or input operation in Archicad and retry.",
                }
            )
        elif item.get("status") != "ready":
            problems.append(
                {
                    "code": "archicad_error",
                    "port": port,
                    "action": "Check the Archicad Python connection and retry.",
                }
            )
        elif item.get("tapir_loaded") is False:
            problems.append(
                {
                    "code": "tapir_missing",
                    "port": port,
                    "action": "Install and load Tapir in Archicad's Add-On Manager.",
                }
            )
    return {
        "package_version": __version__,
        "host": client.host,
        "ports_checked": list(client.ports),
        "instances": instances,
        "status": "ready" if instances and not problems else "needs_attention",
        "problems": problems,
        "notes": [
            "The ArchicadMcpAberto companion add-on is optional and only needed "
            "for 3D scene tools.",
            "The doctor is read-only and never changes the project, view or selection.",
        ],
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"archicad-mcp-aberto {report['package_version']}",
        f"Status: {report['status']}",
        f"Ports checked: {', '.join(map(str, report['ports_checked']))}",
    ]
    if not report["instances"]:
        lines.append("Archicad: not found")
    for item in report["instances"]:
        product = " ".join(
            str(value)
            for value in (
                item.get("version"),
                item.get("buildNumber"),
                item.get("languageCode"),
            )
            if value is not None
        )
        lines.append(
            f"Port {item['port']}: {item['status']} (Archicad {product or 'version unknown'})"
        )
        lines.append(f"  Project: {item.get('project_name') or '(unavailable)'}")
        tapir = item.get("tapir_loaded")
        tapir_text = (
            "loaded " + str(item.get("tapir_version") or "")
            if tapir
            else "not loaded"
            if tapir is False
            else "unknown"
        )
        lines.append(f"  Tapir: {tapir_text.rstrip()}")
        addon = item.get("companion_addon", {})
        state = addon.get("loaded")
        addon_text = "loaded" if state else "not loaded" if state is False else "unknown"
        lines.append(f"  Companion add-on: {addon_text}")
    for problem in report["problems"]:
        where = f" on port {problem['port']}" if "port" in problem else ""
        lines.append(f"Action{where}: {problem['action']}")
    lines.append(report["notes"][0])
    return "\n".join(lines)


async def _run(ports: tuple[int, ...]) -> dict[str, Any]:
    async with ArchicadClient(ports=ports) as client:
        return await build_report(client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose the local Archicad MCP setup.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--ports", help="Ports or ranges to scan, for example 19723-19730 or 19723,19725."
    )
    args = parser.parse_args()
    try:
        ports = ports_from_env(args.ports)
    except ValueError as exc:
        parser.error(str(exc))
    report = asyncio.run(_run(ports))
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    raise SystemExit(0 if report["status"] == "ready" else 1)


if __name__ == "__main__":
    main()
