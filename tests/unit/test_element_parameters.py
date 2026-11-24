"""General parameter layer: capabilities, inspection and GDL/marker edits (simulated only)."""

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, parameters, read
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
DOOR = "D0000000-0000-4000-8000-000000000001"
WALL = "A0000000-0000-4000-8000-000000000001"
STAIR = "5A000000-0000-4000-8000-000000000001"
SYSTEM = "1C4E9A10-3B7F-4D2A-9E61-0A5B7C3D2E11"
PART = "0F0F0F0F-0000-4000-8000-0000000000AA"
ITEM = "11111111-2222-4333-8444-555555555555"
FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir173_door_gdl_parameters_documented.json")
    .read_text(encoding="utf-8")
)  # fmt: skip


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def door_details():
    return {
        "type": "Door",
        "floorIndex": 0,
        "layerIndex": 1,
        "details": {
            "libPart": {"name": "Porta fixture", "ownUnID": {"guid": PART}},
            "ownerElementId": {"guid": WALL},
            "ownerElementType": "Wall",
            "width": 0.9,
            "height": 2.1,
            "sillHeight": 0.0,
            "centerOffset": 1.5,
            "reflected": False,
            "refSide": True,
            "oSide": False,
        },
    }  # fmt: skip


def model(**kwargs):
    kwargs.setdefault("tapir_version", "1.7.3")
    fake = FakeArchicad(
        19723,
        elements={DOOR: "Door", WALL: "Wall", STAIR: "Stair"},
        details={
            DOOR: door_details(),
            WALL: {"type": "Wall", "floorIndex": 0, "layerIndex": 1, "details": {}},
            STAIR: {"type": "Stair", "floorIndex": 0, "layerIndex": 1, "details": {}},
        },
        gdl_parameters={DOOR: deepcopy(FIXTURE["parameters"])},
        marker_parameters={DOOR: deepcopy(FIXTURE["marker"])},
        **kwargs,
    )
    fake.classifications[(DOOR, SYSTEM)] = ITEM
    return fake


def change(name, value, target="gdl"):
    return {"element_guid": DOOR, "name": name, "value": value, "target": target}


async def apply(c, changes, **kwargs):
    preview = await parameters.set_element_parameters(c, changes, 19723, **kwargs)
    result = await parameters.set_element_parameters(
        c, changes, 19723, False, preview["confirmation_token"], **kwargs
    )
    return preview, result


async def test_get_gdl_parameters_reads_doors_and_never_sends_walls():
    """The reported failure: a door was refused as 'not an Object'."""
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.get_gdl_parameters(c, [DOOR, WALL], 19723)
    door, wall = result["gdlParametersOfElements"]
    assert door["type"] == "Door" and door["parameters"] == FIXTURE["parameters"]
    assert "no GDL parameters" in wall["error"]["message"]
    sent = [r for r in fake.tapir_requests if r["command"] == "GetGDLParametersOfElements"]
    assert sent[0]["parameters"]["elements"] == [{"elementId": {"guid": DOOR}}]


