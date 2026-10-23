"""create_solid_operations and trim_to_roof (Tapir 1.7.0), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import solids
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "A1000000-0000-4000-8000-000000000001"
WALL2 = "A1000000-0000-4000-8000-000000000002"
ROOF = "A1000000-0000-4000-8000-000000000003"
MORPH = "A1000000-0000-4000-8000-000000000004"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    elements = {WALL: "Wall", WALL2: "Wall", ROOF: "Roof", MORPH: "Morph"}
    return FakeArchicad(19723, elements=elements, **kwargs)


async def apply(tool, c, *args):
    preview = await tool(c, *args, port=19723)
    return preview, await tool(
        c, *args, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"]
    )


async def test_links_created_and_read_back():
    fake = model()
    links = [
        {"target_guid": WALL.lower(), "operator_guid": MORPH, "operation": "Intersection"},
        {"target_guid": WALL2, "operator_guid": ROOF, "skip_polygon_holes": True},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(solids.create_solid_operations, c, links)
    assert [(i["target_type"], i["operator_type"]) for i in preview["items"]] == [
        ("Wall", "Morph"),
        ("Wall", "Roof"),
    ]
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateSolidElementLinks")
    assert request["parameters"]["solidLinks"][1] == {
        "targetId": {"guid": WALL2},
        "operatorId": {"guid": ROOF},
        "operation": "Subtraction",
        "linkFlags": {"inheritOperatorAttributes": False, "skipPolygonHoles": True},
    }
    assert result["status"] == "verified"
    assert fake.solid_links[(WALL, MORPH)]["operation"] == "Intersection"


async def test_existing_link_and_locked_element_are_refused():
    fake = model()
    fake.solid_links[(WALL, ROOF)] = {
        "operation": "Subtraction",
        "linkFlags": {"inheritOperatorAttributes": False, "skipPolygonHoles": False},
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already acts"):
            await solids.create_solid_operations(
                c, [{"target_guid": WALL, "operator_guid": ROOF}], 19723
            )
        fake.locked_elements.add(MORPH)
        with pytest.raises(ValueError, match="non-editable"):
            await solids.create_solid_operations(
                c, [{"target_guid": WALL2, "operator_guid": MORPH}], 19723
            )
    assert "CreateSolidElementLinks" not in fake.tapir_calls


async def test_flags_lost_fail_verification():
    fake = model(solid_link_flags_ignored=True)
    link = {"target_guid": WALL, "operator_guid": ROOF, "inherit_operator_attributes": True}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(solids.create_solid_operations, c, [link])
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["linkFlags"]


def test_link_input_is_checked():
    with pytest.raises(ValidationError, match="itself"):
        solids.SolidLink.model_validate({"target_guid": WALL, "operator_guid": WALL.lower()})
    with pytest.raises(ValidationError):
        solids.SolidLink.model_validate(
            {"target_guid": WALL, "operator_guid": ROOF, "operation": "Cut"}
        )


async def test_trim_to_roof_and_read_back():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(solids.trim_to_roof, c, [WALL, WALL2], ROOF, "KeepOutside")
    assert preview["roof_type"] == "Roof" and preview["keep"] == "KeepOutside"
    request = next(r for r in fake.tapir_requests if r["command"] == "TrimElements")
    assert request["parameters"] == {
        "elements": [{"elementId": {"guid": WALL}}, {"elementId": {"guid": WALL2}}],
        "trimmingElement": {"guid": ROOF},
        "trimType": "KeepOutside",
    }
    assert result["status"] == "verified"
    assert fake.element_trims == {(WALL, ROOF): "KeepOutside", (WALL2, ROOF): "KeepOutside"}


async def test_trim_preview_refusals():
    fake = model()
    fake.element_trims[(WALL, ROOF)] = "KeepInside"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="not a roof or shell"):
            await solids.trim_to_roof(c, [WALL], MORPH, port=19723)
        with pytest.raises(ValueError, match="already trimmed"):
            await solids.trim_to_roof(c, [WALL, WALL2], ROOF, port=19723)
    assert "TrimElements" not in fake.tapir_calls


async def test_refused_trim_is_failed():
    fake = model(trim_refused=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(solids.trim_to_roof, c, [WALL], ROOF)
    assert result["items"][0]["status"] == "failed"


def test_trim_input_is_checked():
    with pytest.raises(ValidationError, match="itself"):
        solids.Trim.model_validate({"element_guids": [ROOF], "roof_guid": ROOF})
    with pytest.raises(ValidationError, match="twice"):
        solids.Trim.model_validate({"element_guids": [WALL, WALL.lower()], "roof_guid": ROOF})
    with pytest.raises(ValidationError):
        solids.Trim.model_validate({"element_guids": [WALL], "roof_guid": ROOF, "keep": "No"})
