"""Read collisions through Tapir 1.7.0 GetCollisions."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 500


def _elements(guids: list[str], label: str) -> list[dict]:
    if not guids or len(guids) > _LIMIT:
        raise ValueError(f"{label} must contain between 1 and 500 GUIDs.")
    return [{"elementId": {"guid": str(UUID(g)).upper()}} for g in guids]


async def find_collisions(
    client: ArchicadClient,
    group1_guids: list[str],
    group2_guids: list[str],
    volume_tolerance: float = 0.001,
    perform_surface_check: bool = False,
    surface_tolerance: float = 0.001,
    port: int | None = None,
) -> dict:
    """Find collisions between two groups of at most 500 elements using SI tolerances."""
    first = _elements(group1_guids, "group1_guids")
    second = _elements(group2_guids, "group2_guids")
    if volume_tolerance < 0 or surface_tolerance < 0:
        raise ValueError("Collision tolerances cannot be negative.")
    port = await resolve_port(client, port)
    result = await client.tapir(
        port,
        "GetCollisions",
        {
            "elementsGroup1": first,
            "elementsGroup2": second,
            "settings": {
                "volumeTolerance": volume_tolerance,
                "performSurfaceCheck": perform_surface_check,
                "surfaceTolerance": surface_tolerance,
            },
        },
    )
    if not isinstance(result.get("collisions"), list):
        raise ValueError("Unexpected GetCollisions response.")
    return {"port": port, "collisions": result["collisions"]}
