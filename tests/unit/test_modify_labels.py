"""T20: source-derived tests, MockTransport only; never live Archicad."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import modify
from tests.unit.fake_archicad import fake_transport
from tests.unit.test_modify_elements import ELEMENT, OTHER, apply, model, sent

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


@pytest.mark.parametrize(
    "edits",
    [
        [],
        [{"guid": ELEMENT}],
        [{"guid": ELEMENT, "text": " "}],
        [{"guid": ELEMENT, "position": {"x": 2, "y": 3}}],
        [{"guid": ELEMENT, "floorIndex": 1}],
        [{"guid": ELEMENT, "height_mm": 0}],
        [{"guid": ELEMENT, "height_mm": float("nan")}],
        [{"guid": ELEMENT, "height_mm": True}],
        [{"guid": ELEMENT, "text": "A"}] * 51,
        [{"guid": ELEMENT, "text": "A"}] * 2,
    ],
)
async def test_refuses_invalid_or_unsupported_changes_before_network(edits):
    fake = model("Label")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await modify.modify_labels(c, edits)
    assert not fake.calls


async def test_text_and_size_preserve_owner_position_story_and_other_style():
    fake = model("Label")
    fake.details[ELEMENT]["details"]["ownerElementId"] = {"guid": OTHER}
    before = deepcopy(fake.details[ELEMENT])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "Label", [{"guid": ELEMENT, "text": "A\r\nB\rC", "height_mm": 4}])
    assert result["status"] == "verified"
    assert sent(fake, "Label") == [
        {"elementId": {"guid": ELEMENT}, "text": "A\nB\nC", "style": {"height": 4}}
    ]
    after = result["items"][0]["after"]
    assert after["floorIndex"] == before["floorIndex"]
    for key in ("ownerElementId", "begCoordinate", "midCoordinate", "endCoordinate"):
        assert after["details"][key] == before["details"][key]
    assert after["details"]["style"]["justification"] == before["details"]["style"]["justification"]


async def test_height_only_keeps_content():
    fake = model("Label")
    fake.details[ELEMENT]["details"]["text"] = "Original\nSecond line"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, "Label", [{"guid": ELEMENT, "height_mm": 3.5}])
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["details"]["text"] == "Original\nSecond line"


async def test_symbol_label_refused():
    fake = model("Label")
    fake.details[ELEMENT]["details"]["labelClass"] = "Symbol"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Symbol"):
            await modify.modify_labels(c, [{"guid": ELEMENT, "text": "A"}], 19723)
    assert "ModifyLabels" not in fake.tapir_calls


async def test_partial_native_error_is_per_label():
    fake = model(
        "Label", modify_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, "Label", [{"guid": ELEMENT, "text": "A"}, {"guid": OTHER, "text": "B"}]
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]


async def test_lost_response_does_not_retry_and_consumes_token():
    fake = model("Label", lose_modify_response=True)
    edits = [{"guid": ELEMENT, "text": "Changed"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_labels(c, edits, 19723)
        result = await modify.modify_labels(c, edits, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await modify.modify_labels(c, edits, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("ModifyLabels") == 1


async def test_apply_requires_explicit_port_and_unchanged_snapshot():
    fake = model("Label")
    edits = [{"guid": ELEMENT, "text": "Changed"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_labels(c, edits, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await modify.modify_labels(c, edits, None, False, preview["confirmation_token"])
        fake.details[ELEMENT]["details"]["text"] = "Externally changed"
        with pytest.raises(ValueError, match="changed"):
            await modify.modify_labels(c, edits, 19723, False, preview["confirmation_token"])
    assert "ModifyLabels" not in fake.tapir_calls
