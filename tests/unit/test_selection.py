import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import selection
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
BEAM = "33333333-3333-4333-8333-333333333333"
COLUMN = "44444444-4444-4444-8444-444444444444"
MISSING = "99999999-9999-4999-8999-999999999999"
GROUP = "55555555-5555-4555-8555-000000000009"
TYPES = {WALL: "Wall", SLAB: "Slab", BEAM: "Beam", COLUMN: "Column"}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements=dict(TYPES),
        details={
            g: {"type": t, "floorIndex": 0, "layerIndex": 1, "details": {}}
            for g, t in TYPES.items()
        },
        **kwargs,
    )


async def apply(c, groups):
    preview = await selection.create_groups(c, groups, 19723)
    return await selection.create_groups(c, groups, 19723, False, preview["confirmation_token"])


async def test_replace_add_remove_and_clear():
    fake = model(selection=[SLAB, BEAM])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        replaced = await selection.select_elements(c, [WALL.lower(), BEAM], 19723)
        assert fake.selection == [BEAM, WALL]
        added = await selection.select_elements(c, [COLUMN], 19723, "add")
        removed = await selection.select_elements(c, [BEAM], 19723, "remove")
        cleared = await selection.select_elements(c, [], 19723)
    assert replaced["status"] == "verified" and replaced["selected_count"] == 2
    assert [r["element_guid"] for r in replaced["removed"]] == [SLAB]
    assert added["selected_count"] == 3 and removed["selected_count"] == 2
    assert cleared["status"] == "verified" and fake.selection == []
    request = next(r for r in fake.tapir_requests if r["command"] == "ChangeSelectionOfElements")
    assert request["parameters"] == {
        "addElementsToSelection": [{"elementId": {"guid": WALL}}, {"elementId": {"guid": BEAM}}],
        "removeElementsFromSelection": [{"elementId": {"guid": SLAB}}],
    }


async def test_selection_reports_what_did_not_take():
    fake = model(select_refused={SLAB})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await selection.select_elements(c, [WALL, SLAB, MISSING], 19723)
    assert result["status"] == "verification_failed"
    assert result["not_selected"] == [SLAB, MISSING]
    assert [r["ok"] for r in result["added"]] == [True, False, False]


async def test_selection_input_refusals():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await selection.select_elements(c, [], 19723, "add")
        with pytest.raises(ValueError, match="only once"):
            await selection.select_elements(c, [WALL, WALL.lower()], 19723)
        with pytest.raises(ValueError):
            await selection.select_elements(c, ["not-a-guid"], 19723)
        with pytest.raises(ValueError):
            await selection.select_elements(c, [str(i) * 1 for i in range(101)], 19723)
    assert not fake.calls


async def test_highlight_and_clear():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await selection.highlight_elements(
            c, [WALL, SLAB], 19723, [0, 128, 255], wireframe_3d=True
        )
        assert fake.highlight == {
            "elements": [{"elementId": {"guid": WALL}}, {"elementId": {"guid": SLAB}}],
            "highlightedColors": [[0, 128, 255, 255]] * 2,
            "wireframe3D": True,
        }
        cleared = await selection.highlight_elements(c, [], 19723)
        with pytest.raises(ValueError, match="color"):
            await selection.highlight_elements(c, [WALL], 19723, [0, 0, 256])
        with pytest.raises(ValueError, match="color"):
            await selection.highlight_elements(c, [WALL], 19723, [0, 0])
    assert result["status"] == "done" and result["highlighted"] == 2
    assert cleared["cleared"] and fake.highlight == {"elements": [], "highlightedColors": []}


async def test_get_element_groups():
    fake = model(groups={GROUP: [WALL, SLAB]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await selection.get_element_groups(c, [WALL, BEAM], 19723)
    assert result["elements"] == [
        {"element_guid": WALL, "group_guid": GROUP},
        {"element_guid": BEAM, "group_guid": None},
    ]
    assert result["groups"] == [{"group_guid": GROUP, "element_guids": [WALL, SLAB]}]


async def test_create_groups_preview_then_apply():
    fake = model()
    groups = [{"element_guids": [WALL, SLAB.lower()]}, {"element_guids": [BEAM, COLUMN]}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await selection.create_groups(c, groups, 19723)
        assert "CreateGroups" not in fake.tapir_calls
        assert preview["items"][0]["members"] == [
            {"element_guid": WALL, "type": "Wall"},
            {"element_guid": SLAB, "type": "Slab"},
        ]
        token = preview["confirmation_token"]
        result = await selection.create_groups(c, groups, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await selection.create_groups(c, groups, 19723, False, token)
    assert result["status"] == "verified"
    assert all(i["group_receipt_id"] for i in result["items"])
    assert {frozenset(m) for m in fake.groups.values()} == {
        frozenset({WALL, SLAB}),
        frozenset({BEAM, COLUMN}),
    }


async def test_create_groups_refusals():
    fake = model(groups={GROUP: [WALL, SLAB]}, locked_elements={COLUMN})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Already in a group"):
            await selection.create_groups(c, [{"element_guids": [WALL, BEAM]}], 19723)
        with pytest.raises(ValueError, match="Locked"):
            await selection.create_groups(c, [{"element_guids": [BEAM, COLUMN]}], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await selection.create_groups(c, [{"element_guids": [BEAM, MISSING]}], 19723)
        with pytest.raises(ValueError, match="only one new group"):
            await selection.create_groups(
                c, [{"element_guids": [BEAM, COLUMN]}, {"element_guids": [BEAM, SLAB]}], 19723
            )
        for bad in ([{"element_guids": [BEAM]}], [], [{"element_guids": [BEAM, COLUMN]}] * 21):
            with pytest.raises(ValueError):
                await selection.create_groups(c, bad, 19723)
    assert "CreateGroups" not in fake.tapir_calls


async def test_create_groups_failed_mismatch_and_lost():
    error = {"error": {"code": -1, "message": "Failed to create group."}}
    fake = model(group_create_errors={0: error})
    groups = [{"element_guids": [WALL, SLAB]}, {"element_guids": [BEAM, COLUMN]}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, groups)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await selection.create_groups(c, groups[:1], 19723)
        original = fake._tapir

        def stored(params):
            response = original(params)
            if params["addOnCommandId"]["commandName"] == "CreateGroups":
                for members in fake.groups.values():
                    members.pop()
            return response

        fake._tapir = stored
        result = await selection.create_groups(
            c, groups[:1], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verification_failed"
    fake = model(lose_group_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, groups[:1])
        preview = await selection.create_groups(c, groups[1:])
        with pytest.raises(ValueError, match="explicit port"):
            await selection.create_groups(c, groups[1:], None, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateGroups") == 1
