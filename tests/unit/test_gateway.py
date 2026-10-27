import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import TapirError
from archicad_mcp_aberto.tools import gateway
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"


def model():
    return FakeArchicad(19723, elements={GUID: "Wall"})


async def test_official_command_returns_raw_result():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await gateway.run_read_command(c, "API.GetAllElements", port=19723)
    assert result["port"] == 19723 and result["command"] == "API.GetAllElements"
    assert result["response"] == {"elements": [{"elementId": {"guid": GUID}}]}
    assert fake.calls[-1] == "API.GetAllElements"


async def test_tapir_command_passes_parameters_unchanged():
    fake = model()
    parameters = {"elements": [{"elementId": {"guid": GUID}}], "fields": ["type"]}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await gateway.run_read_command(c, "Tapir.GetDetailsOfElements", parameters, 19723)
    assert result["response"] == {"detailsOfElements": [{"type": "Wall"}]}
    assert fake.tapir_requests[-1] == {"command": "GetDetailsOfElements", "parameters": parameters}


async def test_single_instance_is_found_without_port():
    fake = model()
    async with ArchicadClient(ports=(19723,), transport=fake_transport(fake)) as c:
        result = await gateway.run_read_command(c, "Tapir.GetStories")
    assert result["response"]["stories"][0]["name"] == "Térreo"


@pytest.mark.parametrize(
    "command",
    [
        "API.SetPropertyValuesOfElements",
        "API.ExecuteAddOnCommand",
        "API.DeleteAttributes",
        "API.CreateLayout",
        "Tapir.CreateWalls",
        "Tapir.DeleteElements",
        "Tapir.ModifyWalls",
        "Tapir.SaveProject",
        "Tapir.SetStories",
        "Tapir.QuitArchicad",
        "Tapir.GetPointFromUser",
        "Tapir.GetUserGSID",
        "Tapir.GetNotARealCommand",
        "Tapir.getstories",
        "GetAllElements",
        "Other.GetAllElements",
        "API.",
        "",
    ],
)
async def test_unlisted_commands_never_reach_archicad(command):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await gateway.run_read_command(c, command, port=19723)
    assert fake.calls == [] and fake.tapir_calls == []


def test_lists_hold_only_read_names():
    names = gateway.OFFICIAL_READ_COMMANDS | gateway.TAPIR_READ_COMMANDS
    assert all(n.startswith(("Get", "Is", "Filter")) for n in names)
    for word in ("Set", "Create", "Delete", "Modify", "Save", "Execute", "Move", "Rename"):
        assert not any(n.startswith(word) for n in names)


def test_gateway_doc_lists_exactly_the_allowed_commands():
    from pathlib import Path

    text = (Path(__file__).parents[2] / "docs" / "GATEWAY.md").read_text(encoding="utf-8")
    for name in gateway.OFFICIAL_READ_COMMANDS:
        assert f"`API.{name}`" in text, name
    for name in gateway.TAPIR_READ_COMMANDS:
        assert f"`Tapir.{name}`" in text, name


async def test_oversized_or_non_object_parameters_are_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="at most"):
            await gateway.run_read_command(
                c, "Tapir.GetStories", {"x": "a" * 1_000_001}, port=19723
            )
        with pytest.raises(ValueError, match="JSON object"):
            await gateway.run_read_command(c, "Tapir.GetStories", ["x"], port=19723)
    assert fake.calls == []


async def test_tapir_error_is_raised_not_hidden():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(TapirError):
            await gateway.run_read_command(c, "Tapir.GetAutoTextKeys", port=19723)
