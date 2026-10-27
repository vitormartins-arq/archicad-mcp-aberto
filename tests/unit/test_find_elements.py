from uuid import UUID

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import read
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
PROP = "22222222-2222-2222-2222-222222222222"


def guid(n):
    return str(UUID(int=n)).upper()


def model(size=4):
    return FakeArchicad(
        19723,
        elements={guid(i): "Wall" if i % 2 else "Slab" for i in range(1, size + 1)},
        details={guid(i): {"floorIndex": i % 2, "layerIndex": i % 3} for i in range(1, size + 1)},
        properties={PROP: "Test"},
        property_values={
            (guid(i), PROP): {"type": "number", "status": "normal", "value": i}
            for i in range(1, size + 1)
        },
    )


async def search(fake, **kwargs):
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        return await read.find_elements(c, port=19723, **kwargs)


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"element_type": "Wall"}, [1, 3]),
        ({"floor_index": 0}, [2, 4]),
        ({"layer_index": 1}, [1, 4]),
        ({"element_type": "Wall", "floor_index": 1, "layer_index": 0}, [3]),
        ({"property_guid": PROP, "value": 2}, [2]),
        ({"property_guid": PROP, "operator": "greater", "value": 2}, [3, 4]),
        ({"property_guid": PROP, "operator": "less", "value": 2}, [1]),
        (
            {
                "element_type": "Wall",
                "layer_index": 0,
                "property_guid": PROP,
                "operator": "greater",
                "value": 1,
            },
            [3],
        ),
    ],
)
async def test_filters(filters, expected):
    result = await search(model(), **filters)
    assert [e["elementId"]["guid"] for e in result["elements"]] == [guid(i) for i in expected]
    assert result["total"] == len(expected)


async def test_contains_case_sensitive_and_unavailable():
    fake = model()
    for i, value in enumerate(["Alpha", "alphabet", "Beta", "Alpha"], 1):
        fake.property_values[(guid(i), PROP)] = {
            "type": "string",
            "status": "normal" if i != 4 else "notAvailable",
            "value": value,
        }
    result = await search(fake, property_guid=PROP, operator="contains", value="Al")
    assert result["elements"] == [{"elementId": {"guid": guid(1)}}]
    assert len(result["errors"]) == 1


async def test_pagination():
    fake = model(505)
    first = await search(fake, limit=500)
    last = await search(fake, offset=500, limit=500)
    assert first["total"] == last["total"] == 505
    assert len(first["elements"]) == 500 and len(last["elements"]) == 5
    assert not fake.tapir_calls
    assert "API.GetPropertyValuesOfElements" not in fake.calls


async def test_missing_property_refused_before_details():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await read.find_elements(c, port=19723, property_guid=guid(1000), value=1)
    assert "GetDetailsOfElements" not in fake.tapir_calls
    assert "API.GetPropertyValuesOfElements" not in fake.calls


async def test_expensive_reads_only_for_survivors_and_batched():
    fake = model(405)
    result = await search(
        fake, element_type="Wall", layer_index=0, property_guid=PROP, operator="greater", value=0
    )
    assert result["total"] == 68
    detail_requests = [r for r in fake.tapir_requests if r["command"] == "GetDetailsOfElements"]
    assert [len(r["parameters"]["elements"]) for r in detail_requests] == [100, 100, 3]
    assert all(
        int(UUID(e["elementId"]["guid"])) % 2 == 1
        for r in detail_requests
        for e in r["parameters"]["elements"]
    )
    property_requests = [
        r for r in fake.command_requests if r["command"] == "API.GetPropertyValuesOfElements"
    ]
    assert len(property_requests) == 1
    assert all(
        int(UUID(e["elementId"]["guid"])) % 3 == 0
        for e in property_requests[0]["parameters"]["elements"]
    )


async def test_property_batches_and_empty_results():
    fake = model(205)
    result = await search(fake, property_guid=PROP, operator="less", value=0)
    assert result["total"] == 0
    requests = [
        r for r in fake.command_requests if r["command"] == "API.GetPropertyValuesOfElements"
    ]
    assert [len(r["parameters"]["elements"]) for r in requests] == [100, 100, 5]
    empty = await search(FakeArchicad(19723), floor_index=0)
    assert empty["total"] == 0


@pytest.mark.parametrize("port", [None, 19723])
async def test_property_search_resolves_target_once_across_batches(port):
    fake = model(205)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await read.find_elements(
            client, port=port, property_guid=PROP, operator="greater", value=199
        )
    assert result["total"] == 6
    assert [e["elementId"]["guid"] for e in result["elements"]] == [
        guid(i) for i in range(200, 206)
    ]
    assert result["errors"] == []
    # Count probes of the reachable instance; discovery also checks unused ports.
    probes = [r for r in fake.command_requests if r["command"] == "API.GetProductInfo"]
    assert len(probes) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 501},
        {"offset": -1},
        {"limit": 0},
        {"floor_index": True},
        {"operator": "invalid"},
        {"value": 1},
        {"property_guid": PROP, "operator": "contains", "value": 1},
        {"property_guid": PROP, "operator": "greater", "value": True},
        {"property_guid": PROP, "value": float("nan")},
    ],
)
async def test_invalid_input_before_requests(changes):
    fake = model()
    with pytest.raises(ValueError):
        await search(fake, **changes)
    assert fake.calls == []
