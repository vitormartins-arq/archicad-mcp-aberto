"""Find running Archicad instances and pick a target without guessing."""

from __future__ import annotations

import asyncio
from typing import Any

from archicad_mcp_aberto.connection.client import ArchicadClient
from archicad_mcp_aberto.connection.errors import (
    AmbiguousTarget,
    ArchicadBusy,
    ArchicadError,
    ArchicadUnavailable,
    CommandNotRegistered,
    NoInstance,
)


async def _probe(client: ArchicadClient, port: int) -> dict[str, Any] | None:
    try:
        info = await client.command(port, "GetProductInfo", timeout=client.probe_timeout)
    except ArchicadBusy as exc:
        # Keep busy instances in the list: they exist, they just cannot answer now.
        return {"port": port, "status": "busy", "detail": str(exc)}
    except ArchicadUnavailable:
        return None
    except ArchicadError as exc:
        return {"port": port, "status": "error", "detail": str(exc)}
    if "version" not in info:
        return None
    return {"port": port, "status": "ready", **info}


async def tapir_state(client: ArchicadClient, port: int) -> dict[str, Any]:
    """Return {'tapir_loaded': True/False/None, ...}. None means it could not be checked."""
    try:
        version = await client.tapir(port, "GetAddOnVersion")
    except CommandNotRegistered:
        return {"tapir_loaded": False}
    except ArchicadBusy as exc:
        return {"tapir_loaded": None, "detail": str(exc)}
    except ArchicadError as exc:
        return {"tapir_loaded": None, "detail": str(exc)}
    return {"tapir_loaded": True, "tapir_version": version.get("version")}


async def discover(client: ArchicadClient, *, identify: bool = True) -> list[dict[str, Any]]:
    """List reachable instances. With `identify`, add Tapir state and project name.

    Ports are not permanent identities: an instance can close and another can take
    its port. The project name, when Tapir is loaded, is what tells instances apart.
    """
    found = [i for i in await asyncio.gather(*(_probe(client, p) for p in client.ports)) if i]
    if identify:
        for item in found:
            if item["status"] != "ready":
                continue
            item.update(await tapir_state(client, item["port"]))
            if item.get("tapir_loaded"):
                try:
                    project = await client.tapir(item["port"], "GetProjectInfo")
                except ArchicadError:
                    continue
                item["project_name"] = project.get("projectName")
                item["is_untitled"] = project.get("isUntitled")
    return found


async def resolve_port(client: ArchicadClient, port: int | None) -> int:
    """Use the given port, or the only instance open. Never pick one of several."""
    if port is not None:
        await client.command(port, "GetProductInfo", timeout=client.probe_timeout)
        return port
    found = await discover(client, identify=False)
    if not found:
        raise NoInstance("No Archicad instance is reachable. Open a project in Archicad and retry.")
    if len(found) > 1:
        ports = ", ".join(str(i["port"]) for i in found)
        raise AmbiguousTarget(
            f"Several Archicad instances are open (ports {ports}). Ask the user which project "
            "to use (discover_archicad shows the project names) and pass its port."
        )
    if found[0]["status"] == "busy":
        raise ArchicadBusy(found[0]["detail"])
    return found[0]["port"]
