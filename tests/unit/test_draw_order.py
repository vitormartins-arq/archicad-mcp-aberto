"""Tapir 1.7.0/02691b5d documented payloads, synthetic data, not live captures."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import draw_order
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements={A: "Label", B: "LevelDimension"},
        details={
            A: {
                "type": "Label",
                "floorIndex": 0,
                "layerIndex": 1,
                "drawIndex": 10,
                "details": {
                    "begCoordinate": {"x": 1.0, "y": 2.0},
                    "endCoordinate": {"x": 3.0, "y": 4.0},
                    "ownerElementId": {"guid": B},
                },
            },
            B: {
                "type": "LevelDimension",
                "floorIndex": 0,
                "layerIndex": 1,
                "drawIndex": 10,
                "details": {"position": {"x": 1.0, "y": 2.0}, "level": 0.42},
            },
        },
        **kwargs,
    )


async def apply(client, changes):
    preview = await draw_order.set_draw_order(client, changes, 19723)
    return await draw_order.set_draw_order(
        client, changes, 19723, False, preview["confirmation_token"]
    )


async def test_preview_does_not_mutate_and_payload_only_contains_draw_index():
    fake = model()
    before = deepcopy(fake.details)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        plan = await draw_order.set_draw_order(client, [{"guid": A, "draw_index": 14}], 19723)
    assert fake.details == before
    assert plan["items"][0]["parameters"] == {
        "elementId": {"guid": A},
        "details": {"drawIndex": 14},
    }


async def test_display_order_changes_without_moving_label_or_physical_level_origin():
    fake = model()
    before = deepcopy(fake.details)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, [{"guid": A, "draw_index": 14}, {"guid": B, "draw_index": 9}])
    assert result["status"] == "verified"
    for guid in (A, B):
        assert fake.details[guid]["details"] == before[guid]["details"]
    assert fake.details[A]["drawIndex"] == 14 and fake.details[B]["drawIndex"] == 9


async def test_native_failure_is_per_item_and_ignored_change_fails_verification():
    fake = model(
        layer_move_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, [{"guid": A, "draw_index": 14}, {"guid": B, "draw_index": 9}])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    fake = model(layer_move_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, [{"guid": A, "draw_index": 14}])
    assert result["items"][0]["status"] == "verification_failed"


async def test_embedded_model_elements_are_refused_instead_of_changing_their_host():
    fake = model()
    fake.elements[A] = "Window"
    fake.details[A]["type"] = "Window"
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError, match="annotation"):
            await draw_order.set_draw_order(client, [{"guid": A, "draw_index": 14}], 19723)


@pytest.mark.parametrize("value", [0, 15, True, 3.5])
async def test_invalid_order_refused(value):
    with pytest.raises(ValueError):
        await draw_order.set_draw_order(None, [{"guid": A, "draw_index": value}], 19723)


async def test_token_is_single_use_and_apply_requires_explicit_port():
    fake = model()
    changes = [{"guid": A, "draw_index": 14}]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await draw_order.set_draw_order(client, changes, 19723)
        with pytest.raises(ValueError, match="port"):
            await draw_order.set_draw_order(
                client, changes, None, False, preview["confirmation_token"]
            )
        await draw_order.set_draw_order(
            client, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError):
            await draw_order.set_draw_order(
                client, changes, 19723, False, preview["confirmation_token"]
            )
