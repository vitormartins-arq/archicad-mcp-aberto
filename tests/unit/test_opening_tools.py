from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import openings
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-1111-1111-111111111111"
SLAB = "22222222-2222-2222-2222-222222222222"
TOOLS = {"create_windows": openings.create_windows, "create_doors": openings.create_doors}
COMMANDS = {"create_windows": "CreateWindows", "create_doors": "CreateDoors"}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    # The fixture wall runs from (0, 15) to (4, 15): 4 m long.
    return FakeArchicad(
        19723,
        elements={WALL: "Wall", SLAB: "Slab"},
        details={
            WALL: deepcopy(CREATE_WALLS_FIXTURE["wall_details"]),
            SLAB: {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}},
        },
        **kwargs,
    )


async def apply(c, operation, rows):
    tool = TOOLS[operation]
    preview = await tool(c, rows, 19723)
    return await tool(c, rows, 19723, False, preview["confirmation_token"])


@pytest.mark.parametrize("operation", sorted(TOOLS))
async def test_preview_then_apply_verifies_owner_offset_and_size(operation):
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 1.5, "width": 1.0, "height": 1.4}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await TOOLS[operation](c, rows, 19723)
        assert COMMANDS[operation] not in fake.tapir_calls
        item = preview["items"][0]
        assert item["wall_length"] == 4
        assert item["floorName"] == "Térreo" and item["layerIndex"] == 22
        assert item["library_part"].endswith("tool default")
        result = await TOOLS[operation](c, rows, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await TOOLS[operation](c, rows, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["library_part_name"] in {"Janela 30", "Porta 30"}
    receipt_key = "window_receipt_id" if operation == "create_windows" else "door_receipt_id"
    assert item[receipt_key]
    request = next(r for r in fake.tapir_requests if r["command"] == COMMANDS[operation])
    data = request["parameters"]["windowsData" if operation == "create_windows" else "doorsData"]
    assert data == [
        {"ownerWallId": {"guid": WALL}, "centerOffset": 1.5, "width": 1.0, "height": 1.4}
    ]
    assert "Save" not in " ".join(fake.calls + fake.tapir_calls)


async def test_sill_height_and_favorite_are_sent_and_checked():
    fake = model()
    rows = [
        {
            "wall_guid": WALL,
            "center_offset": 2.0,
            "sill_height": 1.1,
            "favorite_name": "Janela padrão",
        }
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "create_windows", rows)
    assert result["status"] == "verified"
    assert result["items"][0]["library_part"] == "Janela padrão"
    assert result["items"][0]["library_part_name"] == "Janela padrão (peça)"
    assert result["items"][0]["after"]["details"]["sillHeight"] == 1.1
    assert "GetFavoritesByType" in fake.tapir_calls


async def test_unknown_favorite_is_refused_in_preview():
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 2.0, "favorite_name": "Porta padrão"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="No Window favorite named 'Porta padrão'"):
            await openings.create_windows(c, rows, 19723)
    assert "CreateWindows" not in fake.tapir_calls


@pytest.mark.parametrize(
    "setup, rows, message",
    [
        (None, [{"wall_guid": SLAB, "center_offset": 1}], "not a wall"),
        (None, [{"wall_guid": WALL, "center_offset": 4.5}], "past the wall end"),
        ("curved", [{"wall_guid": WALL, "center_offset": 1}], "only straight walls"),
        ("locked", [{"wall_guid": WALL, "center_offset": 1}], "non-editable"),
        ("hotlink", [{"wall_guid": WALL, "center_offset": 1}], "hotlink"),
        (
            None,
            [{"wall_guid": "33333333-3333-3333-3333-333333333333", "center_offset": 1}],
            "does not exist",
        ),
    ],
)
async def test_preview_refuses_bad_owners(setup, rows, message):
    fake = model()
    if setup == "curved":
        fake.details[WALL]["details"]["geometryType"] = "Curved"
    elif setup == "locked":
        fake.locked_elements.add(WALL)
    elif setup == "hotlink":
        fake.details[WALL]["hotlinkId"] = {"guid": SLAB}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await openings.create_doors(c, rows, 19723)
    assert "CreateDoors" not in fake.tapir_calls


@pytest.mark.parametrize(
    "row",
    [
        {"wall_guid": WALL, "center_offset": -0.1},
        {"wall_guid": WALL, "center_offset": 1, "width": 0},
        {"wall_guid": WALL, "center_offset": 1, "height": -1},
        {"wall_guid": WALL, "center_offset": 1, "favorite_name": " Porta"},
        {"wall_guid": WALL, "center_offset": 1, "library_part_name": "Porta"},
        {"wall_guid": "not-a-guid", "center_offset": 1},
    ],
)
async def test_invalid_input_is_refused_before_archicad(row):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await openings.create_doors(c, [row], 19723)
    assert fake.calls == []


async def test_count_limits():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="between 1 and 20 windows"):
            await openings.create_windows(c, [], 19723)
        with pytest.raises(ValueError, match="between 1 and 20 doors"):
            await openings.create_doors(c, [{"wall_guid": WALL, "center_offset": 1}] * 21)


async def test_apply_needs_explicit_port():
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 1}]
    async with ArchicadClient(ports=(19723,), transport=fake_transport(fake)) as c:
        preview = await openings.create_doors(c, rows)
        with pytest.raises(ValueError, match="explicit port"):
            await openings.create_doors(c, rows, None, False, preview["confirmation_token"])
    assert "CreateDoors" not in fake.tapir_calls


async def test_changed_wall_after_preview_blocks_apply():
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 1}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await openings.create_doors(c, rows, 19723)
        fake.details[WALL]["details"]["endCoordinate"] = {"x": 6, "y": 15}
        with pytest.raises(ValueError, match="changed since preview"):
            await openings.create_doors(c, rows, 19723, False, preview["confirmation_token"])
    assert "CreateDoors" not in fake.tapir_calls


async def test_per_item_errors_keep_other_items():
    fake = model(create_errors={0: {"error": {"code": -1, "message": "Failed to create door."}}})
    rows = [{"wall_guid": WALL, "center_offset": 1}, {"wall_guid": WALL, "center_offset": 3}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "create_doors", rows)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    assert result["status"] == "needs_review"


async def test_lost_response_is_unknown_and_never_retried():
    fake = model(lose_opening_response=True)
    rows = [{"wall_guid": WALL, "center_offset": 1}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "create_windows", rows)
    assert result["items"][0]["status"] == "unknown"
    assert "do not retry" in result["warning"]
    assert fake.tapir_calls.count("CreateWindows") == 1


async def test_wrong_owner_or_offset_fails_verification():
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 1}]
    original = fake._tapir

    def drifting(params):
        response = original(params)
        if params["addOnCommandId"]["commandName"] == "CreateDoors":
            for row in fake.details.values():
                if row.get("type") == "Door":
                    row["details"]["centerOffset"] = 1.2
        return response

    fake._tapir = drifting
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "create_doors", rows)
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["details.centerOffset"]


async def test_owner_guid_case_does_not_fail_verification():
    fake = model()
    rows = [{"wall_guid": WALL, "center_offset": 1}]
    original = fake._tapir

    def lowercase(params):
        response = original(params)
        if params["addOnCommandId"]["commandName"] == "CreateDoors":
            for row in fake.details.values():
                if row.get("type") == "Door":
                    row["details"]["ownerElementId"]["guid"] = WALL.lower()
        return response

    fake._tapir = lowercase
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "create_doors", rows)
    assert result["status"] == "verified"
