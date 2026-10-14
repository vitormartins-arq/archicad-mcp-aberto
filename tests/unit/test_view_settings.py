"""View settings safety and read-back; source-derived fake only."""

import json
import math
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import views, write
from tests.unit.fake_archicad import VIEW_SETTINGS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
FIRST, SECOND = VIEW_SETTINGS_FIXTURE["views"]
MISSING = "11111111-1111-1111-1111-111111111111"
COMBINATION = "1ª ETAPA | CADASTRO"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, changes):
    preview = await views.set_view_settings(c, changes, 19723)
    return await views.set_view_settings(c, changes, 19723, False, preview["confirmation_token"])


async def test_read_is_per_view_and_keeps_middle_error():
    fake = FakeArchicad(19723)
    before = deepcopy(fake.view_settings)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await views.get_view_settings(c, [FIRST, MISSING, SECOND], 19723)
    assert [r["guid"] for r in result["views"]] == [FIRST, MISSING, SECOND]
    assert result["views"][0]["settings"]["drawingScale"] == 100
    assert result["views"][1]["error"] == VIEW_SETTINGS_FIXTURE["not_a_view"]["error"]
    assert result["views"][2]["settings"]["drawingScale"] == 50
    assert fake.view_settings == before
    assert fake.tapir_requests == [
        {
            "command": "GetViewSettings",
            "parameters": {
                "navigatorItemIds": [
                    {"navigatorItemId": {"guid": g}} for g in (FIRST, MISSING, SECOND)
                ]
            },
        }
    ]


@pytest.mark.parametrize("guids", [[], [FIRST] * 101, [FIRST, FIRST], ["bad"]])
async def test_invalid_read_input_before_network(guids):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await views.get_view_settings(c, guids)
    assert not fake.calls


async def test_scale_preview_apply_keeps_other_settings_and_honest_undo_note():
    fake = FakeArchicad(19723)
    fake.view_settings[FIRST].update(
        saveZoom=True, zoom={"xMin": 0, "yMin": 0, "xMax": 30, "yMax": 20}, rotation=0.5
    )
    before = deepcopy(fake.view_settings[FIRST])
    changes = [{"guid": FIRST, "drawing_scale": 200}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await views.set_view_settings(c, changes, 19723)
        assert "SetViewSettings" not in fake.tapir_calls
        assert preview["items"][0]["before"] == before
        assert "Undo" in preview["revert_note"] and "stored-scale flag" in preview["scale_note"]
        result = await views.set_view_settings(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await views.set_view_settings(c, changes, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["view_settings_receipt_id"] and item["after"] == {**before, "drawingScale": 200}
    assert "Do not rely on Archicad Undo" in result["note"]
    assert "Use Archicad Undo to revert this batch" not in result["note"]
    assert (
        json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))["note"]
        == result["note"]
    )
    sent = next(r["parameters"] for r in fake.tapir_requests if r["command"] == "SetViewSettings")
    assert sent == {
        "navigatorItemIdsWithViewSettings": [
            {"navigatorItemId": {"guid": FIRST}, "viewSettings": {"drawingScale": 200}}
        ]
    }
    assert "GetAttributesByType" not in fake.tapir_calls
    assert not any("Save" in c or "Publish" in c or "Delete" in c for c in fake.tapir_calls)


async def test_existing_combination_resolved_once_and_states_preserved():
    fake = FakeArchicad(19723)
    before = deepcopy(fake.layer_combinations)
    changes = [
        {"guid": FIRST, "layer_combination": COMBINATION.lower()},
        {"guid": SECOND, "layer_combination": COMBINATION},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await views.set_view_settings(c, changes, 19723)
        assert fake.tapir_calls.count("GetAttributesByType") == 1
        result = await views.set_view_settings(
            c, changes, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified" and len(result["items"]) == 2
    assert all(i["after"]["layerCombination"] == COMBINATION for i in result["items"])
    assert fake.layer_combinations == before
    assert fake.tapir_calls.count("GetAttributesByType") == 2  # preview + apply preflight


async def test_combination_can_be_selected_by_guid():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        catalog = await views.drafting._attributes(c, 19723, "LayerCombination")
        row = next(r for r in catalog if r["name"] == COMBINATION)
        result = await apply(c, [{"guid": FIRST, "layer_combination": row["attributeId"]["guid"]}])
    assert result["status"] == "verified"
    assert result["items"][0]["parameters"]["viewSettings"] == {"layerCombination": COMBINATION}


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"guid": FIRST}],
        [{"guid": FIRST, "drawing_scale": 0}],
        [{"guid": FIRST, "drawing_scale": True}],
        [{"guid": FIRST, "drawing_scale": 1.5}],
        [{"guid": FIRST, "drawing_scale": 1000001}],
        [{"guid": FIRST, "rotation": 1}],
        [{"guid": FIRST, "drawing_scale": 100}] * 2,
        [{"guid": FIRST, "drawing_scale": 100}] * 101,
    ],
)
async def test_invalid_or_unsupported_write_input_before_network(changes):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await views.set_view_settings(c, changes)
    assert not fake.calls


