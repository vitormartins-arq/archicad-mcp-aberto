from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import modify, write
from tests.unit.fake_archicad import (
    CREATE_COLUMNS_FIXTURE,
    CREATE_OPENINGS_FIXTURE,
    CREATE_SLABS_FIXTURE,
    CREATE_WALLS_FIXTURE,
    MODIFY_ELEMENTS_FIXTURE,
    FakeArchicad,
    fake_transport,
)

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"  # the owner wall in the opening fixture
ELEMENT = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]
BEAM_DETAILS = {
    "type": "Beam",
    "floorIndex": 0,
    "layerIndex": 1,
    "details": {
        "begCoordinate": {"x": 0, "y": 0},
        "endCoordinate": {"x": 4, "y": 0},
        "zCoordinate": 3,
        "level": 3,
        "width": 0.2,
        "height": 0.4,
        "arcAngle": 0,
        "beamShape": "Straight",
        "circleBased": False,
        "isWidthAndHeightLinked": False,
    },
}
ROWS = {
    "Slab": CREATE_SLABS_FIXTURE["slab_details"],
    "Column": CREATE_COLUMNS_FIXTURE["column_details"],
    "Beam": BEAM_DETAILS,
    "Window": CREATE_OPENINGS_FIXTURE["window_details"],
    "Door": CREATE_OPENINGS_FIXTURE["door_details"],
    "Object": MODIFY_ELEMENTS_FIXTURE["object_details"],
}
TOOLS = {
    "Slab": (modify.modify_slabs, "ModifySlabs", "slabsWithDetails"),
    "Column": (modify.modify_columns, "ModifyColumns", "columnsWithDetails"),
    "Beam": (modify.modify_beams, "ModifyBeams", "beamsWithDetails"),
    "Window": (modify.modify_windows, "ModifyWindows", "windowsWithDetails"),
    "Door": (modify.modify_doors, "ModifyDoors", "doorsWithDetails"),
    "Object": (modify.modify_objects, "ModifyObjects", "objectsWithDetails"),
}
SAMPLE = {
    "Slab": {"thickness": 0.25},
    "Column": {"height": 3.5},
    "Beam": {"level": 2.8},
    "Window": {"width": 1.5},
    "Door": {"height": 2.2},
    "Object": {"origin": {"x": 5, "y": 6}},
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(kind, **kwargs):
    wall = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    return FakeArchicad(
        19723,
        stories=deepcopy(STORIES),
        elements={ELEMENT: kind, OTHER: kind, GUID: "Wall"},
        details={ELEMENT: deepcopy(ROWS[kind]), OTHER: deepcopy(ROWS[kind]), GUID: wall},
        **kwargs,
    )


async def apply(c, kind, edits):
    tool = TOOLS[kind][0]
    preview = await tool(c, edits, 19723)
    return await tool(c, edits, 19723, False, preview["confirmation_token"])


def sent(fake, kind):
    _, command, key = TOOLS[kind]
    return next(r for r in fake.tapir_requests if r["command"] == command)["parameters"][key]


@pytest.mark.parametrize("kind", list(TOOLS))
async def test_preview_then_apply_verified(kind):
    fake = model(kind)
    edits = [{"guid": ELEMENT, **SAMPLE[kind]}]
    tool, command, _ = TOOLS[kind]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, edits, 19723)
        assert preview["items"][0]["before"]["type"] == kind
        assert preview["items"][0]["new"] == SAMPLE[kind]
        assert command not in fake.tapir_calls
        result = await tool(c, edits, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await tool(c, edits, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert fake.tapir_calls.count(command) == 1
    assert result["items"][0][f"{kind.lower()}_edit_receipt_id"]
    assert result["receipt_path"]


@pytest.mark.parametrize(
    ("kind", "change", "payload", "after"),
    [
        ("Slab", {"thickness": 0.3}, {"thickness": 0.3}, {"thickness": 0.3}),
        ("Slab", {"level": 0.5}, {"zCoordinate": 0.5}, {"level": 0.5, "zCoordinate": 0.5}),
        ("Column", {"origin": {"x": 1, "y": 2}}, {"origin": {"x": 1, "y": 2}}, None),
        (
            "Column",
            {"bottomOffset": -0.2},
            {"bottomOffset": -0.2},
            {"bottomOffset": -0.2, "zCoordinate": -0.2},
        ),
        ("Column", {"height": 4.0}, {"height": 4.0}, {"height": 4.0, "relativeTopStory": 0}),
        ("Column", {"width": 0.4, "depth": 0.6}, {"width": 0.4, "depth": 0.6}, None),
        ("Beam", {"begCoordinate": {"x": 1, "y": 1}}, {"begCoordinate": {"x": 1, "y": 1}}, None),
        ("Beam", {"level": 2.5}, {"level": 2.5}, {"level": 2.5, "zCoordinate": 2.5}),
        ("Beam", {"width": 0.25, "height": 0.5}, {"width": 0.25, "height": 0.5}, None),
        ("Window", {"sillHeight": 1.1}, {"sillHeight": 1.1}, None),
        ("Window", {"centerOffset": 2.0}, {"centerOffset": 2.0}, None),
        ("Door", {"width": 0.9, "height": 2.1}, {"width": 0.9, "height": 2.1}, None),
        (
            "Object",
            {"origin": {"x": 7, "y": 8}},
            {"coordinates": {"x": 7, "y": 8, "z": 0}},
            {"origin": {"x": 7, "y": 8, "z": 0}},
        ),
        (
            "Object",
            {"level": 0.4},
            {"coordinates": {"x": 2, "y": 3, "z": 0.4}},
            {"origin": {"x": 2, "y": 3, "z": 0.4}},
        ),
        (
            "Object",
            {"dimensions": {"x": 2, "y": 1, "z": 0.9}},
            {"dimensions": {"x": 2, "y": 1, "z": 0.9}},
            None,
        ),
    ],
)
async def test_each_field_sends_native_payload(kind, change, payload, after):
    fake = model(kind)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, kind, [{"guid": ELEMENT, **change}])
    assert result["status"] == "verified"
    assert sent(fake, kind) == [{"elementId": {"guid": ELEMENT}, **payload}]
    details = result["items"][0]["after"]["details"]
    for key, value in (after or payload).items():
        assert details[key] == value


async def test_below_lowest_story_stays_on_it():
    # Tapir keeps z under the lowest story on story 0 (GetFloorIndexAndOffset).
    fake = model("Slab")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "Slab", [{"guid": ELEMENT, "level": -0.5}])
    assert result["status"] == "verified"


