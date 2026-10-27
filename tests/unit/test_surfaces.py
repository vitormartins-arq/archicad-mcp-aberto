"""create_surfaces (Tapir 1.7.0 CreateSurfaces), against the simulated Archicad."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import surfaces
from tests.unit.fake_archicad import SURFACE_DEFAULT, FakeArchicad, fake_transport, surface_guid

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    fake = FakeArchicad(19723, **kwargs)
    textured = deepcopy(SURFACE_DEFAULT)
    textured["texture"]["name"] = "Concreto 01"
    fake.surface_details[surface_guid(2)] = textured
    return fake


async def apply(c, items):
    preview = await surfaces.create_surfaces(c, items, 19723)
    return preview, await surfaces.create_surfaces(
        c, items, 19723, False, preview["confirmation_token"]
    )


async def test_copy_of_a_surface_with_new_colour():
    fake = model()
    color = {"red": 0.2, "green": 0.4, "blue": 0.6}
    items = [
        {"name": "Pintura Azul", "based_on": "pintura branca", "color": color},
        {"name": "Concreto liso", "based_on": "Concreto Aparente", "keep_texture": False,
         "transparency": 20, "material_type": "Plastic"},
        {"name": "Concreto 2", "based_on": "Concreto Aparente"},
    ]  # fmt: skip
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, items)
    blue, smooth, copy = (i["parameters"] for i in preview["items"])
    assert blue["surfaceColor"] == color and blue["shine"] == 1600
    assert "texture" not in blue  # the base has no texture
    assert "texture" not in smooth and smooth["transparency"] == 20
    assert copy["texture"]["name"] == "Concreto 01"
    assert result["status"] == "verified"
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateSurfaces")
    assert request["parameters"]["overwriteExisting"] is False


async def test_ignored_type_is_caught():
    fake = model(surface_type_ignored=True)
    items = [{"name": "Vidro", "based_on": "Pintura Branca", "material_type": "Glass"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, items)
    assert result["items"][0]["mismatches"] == ["materialType"]


async def test_preview_refusals():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="already exists"):
            await surfaces.create_surfaces(
                c, [{"name": "CONCRETO APARENTE", "based_on": "Pintura Branca"}], 19723
            )
        with pytest.raises(ValueError, match="does not exist"):
            await surfaces.create_surfaces(c, [{"name": "X", "based_on": "Madeira"}], 19723)
        with pytest.raises(ValueError, match="twice"):
            await surfaces.create_surfaces(
                c,
                [
                    {"name": "X", "based_on": "Pintura Branca"},
                    {"name": "x", "based_on": "Pintura Branca"},
                ],
                19723,
            )
    with pytest.raises(ValidationError):
        surfaces.SurfaceCreate.model_validate({"name": "X", "based_on": "A", "transparency": 120})