async def test_set_gdl_parameters_now_accepts_doors_and_refuses_walls():
    fake = model()
    changes = [{"element_guid": DOOR, "name": "fx_handle_height", "value": 1.0}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.set_gdl_parameters(c, changes, 19723)
        result = await edit.set_gdl_parameters(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="Wall elements have no GDL"):
            await edit.set_gdl_parameters(
                c, [{"element_guid": WALL, "name": "A", "value": 1.0}], 19723
            )
    assert preview["items"][0]["before"]["value"] == 1.05
    assert result["counts"]["verified"] == 1


async def test_capabilities_by_type_need_no_archicad():
    result = await parameters.get_element_capabilities(None, element_types=["Door", "Stair"])
    door, stair = result["types"]
    assert door["gdl"]["read"] and door["gdl"]["write"]
    assert door["marker"]["requires_tapir"] == "1.7.1"
    assert door["native"]["write"][0]["tool"] == "modify_doors"
    assert "sillHeight" in door["native"]["write"][0]["fields"]
    assert "reflected" in door["native"]["tapir_only_fields"]
    assert not stair["gdl"]["read"] and stair["native"]["write"] == []
    assert "No Modify command" in stair["native"]["limitation"]


async def test_capabilities_of_elements_report_locks_hotlinks_and_version():
    fake = model(tapir_version="1.7.0")
    fake.locked_elements.add(WALL)
    fake.details[STAIR]["hotlinkId"] = {"guid": "00000000-0000-4000-8000-0000000000FF"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await parameters.get_element_capabilities(c, [DOOR, WALL, STAIR], port=19723)
    door, wall, stair = result["elements"]
    assert result["tapir_version"] == "1.7.0"
    assert door["editable"] and door["capabilities"]["marker"]["blocked"] == "needs Tapir 1.7.1"
    assert door["capabilities"]["gdl"]["arrays"] == {"blocked": "needs Tapir 1.7.2"}
    assert not wall["editable"] and "locked" in wall["edit_blocked_reasons"][0]
    assert not stair["editable"] and "hotlink" in stair["edit_blocked_reasons"][0]
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


async def test_inspection_describes_parameters_without_inventing_any():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await parameters.inspect_element_parameters(c, [DOOR, STAIR], 19723)
    door, stair = result["elements"]
    rows = {p["name"]: p for p in door["gdl"]["parameters"]}
    assert set(rows) == {p["name"] for p in FIXTURE["parameters"]}
    style = rows["fx_leaf_style"]
    assert style["description"] == "Leaf style" and style["value_description"] == "Flush"
    assert style["options"] == [
        {"value": 1, "description": "Flush"},
        {"value": 2, "description": "Panelled"},
    ]
    assert style["group"] == "fx_leaf_title" and style["custom_value_allowed"] is False
    thickness = rows["fx_leaf_thickness"]
    assert thickness["unit"] == "m" and thickness["parent"] == "fx_leaf_style"
    assert thickness["limits"] == {"lower": [{"value": 0.03, "inclusive": True}]}
    assert rows["fx_opening_angle"]["unit"] == "rad"
    assert rows["fx_frame_widths"]["dimensions"] == [2, 1]
    assert rows["fx_frame_widths"]["item_descriptions"] == ["Left", "Right"]
    for name in ("fx_hidden_option", "fx_script_locked", "fx_settings"):
        assert not rows[name]["editable"] and rows[name]["edit_blocked_reason"]
    assert door["marker"]["parameters"][0]["name"] == "fx_marker_text"
    assert door["identity"]["ownerElementId"] == {"guid": WALL}
    assert door["native"]["writable_by"]["sillHeight"] == "modify_doors"
    assert stair["gdl"]["available"] is False and "limitation" in stair["native"]


async def test_name_filter_matches_name_or_description():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        result = await parameters.inspect_element_parameters(
            c, [DOOR], 19723, name_contains="HANDLE"
        )
    names = [p["name"] for p in result["elements"][0]["gdl"]["parameters"]]
    assert names == ["fx_handle_type", "fx_handle_height"]
    assert result["elements"][0]["gdl"]["count"] == len(FIXTURE["parameters"])


async def test_preview_lists_only_requested_differences_and_writes_nothing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await parameters.set_element_parameters(
            c, [change("fx_handle_type", "Knob"), change("fx_show_swing_2d", True)], 19723
        )
    item = preview["items"][0]
    assert [(x["name"], x["status"]) for x in item["changes"]] == [
        ("fx_handle_type", "ready"),
        ("fx_show_swing_2d", "unchanged"),
    ]
    assert item["gdl_payload"] == [{"name": "fx_handle_type", "value": "Knob"}]
    assert item["changes"][0]["before"] == "Lever" and item["changes"][0]["description"]
    assert not {"SetGDLParametersOfElements", "SetMarkerParametersOfElements"} & set(
        fake.tapir_calls
    )


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (change("fx_handle_type", "Crank"), "must be one of"),
        (change("fx_leaf_style", 3), "outside the library part"),
        (change("fx_leaf_thickness", 0.01), "outside the library part"),
        (change("fx_hidden_option", True), "Hidden"),
        (change("fx_script_locked", 0.2), "locked by the library part"),
        (change("fx_settings", "x"), "cannot be written"),
        (change("fx_frame_widths", [0.1]), "resizing is impossible"),
        (change("fx_frame_widths", 0.1), "requires a list"),
        (change("fx_leaf_style", 1.5), "requires an integer"),
        (change("fx_show_swing_2d", 1), "true/false"),
        (change("fx_missing", 1), "no such parameter"),
        (change("fx_marker_text", ["a"], "marker"), "single value"),
        ({"element_guid": WALL, "name": "A", "value": 1.0}, "Wall has no GDL"),
    ],
)
async def test_invalid_changes_are_refused_per_field(bad, message):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await parameters.set_element_parameters(c, [bad], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


async def test_all_problems_are_reported_together():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError) as error:
            await parameters.set_element_parameters(
                c, [change("fx_handle_type", "Crank"), change("fx_missing", 1)], 19723
            )
    assert "fx_handle_type" in str(error.value) and "fx_missing" in str(error.value)


