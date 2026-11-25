"""Companion native LevelDimension contract; synthetic data, no live Archicad."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import level_dimensions as tool
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
SLAB = "11111111-1111-4111-8111-111111111111"
MISSING = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model():
    fake = FakeArchicad(19723, elements={SLAB: "Slab"})
    fake.native_level_slabs[SLAB] = {"top": 3.25, "floorIndex": 1, "bounds": [0, 0, 8, 6]}
    return fake


def dimension(**kwargs):
    return {"slab_guid": SLAB, "position": {"x": 2, "y": 3}, **kwargs}


async def apply(c, dims):
    preview = await tool.create_level_dimensions(c, dims, 19723)
    return await tool.create_level_dimensions(c, dims, 19723, False, preview["confirmation_token"])


async def test_preview_then_apply_native_owner_value_and_independent_getter():
    fake = model()
    original = deepcopy(fake.native_level_slabs)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_level_dimensions(c, [dimension()], 19723)
        assert preview["dry_run"]
        assert not fake.native_level_dimensions
        assert preview["items"][0]["before"]["expectedLevel"] == 3.25
        result = await tool.create_level_dimensions(
            c, [dimension()], 19723, False, preview["confirmation_token"]
        )
        assert result["counts"]["verified"] == 1
        row = result["items"][0]["after"]
        assert row["type"] == "LevelDimension"
        assert row["parentElementId"]["guid"] == SLAB
        assert row["staticLevel"] is False
        assert row["level"] == 3.25
        assert row["floorIndex"] == 1
        assert row["position"] == {"x": 2, "y": 3}
        assert row["note1"]["contentType"] == 0
        read = await tool.get_level_dimensions(c, [row["elementId"]["guid"], MISSING], 19723)
        assert "error" in read["elements"][1]
        with pytest.raises(ValueError, match="consumed"):
            await tool.create_level_dimensions(
                c, [dimension()], 19723, False, preview["confirmation_token"]
            )
    assert fake.native_level_slabs == original
    assert "GetLevelDimensions" in fake.own_addon_calls
    assert "CreateLabels" not in fake.tapir_calls
    assert all(t == "LevelDimension" for g, t in fake.elements.items() if g != SLAB)
    assert result["receipt_path"]


@pytest.mark.parametrize(
    "override",
    [
        {"level": 3.0},
        {"staticLevel": True},
        {"parentElementId": {"guid": MISSING}},
        {"parentTypeId": 1},
        {"position": {"x": 3, "y": 3}},
        {"type": "Label"},
        {"note1": {"contentType": 1}},
        {"floorIndex": 0},
        {"origin": 1},
    ],
)
async def test_native_readback_mismatch_is_never_verified(override):
    fake = model()
    fake.native_level_override = override
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [dimension()])
    assert result["counts"]["verification_failed"] == 1


async def test_partial_native_creation_failure_preserves_other_receipts():
    fake = model()
    fake.create_errors[1] = {"error": {"code": -1, "message": "Native refused"}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [dimension(), dimension(position={"x": 3, "y": 4})])
    assert result["counts"]["verified"] == 1
    assert result["counts"]["failed"] == 1
    assert len({i["level_dimension_receipt_id"] for i in result["items"]}) == 2


async def test_invalid_parent_does_not_drop_good_item():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [dimension(slab_guid=MISSING), dimension()])
    assert result["counts"]["failed"] == 1
    assert result["counts"]["verified"] == 1


async def test_changed_slab_top_invalidates_token_before_dispatch():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_level_dimensions(c, [dimension()], 19723)
        fake.native_level_slabs[SLAB]["top"] += 0.1
        with pytest.raises(ValueError, match="changed"):
            await tool.create_level_dimensions(
                c, [dimension()], 19723, False, preview["confirmation_token"]
            )
    assert "CreateLevelDimensions" not in fake.own_addon_calls


async def test_apply_requires_explicit_port_and_preview():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="explicit port"):
            await tool.create_level_dimensions(c, [dimension()], dry_run=False)
        with pytest.raises(ValueError, match="Preview"):
            await tool.create_level_dimensions(c, [dimension()], 19723, False, "invalid")


@pytest.mark.parametrize(
    "dimensions",
    [
        [],
        [dimension()] * 21,
        [dimension(position={"x": float("nan"), "y": 0})],
        [dimension(slab_guid="invalid")],
    ],
)
async def test_input_validation(dimensions):
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError):
            await tool.create_level_dimensions(c, dimensions, 19723)


async def test_missing_companion_has_no_label_fallback():
    fake = model()
    fake.own_addon_loaded = False
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(AddOnError):
            await tool.create_level_dimensions(c, [dimension()], 19723)
    assert not fake.native_level_dimensions
    assert "CreateLabels" not in fake.tapir_calls


async def test_favorite_layer_and_numeric_readback_failure():
    fake = model()
    fake.native_level_favorites["Neutral level"] = {"pen": 3, "noteSize": 1.8}
    fake.own_addon_errors.add("GetLevelDimensions")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [dimension(favorite="Neutral level", layer_index=4)])
    assert result["counts"]["unverified"] == 1
    assert "verification_error" in result
    row = next(iter(fake.native_level_dimensions.values()))
    assert row["settings"]["layerIndex"] == 4
    assert row["settings"]["noteSize"] == 1.8


@pytest.mark.parametrize(
    "changes",
    [
        {"bounds": [4, 4, 8, 8]},
        {"holes": [[1, 2, 3, 4]]},
        {"referencePlane": "Bottom"},
        {"curved": True},
    ],
)
async def test_unsupported_or_outside_point_never_creates(changes):
    fake = model()
    fake.native_level_slabs[SLAB].update(changes)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [dimension()])
    assert result["counts"]["failed"] == 1
    assert not fake.native_level_dimensions


async def test_unknown_write_is_not_retried_and_token_is_consumed():
    fake = model()
    fake.native_level_lose_response = True
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_level_dimensions(c, [dimension()], 19723)
        result = await tool.create_level_dimensions(
            c, [dimension()], 19723, False, preview["confirmation_token"]
        )
        assert result["counts"]["unknown"] == 1
        with pytest.raises(ValueError, match="consumed"):
            await tool.create_level_dimensions(
                c, [dimension()], 19723, False, preview["confirmation_token"]
            )
    assert len(fake.native_level_dimensions) == 1
    assert fake.own_addon_calls.count("CreateLevelDimensions") == 1
