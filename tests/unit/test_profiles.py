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