@pytest.mark.parametrize("reason", ["locked", "hotlink"])
async def test_locked_and_hotlinked_elements_are_refused(reason):
    fake = model()
    if reason == "locked":
        fake.locked_elements.add(DOOR)
    else:
        fake.details[DOOR]["hotlinkId"] = {"guid": "00000000-0000-4000-8000-0000000000FF"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="(?i)locked|hotlink"):
            await parameters.set_element_parameters(c, [change("A", 1.0)], 19723)


async def test_gdl_and_marker_apply_in_two_undo_steps_and_keep_the_same_door():
    fake = model()
    changes = [
        change("fx_handle_type", "Knob"),
        change("fx_frame_widths", [0.06, 0.08]),
        change("fx_opening_angle", math.pi / 2),
        change("fx_marker_text", "P2", "marker"),
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, changes)
    item = result["items"][0]
    assert result["status"] == "verified", item.get("mismatches")
    assert result["undo_steps"] == 2
    assert [x["status"] for x in item["changes"]] == ["verified"] * 4
    assert item["identity_after"]["details"]["ownerElementId"] == {"guid": WALL}
    assert item["identity_after"]["classifications"][SYSTEM] == {"item_guid": ITEM}
    assert item["dependent_changes"] == []
    assert fake.elements[DOOR] == "Door" and DOOR in fake.details
    sent = [r for r in fake.tapir_requests if r["command"] == "SetGDLParametersOfElements"]
    assert len(sent) == 1  # every GDL change of the batch in one undoable command
    assert {p["name"] for p in sent[0]["parameters"]["elementsWithGDLParameters"][0][
        "gdlParameters"]} == {"fx_handle_type", "fx_frame_widths", "fx_opening_angle"}  # fmt: skip
    assert fake.marker_parameters[DOOR][0]["value"] == "P2"


async def test_parameter_script_dependencies_are_reported_not_hidden():
    def script(guid, rows):
        named = {r["name"]: r for r in rows}
        if named["fx_handle_type"]["value"] == "Pull bar":
            named["fx_handle_height"]["value"] = 0.9

    fake = model(gdl_script=script)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [change("fx_handle_type", "Pull bar")])
    item = result["items"][0]
    assert item["status"] == "verified"
    assert item["dependent_changes"] == [
        {"target": "gdl", "name": "fx_handle_height", "before": 1.05, "after": 0.9}
    ]


async def test_a_value_the_script_rejects_is_not_reported_as_success():
    def clamp(guid, rows):
        for row in rows:
            if row["name"] == "fx_handle_height" and row["value"] > 1.2:
                row["value"] = 1.2

    fake = model(gdl_script=clamp)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [change("fx_handle_height", 1.5)])
    item = result["items"][0]
    assert result["status"] == "needs_review" and item["status"] == "verification_failed"
    assert item["changes"][0]["status"] == "not_applied"
    assert item["changes"][0]["after"] == 1.2


