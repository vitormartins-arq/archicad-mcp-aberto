"""modify_morphs (Tapir 1.7.0 ModifyMorphs), against the simulated Archicad."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import modify
from tests.unit.fake_archicad import FakeArchicad, fake_transport, surface_guid
from tests.unit.test_modify_elements import ROWS

pytestmark = pytest.mark.anyio
GUID = "7A7A7A7A-0000-4000-8000-000000000001"
MATERIAL = "7A7A7A7A-0000-4000-8000-0000000000B1"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(row=None):
    material = {"attributeId": {"guid": MATERIAL}, "index": 7, "name": "Concreto Estrutural"}
    fake = FakeArchicad(
        19723,
        stories=[{"index": 0, "name": "Térreo", "level": 0.0}],
        elements={GUID: "Morph"},
        building_materials={MATERIAL: material},
    )
    fake.details[GUID] = deepcopy(row or ROWS["Morph"])
    return fake


async def apply(c, edits):
    preview = await modify.modify_morphs(c, edits, 19723)
    result = await modify.modify_morphs(c, edits, 19723, False, preview["confirmation_token"])
    return preview, result


def sent(fake):
    return next(r for r in fake.tapir_requests if r["command"] == "ModifyMorphs")["parameters"]


async def test_resize_box_keeps_corner_and_is_verified():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"guid": GUID, "size": {"x": 4, "y": 2, "z": 1.5}}])
    body = sent(fake)["morphsWithDetails"][0]["body"]
    assert body["bodyType"] == "Solid" and len(body["polygons"]) == 6
    assert {(v["x"], v["y"], v["z"]) for v in body["vertices"]} == {
        (x, y, z) for x in (0, 4) for y in (0, 2) for z in (0, 1.5)
    }
    item = result["items"][0]
    assert item["status"] == "verified"
    assert item["size_after"] == {"x": 4.0, "y": 2.0, "z": 1.5}
    assert fake.details[GUID]["details"]["origin"] == {"x": 1.0, "y": 2.0, "z": 0.0}


async def test_material_surface_and_shadows_by_name():
    fake = model()
    edit = {
        "guid": GUID,
        "buildingMaterial": "concreto estrutural",
        "surface": "Pintura Branca",
        "castShadow": False,
        "receiveShadow": False,
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [edit])
    payload = sent(fake)["morphsWithDetails"][0]
    assert payload == {
        "elementId": {"guid": GUID},
        "buildingMaterialId": {"guid": MATERIAL},
        "surfaceId": {"guid": surface_guid(1)},
        "castShadow": False,
        "receiveShadow": False,
    }
    assert result["items"][0]["status"] == "verified"


async def test_non_box_morph_is_not_resized():
    row = deepcopy(ROWS["Morph"])
    row["details"]["body"]["vertices"][6] = {"x": 2.5, "y": 1.0, "z": 3.0}
    fake = model(row)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="only a box morph"):
            await modify.modify_morphs(c, [{"guid": GUID, "size": {"x": 1, "y": 1, "z": 1}}], 19723)


async def test_unknown_material_refused_in_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="'Madeira' does not exist"):
            await modify.modify_morphs(c, [{"guid": GUID, "buildingMaterial": "Madeira"}], 19723)


async def test_ignored_change_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await modify.modify_morphs(c, [{"guid": GUID, "castShadow": False}], 19723)
        fake.modify_ignored = True
        result = await modify.modify_morphs(
            c, [{"guid": GUID, "castShadow": False}], 19723, False, preview["confirmation_token"]
        )
    item = result["items"][0]
    assert item["status"] == "verification_failed" and "details.castShadow" in item["mismatches"]


async def test_other_element_type_refused():
    fake = model()
    fake.elements[GUID] = "Wall"
    fake.details[GUID]["type"] = "Wall"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="not a Morph"):
            await modify.modify_morphs(c, [{"guid": GUID, "castShadow": True}], 19723)


@pytest.mark.parametrize(
    "bad",
    [
        {"guid": GUID},
        {"guid": GUID, "size": {"x": 1, "y": 1}},
        {"guid": GUID, "size": {"x": 0, "y": 1, "z": 1}},
        {"guid": GUID, "surface": ""},
        {"guid": "nope", "castShadow": True},
    ],
)
def test_invalid_input_refused(bad):
    with pytest.raises(ValidationError):
        modify.MorphModify.model_validate(bad)


def test_box_size_reads_only_boxes():
    assert modify._box_size(ROWS["Morph"]["details"]["body"]) == {"x": 2.0, "y": 1.0, "z": 3.0}
    surface = {**ROWS["Morph"]["details"]["body"], "bodyType": "Surface"}
    assert modify._box_size(surface) is None
    assert modify._box_size({"bodyType": "Solid", "vertices": [], "polygons": []}) is None
