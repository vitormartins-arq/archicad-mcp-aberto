"""Read MEP data using Tapir 1.7.0 source schemas."""

from typing import Literal

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 100


async def list_mep_systems(
    client: ArchicadClient, port: int | None = None, limit: int = 100
) -> dict:
    if not 1 <= limit <= _LIMIT:
        raise ValueError("limit must be between 1 and 100.")
    port = await resolve_port(client, port)
    headers = await client.tapir(port, "GetAttributesByType", {"attributeType": "MEPSystem"})
    attributes = headers.get("attributes")
    if not isinstance(attributes, list):
        raise ValueError("Unexpected MEP system inventory response.")
    selected = attributes[:limit]
    details = await client.tapir(
        port,
        "GetMEPSystems",
        {"attributeIds": [{"attributeId": row["attributeId"]} for row in selected]},
    )
    systems = details.get("mepSystems")
    if not isinstance(systems, list) or len(systems) != len(selected):
        raise ValueError("Unexpected GetMEPSystems response.")
    distribution = await client.tapir(port, "GetMEPDistributionSystems", {})
    if not isinstance(distribution.get("distributionSystems"), list):
        raise ValueError("Unexpected GetMEPDistributionSystems response.")
    return {
        "port": port,
        "total": len(attributes),
        "mepSystems": systems,
        "distributionSystems": distribution["distributionSystems"],
    }


async def get_mep_elements(
    client: ArchicadClient,
    element_types: list[str] | None = None,
    domains: list[str] | None = None,
    limit: int = 100,
    port: int | None = None,
) -> dict:
    if not 1 <= limit <= _LIMIT:
        raise ValueError("limit must be between 1 and 100.")
    port = await resolve_port(client, port)
    params = {}
    if element_types is not None:
        params["elementTypes"] = element_types
    if domains is not None:
        params["domains"] = domains
    inventory = await client.tapir(port, "GetMEPElements", params)
    rows = inventory.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected GetMEPElements response.")
    selected = rows[:limit]
    elements = [{"elementId": row["elementId"]} for row in selected]
    routing = await client.tapir(port, "GetMEPRoutingElements", {"elements": elements})
    ports = await client.tapir(port, "GetMEPPorts", {"elements": elements})
    if not isinstance(routing.get("routingElements"), list) or len(
        routing["routingElements"]
    ) != len(selected):
        raise ValueError("Unexpected GetMEPRoutingElements response.")
    if not isinstance(ports.get("elementPorts"), list) or len(ports["elementPorts"]) != len(
        selected
    ):
        raise ValueError("Unexpected GetMEPPorts response.")
    return {
        "port": port,
        "total": len(rows),
        "elements": selected,
        "routingElements": routing["routingElements"],
        "elementPorts": ports["elementPorts"],
    }


async def get_mep_preference_tables(
    client: ArchicadClient,
    domain: Literal["Piping", "Ventilation"],
    port: int | None = None,
) -> dict:
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetMEPPreferenceTables", {"domain": domain})
    if not isinstance(result.get("tables"), list):
        raise ValueError("Unexpected GetMEPPreferenceTables response.")
    return {"port": port, "domain": domain, "tables": result["tables"]}