async def test_moved_or_reclassified_door_fails_identity_check():
    def move(guid, rows):
        fake.details[DOOR]["details"]["centerOffset"] = 2.0
        fake.classifications.pop((DOOR, SYSTEM), None)

    fake = model(gdl_script=move)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [change("fx_handle_type", "Knob")])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert "details.centerOffset" in item["identity_changed"]
    assert f"classification.{SYSTEM}" in item["identity_changed"]


async def test_old_tapir_gets_angles_in_degrees_and_no_arrays_or_markers():
    fake = model(tapir_version="1.7.0")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [change("fx_opening_angle", math.pi / 2)])
        for bad, message in (
            (change("fx_frame_widths", [0.1, 0.2]), "1.7.2"),
            (change("fx_marker_text", "P2", "marker"), "1.7.1"),
        ):
            with pytest.raises(ValueError, match=message):
                await parameters.set_element_parameters(c, [bad], 19723)
        with pytest.raises(ValueError, match="1.7.3"):
            await parameters.set_element_parameters(
                c, [change("A", 1.0)], 19723, run_parameter_script=True
            )
    assert preview["items"][0]["gdl_payload"][0]["value"] == pytest.approx(90.0)
    assert result["status"] == "verified"


async def test_optional_parameter_script_run_is_a_separate_undo_step():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [change("A", 1.0)], run_parameter_script=True)
    assert fake.run_script_calls == [[DOOR]]
    assert result["undo_steps"] == 2 and result["status"] == "verified"


async def test_lost_response_is_unknown_marker_not_sent_and_token_consumed():
    fake = model(lose_gdl_response=True)
    changes = [change("A", 1.0), change("fx_marker_text", "P2", "marker")]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await parameters.set_element_parameters(c, changes, 19723)
        token = preview["confirmation_token"]
        result = await parameters.set_element_parameters(c, changes, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await parameters.set_element_parameters(c, changes, 19723, False, token)
    item = result["items"][0]
    assert item["status"] == "unknown" and "inspect" in result["warning"].lower()
    assert "SetMarkerParametersOfElements" not in fake.tapir_calls
    assert item["changes"][0]["after"] == 1.0  # observed, still reported unknown


async def test_native_refusal_of_one_element_does_not_hide_the_other():
    other = "D0000000-0000-4000-8000-000000000002"
    fake = model(gdl_errors={0: {"success": False, "error": {"code": -1, "message": "no"}}})
    fake.elements[other] = "Door"
    fake.details[other] = door_details()
    fake.gdl_parameters[other] = deepcopy(FIXTURE["parameters"])
    changes = [change("A", 1.0), {**change("A", 1.0), "element_guid": other}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, changes)
    first, second = result["items"]
    assert first["status"] == "failed" and second["status"] == "verified"
    assert result["status"] == "needs_review"


async def test_changed_model_invalidates_the_token():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await parameters.set_element_parameters(c, [change("A", 1.0)], 19723)
        fake.gdl_parameters[DOOR][7]["value"] = 0.5  # someone opened the door in 3D
        with pytest.raises(ValueError, match="changed since preview"):
            await parameters.set_element_parameters(
                c, [change("A", 1.0)], 19723, False, preview["confirmation_token"]
            )
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


async def test_apply_requires_explicit_port():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        preview = await parameters.set_element_parameters(c, [change("A", 1.0)], 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await parameters.set_element_parameters(
                c, [change("A", 1.0)], None, False, preview["confirmation_token"]
            )


async def test_failed_marker_step_still_reads_back_the_written_gdl():
    fake = model(marker_refused={DOOR})
    changes = [change("A", 1.0), change("fx_marker_text", "P2", "marker")]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, changes)
    item = result["items"][0]
    assert item["status"] == "failed" and result["undo_steps"] == 2
    assert item["changes"][0]["status"] == "verified"  # the GDL step really happened
    assert item["changes"][1]["status"] == "not_applied"
