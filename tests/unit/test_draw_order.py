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


async def test_object_order_only_preserves_xyz_gdl_classifications_and_id():
    fake = model()
    fake.elements[A] = "Object"
    fake.details[A] = {
        "type": "Object",
        "id": "Neutral point",
        "floorIndex": 0,
        "layerIndex": 1,
        "drawIndex": 8,
        "details": {
            "x": 1.0,
            "y": 2.0,
            "z": 0.42,
            "angle": 1.2,
            "libPart": {"name": "Neutral parametric point"},
            "dimensions": {"x": 0.12, "y": 0.08, "z": 0.42},
        },
    }
    before = deepcopy(fake.details[A])
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await draw_order.set_draw_order(client, [{"guid": A, "draw_index": 14}], 19723)
        invariants = deepcopy(preview["items"][0]["object_invariants"])
        assert preview["items"][0]["parameters"] == {
            "elementId": {"guid": A},
            "details": {"drawIndex": 14},
        }
        result = await draw_order.set_draw_order(
            client, [{"guid": A, "draw_index": 14}], 19723, False, preview["confirmation_token"]
        )
    assert result["counts"]["verified"] == 1
    assert fake.details[A] == {**before, "drawIndex": 14}
    assert result["items"][0]["object_invariants_after"] == invariants
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


async def test_object_regenerated_gdl_cannot_be_reported_verified():
    fake = model()
    fake.elements[A] = "Object"
    fake.details[A]["type"] = "Object"
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        original = client.tapir

        async def side_effect(port, name, parameters=None, **kwargs):
            result = await original(port, name, parameters, **kwargs)
            if name == "SetDetailsOfElements":
                fake.gdl_parameters[A][0]["value"] = "unexpected-GDL-change"
            return result

        client.tapir = side_effect
        result = await apply(client, [{"guid": A, "draw_index": 14}])
    assert result["counts"]["verification_failed"] == 1
    assert "object_invariants.GDL_or_classifications" in result["items"][0]["mismatches"]


async def test_object_classification_side_effect_cannot_be_reported_verified():
    fake = model()
    fake.elements[A] = "Object"
    fake.details[A]["type"] = "Object"
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await draw_order.set_draw_order(client, [{"guid": A, "draw_index": 14}], 19723)
        system = next(iter(preview["items"][0]["object_invariants"]["classifications"]))
        original = client.tapir

        async def side_effect(port, name, parameters=None, **kwargs):
            result = await original(port, name, parameters, **kwargs)
            if name == "SetDetailsOfElements":
                fake.classifications[A, system] = B
            return result

        client.tapir = side_effect
        result = await draw_order.set_draw_order(
            client, [{"guid": A, "draw_index": 14}], 19723, False, preview["confirmation_token"]
        )
    assert result["counts"]["verification_failed"] == 1


async def test_object_gdl_readback_failure_remains_unverified():
    fake = model()
    fake.elements[A] = "Object"
    fake.details[A]["type"] = "Object"
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        original = client.tapir
        applied = False

        async def missing_gdl(port, name, parameters=None, **kwargs):
            nonlocal applied
            result = await original(port, name, parameters, **kwargs)
            if name == "SetDetailsOfElements":
                applied = True
            if applied and name == "GetGDLParametersOfElements":
                return {
                    "gdlParametersOfElements": [{"error": {"code": -1, "message": "Unreadable"}}]
                }
            return result

        client.tapir = missing_gdl
        result = await apply(client, [{"guid": A, "draw_index": 14}])
    assert result["counts"]["unverified"] == 1
    assert "verification_error" in result
