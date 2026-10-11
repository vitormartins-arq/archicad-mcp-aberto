"""P-005: target selection against MockTransport only; never a real Archicad."""

import inspect
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient, resolve_port
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import attributes, read, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
PROP = "22222222-2222-2222-2222-222222222222"
INPUTS = {
    "create_columns": {
        "columns": [
            {
                "origin": {"x": 0, "y": 0},
                "floor_index": 0,
                "height": 3,
                "base_level": 0,
                "width": 0.3,
                "depth": 0.5,
            }
        ]
    },
    "list_building_materials": {},
    "list_elements": {},
    "get_selection": {},
    "list_properties": {},
    "get_properties": {"element_guids": [GUID], "property_guids": [PROP]},
    "get_project_info": {},
    "get_stories": {},
    "get_element_details": {"element_guids": [GUID]},
    "create_walls": {
        "walls": [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 4, "y": 0},
                "floor_index": 0,
                "height": 3,
                "thickness": 0.2,
            }
        ]
    },
    # This branch starts from main before PR #5; include slabs once that tool is merged.
    "create_slabs": {
        "slabs": [
            {
                "outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}],
                "floor_index": 0,
                "thickness": 0.2,
                "level": 0,
            }
        ]
    },
}
TARGETED = {
    name: function
    for module in (attributes, read, write)
    for name, function in inspect.getmembers(module, inspect.iscoroutinefunction)
    if function.__module__ == module.__name__
    and not name.startswith("_")
    and "port" in inspect.signature(function).parameters
}


def instances(second_state="ready"):
    first = FakeArchicad(
        19723,
        project_name="First",
        elements={GUID: "Wall"},
        selection=[GUID],
        properties={PROP: "Test property"},
    )
    second = FakeArchicad(
        19724,
        project_name="Second",
        elements={GUID: "Wall"},
        selection=[GUID],
        properties={PROP: "Test property"},
        busy=second_state == "busy",
        tapir_version=None if second_state == "no_tapir" else "1.7.0",
    )
    return first, second


def client(first, second, reversed_ports=False):
    ports = (19724, 19723) if reversed_ports else (19723, 19724)
    return ArchicadClient(ports=ports, transport=fake_transport(first, second))


async def test_all_registered_targeted_tools_have_cases():
    tools = await create_server().list_tools()
    registered = {tool.name for tool in tools if "port" in tool.inputSchema["properties"]}
    assert registered == set(TARGETED)
    assert registered <= INPUTS.keys()


@pytest.mark.parametrize("name", sorted(TARGETED))
@pytest.mark.parametrize("explicit_none", [False, True], ids=["omitted-port", "null-port"])
@pytest.mark.parametrize("second_state", ["ready", "busy", "no_tapir"])
async def test_every_targeted_tool_refuses_two_instances(
    name, explicit_none, second_state, tmp_path, monkeypatch
):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    first, second = instances(second_state)
    arguments = deepcopy(INPUTS[name])
    if explicit_none:
        arguments["port"] = None
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget, match="19723, 19724"):
            await TARGETED[name](c, **arguments)
    # Discovery probes both ports, but no model read/write may choose either instance.
    assert first.calls == second.calls == ["API.GetProductInfo"]
    assert first.tapir_calls == second.tapir_calls == []
    assert first.elements == second.elements == {GUID: "Wall"}
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("name", sorted(TARGETED))
async def test_reversing_probe_order_does_not_select_first_instance(name):
    first, second = instances()
    async with client(first, second, reversed_ports=True) as c:
        with pytest.raises(AmbiguousTarget, match="19724, 19723"):
            await TARGETED[name](c, **deepcopy(INPUTS[name]))
    assert first.calls == second.calls == ["API.GetProductInfo"]


@pytest.mark.parametrize("name", sorted(TARGETED))
@pytest.mark.parametrize("port", [19723, 19724])
async def test_explicit_port_reaches_only_requested_instance(name, port):
    first, second = instances()
    async with client(first, second) as c:
        result = await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
    selected, untouched = (first, second) if port == 19723 else (second, first)
    result_port = result["target"]["port"] if name.startswith("create_") else result["port"]
    assert result_port == port
    assert selected.calls and untouched.calls == []
    assert selected.elements == untouched.elements == {GUID: "Wall"}
    assert not any("Create" in command or "Save" in command for command in selected.tapir_calls)


@pytest.mark.parametrize("reversed_ports", [False, True])
async def test_resolver_never_guesses_even_after_an_explicit_call(reversed_ports):
    first, second = instances()
    async with client(first, second, reversed_ports) as c:
        assert await resolve_port(c, 19724) == 19724
        with pytest.raises(AmbiguousTarget):
            await resolve_port(c, None)
        assert await resolve_port(c, 19723) == 19723


@pytest.mark.parametrize("name", ["discover_archicad", "tapir_status"])
async def test_instance_inventory_tools_report_both_without_selecting(name):
    first, second = instances()
    async with client(first, second) as c:
        result = await getattr(read, name)(c)
    assert {item["port"] for item in result["instances"]} == {19723, 19724}
    assert result["status"] == "connected"


@pytest.mark.parametrize("name", [n for n in TARGETED if n.startswith("create_")])
async def test_write_apply_requires_explicit_port_before_dispatch(name, tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    first, second = instances()
    arguments = deepcopy(INPUTS[name])
    async with client(first, second) as c:
        preview = await TARGETED[name](c, port=19724, **arguments)
        first.calls.clear()
        second.calls.clear()
        first.tapir_calls.clear()
        second.tapir_calls.clear()
        with pytest.raises(ValueError, match="explicit port"):
            await TARGETED[name](
                c, dry_run=False, confirmation_token=preview["confirmation_token"], **arguments
            )
    assert first.calls == second.calls == []
    assert first.tapir_calls == second.tapir_calls == []
    assert not (tmp_path / "receipts").exists()