async def test_slab_level_on_upper_story_uses_absolute_z():
    fake = model("Slab")
    fake.details[ELEMENT]["floorIndex"] = 1
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "Slab", [{"guid": ELEMENT, "level": 0.2}])
    assert sent(fake, "Slab")[0]["zCoordinate"] == pytest.approx(3.2)
    assert result["status"] == "verified"


@pytest.mark.parametrize(
    ("kind", "floor", "change"),
    [
        ("Slab", 0, {"level": 3.5}),
        ("Slab", 1, {"level": -0.1}),
        ("Object", 0, {"level": 3.0}),
        ("Object", 1, {"level": -1.0}),
    ],
)
async def test_level_that_changes_story_refused(kind, floor, change):
    fake = model(kind)
    fake.details[ELEMENT]["floorIndex"] = floor
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="another story"):
            await TOOLS[kind][0](c, [{"guid": ELEMENT, **change}], 19723)
    assert TOOLS[kind][1] not in fake.tapir_calls


async def test_composite_slab_thickness_refused():
    fake = model("Slab")
    fake.details[ELEMENT]["details"]["structureType"] = "Composite"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Basic"):
            await modify.modify_slabs(c, [{"guid": ELEMENT, "thickness": 0.3}], 19723)


@pytest.mark.parametrize(("kind", "second"), [("Column", "depth"), ("Beam", "height")])
async def test_linked_section_sends_one_size_for_both(kind, second):
    fake = model(kind)
    fake.details[ELEMENT]["details"].update(circleBased=True, isWidthAndHeightLinked=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, kind, [{"guid": ELEMENT, "width": 0.45}])
        assert result["status"] == "verified"
        assert sent(fake, kind)[0]["width"] == sent(fake, kind)[0][second] == 0.45
        with pytest.raises(ValueError, match="linked"):
            await TOOLS[kind][0](c, [{"guid": ELEMENT, "width": 0.4, second: 0.5}], 19723)


@pytest.mark.parametrize(
    "metadata", [{"beamShape": "HorizontallyCurved"}, {"arcAngle": 0.3}, {"arcAngle": None}]
)
async def test_curved_beam_refused(metadata):
    fake = model("Beam")
    fake.details[ELEMENT]["details"].update(metadata)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="curved"):
            await modify.modify_beams(c, [{"guid": ELEMENT, "level": 1.0}], 19723)