async def test_missing_combination_or_view_refused_before_apply():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await views.set_view_settings(
                c, [{"guid": FIRST, "layer_combination": "No such combination"}], 19723
            )
        with pytest.raises(ValueError, match="PublicViewMap"):
            await views.set_view_settings(c, [{"guid": MISSING, "drawing_scale": 50}], 19723)
        folder = fake.navigator_trees["PublicViewMap"]["navigatorItemId"]["guid"]
        with pytest.raises(ValueError, match="not a readable view"):
            await views.set_view_settings(c, [{"guid": folder, "drawing_scale": 50}], 19723)
    assert "SetViewSettings" not in fake.tapir_calls


async def test_duplicate_native_combination_name_refused_even_with_guid():
    fake = FakeArchicad(19723)
    fake.layer_combinations[1]["name"] = COMBINATION
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        catalog = await views.drafting._attributes(c, 19723, "LayerCombination")
        with pytest.raises(ValueError, match="duplicate names"):
            await views.set_view_settings(
                c, [{"guid": FIRST, "layer_combination": catalog[0]["attributeId"]["guid"]}], 19723
            )
    assert "SetViewSettings" not in fake.tapir_calls


async def test_partial_native_error_preserves_per_view_result():
    fake = FakeArchicad(19723, view_settings_errors={1: VIEW_SETTINGS_FIXTURE["failed"]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, [{"guid": FIRST, "drawing_scale": 200}, {"guid": SECOND, "drawing_scale": 200}]
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert fake.view_settings[SECOND]["drawingScale"] == 50


@pytest.mark.parametrize("reason", ["ignored", "pen-set", "combination-layer-state"])
async def test_requested_and_unrequested_changes_checked(reason):
    fake = FakeArchicad(
        19723,
        view_settings_ignored=reason == "ignored",
        view_settings_reset_pen_set=reason == "pen-set",
        view_settings_change_layers=reason == "combination-layer-state",
    )
    changes = [{"guid": FIRST, "drawing_scale": 200, "layer_combination": COMBINATION}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, changes)
    assert result["items"][0]["status"] == "verification_failed"
    field = {
        "ignored": "settings.drawingScale",
        "pen-set": "settings.penSetName",
        "combination-layer-state": "layer_combination_states",
    }[reason]
    assert field in result["items"][0]["mismatches"]


@pytest.mark.parametrize("change", ["settings", "combination", "name", "target-input"])
async def test_snapshot_changes_need_new_preview(change):
    fake = FakeArchicad(19723)
    changes = [{"guid": FIRST, "drawing_scale": 200, "layer_combination": COMBINATION}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await views.set_view_settings(c, changes, 19723)
        if change == "settings":
            fake.view_settings[FIRST]["drawingScale"] = 25
        elif change == "combination":
            fake.layer_combinations[2]["layers"][1]["isHidden"] = False
        elif change == "target-input":
            changes[0]["drawing_scale"] = 300
        else:
            fake.navigator_trees["PublicViewMap"]["children"][0]["navigatorItem"]["children"][0][
                "navigatorItem"
            ]["name"] = "New name"
        with pytest.raises(ValueError, match="changed"):
            await views.set_view_settings(c, changes, 19723, False, preview["confirmation_token"])
    assert "SetViewSettings" not in fake.tapir_calls


async def test_lost_response_and_port_requirements():
    fake = FakeArchicad(19723, lose_view_settings_response=True)
    changes = [{"guid": FIRST, "drawing_scale": 200}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await views.set_view_settings(c, changes, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await views.set_view_settings(c, changes, None, False, preview["confirmation_token"])
        result = await views.set_view_settings(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await views.set_view_settings(c, changes, 19723, False, preview["confirmation_token"])
    assert (
        result["items"][0]["status"] == "unknown"
        and fake.view_settings[FIRST]["drawingScale"] == 200
    )
    assert fake.tapir_calls.count("SetViewSettings") == 1


async def test_prepared_receipt_failure_prevents_dispatch(monkeypatch):
    fake = FakeArchicad(19723)
    changes = [{"guid": FIRST, "drawing_scale": 200}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await views.set_view_settings(c, changes, 19723)

        def denied(*args):
            raise OSError("No receipt")

        monkeypatch.setattr(write, "_journal", denied)
        with pytest.raises(OSError, match="No receipt"):
            await views.set_view_settings(c, changes, 19723, False, preview["confirmation_token"])
    assert "SetViewSettings" not in fake.tapir_calls


def test_rotation_comparison_accepts_equivalent_native_turn():
    assert not views._mismatches({"rotation": 0}, {"rotation": math.tau})
    assert views._mismatches({"rotation": 0}, {"rotation": math.pi}) == ["settings.rotation"]


async def test_shared_timeout_for_write_and_verification(monkeypatch):
    fake = FakeArchicad(19723)
    seen = []

    class TimedClient(ArchicadClient):
        async def tapir(self, port, name, parameters=None, *, timeout=None):
            if timeout is not None:
                seen.append((name, timeout))
            return await super().tapir(port, name, parameters, timeout=timeout)

    monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", "45")
    async with TimedClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"guid": FIRST, "drawing_scale": 200}])
    assert (
        result["status"] == "verified"
        and ("SetViewSettings", 45) in seen
        and ("GetViewSettings", 45) in seen
    )


async def test_bad_response_cardinality_is_not_zipped_silently():
    fake = FakeArchicad(19723)

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        if (
            body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
            == "GetViewSettings"
        ):
            response["result"]["addOnCommandResponse"] = {"viewSettings": []}
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ValueError, match="cardinality"):
            await views.get_view_settings(c, [FIRST], 19723)


async def test_one_hundred_view_changes_in_one_native_batch():
    from uuid import UUID

    fake = FakeArchicad(19723)
    guids = [str(UUID(int=i)).upper() for i in range(1, 101)]
    template = deepcopy(fake.view_settings[FIRST])
    fake.view_settings = {g: deepcopy(template) for g in guids}
    fake.navigator_trees["PublicViewMap"]["children"] = [
        {
            "navigatorItem": {
                "navigatorItemId": {"guid": g},
                "name": f"View {i}",
                "type": "StoryItem",
            }
        }
        for i, g in enumerate(guids)
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        readback = await views.get_view_settings(c, guids, 19723)
        result = await apply(c, [{"guid": g, "drawing_scale": 250} for g in guids])
    assert readback["total"] == 100 and result["counts"]["verified"] == 100
    assert fake.tapir_calls.count("SetViewSettings") == 1


async def test_lost_verification_keeps_known_write_unverified():
    fake = FakeArchicad(19723)
    written = False

    def handler(request):
        nonlocal written
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "GetViewSettings" and written:
            raise httpx.ReadTimeout("Lost readback", request=request)
        response = fake.handle(body)
        if cmd == "SetViewSettings":
            written = True
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [{"guid": FIRST, "drawing_scale": 200}])
    assert result["items"][0]["status"] == "unverified"
    assert result["verification_error"] and result["status"] == "needs_review"
