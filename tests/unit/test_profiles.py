import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import profiles
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def test_create_profile_from_existing_geometry():
    fake = FakeArchicad(19723)
    data = [{"name": "LAB 20x40", "source_profile": "rectangular 20x40", "walls": False}]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await profiles.create_profiles(client, data, 19723)
        result = await profiles.create_profiles(
            client, data, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["name"] == "LAB 20x40"
    assert result["items"][0]["after"]["wallType"] is False
    request = next(row for row in fake.tapir_requests if row["command"] == "CreateProfiles")
    assert request["parameters"]["overwriteExisting"] is False


async def test_create_profile_from_polygon_skins_and_hole():
    material_guid = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    fake = FakeArchicad(
        19723,
        building_materials={
            material_guid: {
                "attributeId": {"guid": material_guid},
                "index": 1,
                "name": "Structural concrete",
            }
        },
    )
    data = [
        {
            "name": "LAB hollow 20x40",
            "skins": [
                {
                    "building_material": "structural CONCRETE",
                    "contours": [
                        {
                            "points": [
                                {"x": 0, "y": 0},
                                {"x": 0.2, "y": 0},
                                {"x": 0.2, "y": 0.4},
                                {"x": 0, "y": 0.4},
                            ]
                        },
                        {
                            "points": [
                                {"x": 0.05, "y": 0.05},
                                {"x": 0.15, "y": 0.05},
                                {"x": 0.15, "y": 0.35},
                                {"x": 0.05, "y": 0.35},
                            ]
                        },
                    ],
                    "contour_pen": 1,
                    "is_core": True,
                }
            ],
            "walls": True,
            "beams": False,
        }
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await profiles.create_profiles(client, data, 19723)
        result = await profiles.create_profiles(
            client, data, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    assert result["items"][0]["source_name"] is None
    created = result["items"][0]["after"]["skins"][0]
    assert created["buildingMaterialId"]["attributeId"]["guid"] == material_guid
    assert created["outlineSubPolyEnds"] == [0, 5, 10]
    request = next(row for row in fake.tapir_requests if row["command"] == "CreateProfiles")
    payload = request["parameters"]["profileDataArray"][0]
    assert "sourceAttributeId" not in payload
    assert len(payload["newSkins"][0]["contours"]) == 2


async def test_profile_refuses_existing_missing_and_duplicate_names():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError, match="already exists"):
            await profiles.create_profiles(
                client, [{"name": "Rectangular 20x40", "source_profile": "Rectangular 20x40"}]
            )
        with pytest.raises(ValueError, match="does not exist"):
            await profiles.create_profiles(client, [{"name": "New", "source_profile": "Missing"}])
        with pytest.raises(ValueError, match="appears twice"):
            await profiles.create_profiles(
                client,
                [
                    {"name": "New", "source_profile": "Rectangular 20x40"},
                    {"name": "new", "source_profile": "Rectangular 20x40"},
                ],
            )
    assert "CreateProfiles" not in fake.tapir_calls


async def test_profile_requires_geometry_and_existing_material():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError, match="source_profile, skins"):
            await profiles.create_profiles(client, [{"name": "New"}], 19723)
        with pytest.raises(ValueError, match="building material.*does not exist"):
            await profiles.create_profiles(
                client,
                [
                    {
                        "name": "New",
                        "skins": [
                            {
                                "building_material": "Missing",
                                "contours": [
                                    {
                                        "points": [
                                            {"x": 0, "y": 0},
                                            {"x": 0.2, "y": 0},
                                            {"x": 0.2, "y": 0.4},
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
                19723,
            )