async def test_zero_length_beam_refused():
    fake = model("Beam")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="zero length"):
            await modify.modify_beams(
                c, [{"guid": ELEMENT, "endCoordinate": {"x": 0, "y": 0}}], 19723
            )


async def test_opening_center_offset_past_wall_end_refused():
    fake = model("Window")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="past the wall end"):
            await modify.modify_windows(c, [{"guid": ELEMENT, "centerOffset": 50.0}], 19723)
    assert "ModifyWindows" not in fake.tapir_calls


async def test_opening_outside_wall_refused():
    fake = model("Door")
    fake.details[ELEMENT]["details"]["ownerElementType"] = "Roof"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="openings in walls"):
            await modify.modify_doors(c, [{"guid": ELEMENT, "width": 1.0}], 19723)


@pytest.mark.parametrize("kind", list(TOOLS))
@pytest.mark.parametrize("reason", ["hotlink", "locked", "missing", "wrong-type"])
async def test_unsafe_targets_refused(kind, reason):
    fake = model(kind)
    if reason == "hotlink":
        fake.details[ELEMENT]["hotlinkId"] = {"guid": OTHER}
    elif reason == "locked":
        fake.locked_elements.add(ELEMENT)
    elif reason == "missing":
        del fake.elements[ELEMENT]
        del fake.details[ELEMENT]
    else:
        fake.elements[ELEMENT] = "Wall"
        fake.details[ELEMENT] = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await TOOLS[kind][0](c, [{"guid": ELEMENT, **SAMPLE[kind]}], 19723)
    assert TOOLS[kind][1] not in fake.tapir_calls


@pytest.mark.parametrize(
    "edits",
    [
        [],
        [{"guid": ELEMENT, "width": 1.0}] * 51,
        [{"guid": ELEMENT, "width": 1.0}, {"guid": ELEMENT, "width": 2.0}],
        [{"guid": ELEMENT}],
        [{"guid": ELEMENT, "width": 0}],
        [{"guid": ELEMENT, "centerOffset": -1.0}],
        [{"guid": ELEMENT, "sillHeight": float("nan")}],
        [{"guid": ELEMENT, "reflected": True}],
        [{"guid": ELEMENT, "width": True}],
        [{"guid": "not-a-guid", "width": 1.0}],
    ],
)
async def test_limits_and_unknown_fields_before_network(edits):
    fake = model("Window")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await modify.modify_windows(c, edits)
    assert not fake.calls


async def test_partial_native_error():
    fake = model(
        "Column",
        modify_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}},
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, "Column", [{"guid": ELEMENT, "height": 4.0}, {"guid": OTHER, "height": 4.0}]
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("kind", list(TOOLS))
async def test_ignored_edit_fails_verification(kind):
    fake = model(kind, modify_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, kind, [{"guid": ELEMENT, **SAMPLE[kind]}])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"]


async def test_changed_element_requires_new_preview():
    fake = model("Slab")
    edits = [{"guid": ELEMENT, "thickness": 0.3}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_slabs(c, edits, 19723)
        fake.details[ELEMENT]["details"]["thickness"] = 0.15
        with pytest.raises(ValueError, match="changed"):
            await modify.modify_slabs(c, edits, 19723, False, preview["confirmation_token"])
    assert "ModifySlabs" not in fake.tapir_calls


async def test_apply_requires_explicit_port():
    fake = model("Beam")
    edits = [{"guid": ELEMENT, "level": 2.0}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_beams(c, edits)
        with pytest.raises(ValueError, match="explicit port"):
            await modify.modify_beams(c, edits, None, False, preview["confirmation_token"])
    assert "ModifyBeams" not in fake.tapir_calls


async def test_lost_response_unknown_and_consumed():
    fake = model("Object", lose_modify_response=True)
    edits = [{"guid": ELEMENT, "origin": {"x": 1, "y": 1}}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_objects(c, edits, 19723)
        result = await modify.modify_objects(c, edits, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await modify.modify_objects(c, edits, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert "Never retry" in result["warning"]
    assert fake.tapir_calls.count("ModifyObjects") == 1


async def test_journal_failure_prevents_dispatch(monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    fake = model("Door")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(c, "Door", [{"guid": ELEMENT, "width": 1.0}])
    assert "ModifyDoors" not in fake.tapir_calls
