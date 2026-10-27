"""place_hotlinks (Tapir 1.7.0 CreateHotlinkNodes/Instances), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import hotlinks
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
BATH = r"H:\Meu Drive\Modulos\Banheiro 01.mod"
KITCHEN = "C:/Modulos/Cozinha.pln"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    stories = [{"index": 0, "name": "Térreo", "level": 0.0}, {"index": 1, "name": "1º", "level": 3}]
    return FakeArchicad(19723, stories=stories, **kwargs)


async def apply(c, items):
    preview = await hotlinks.place_hotlinks(c, items, 19723)
    return preview, await hotlinks.place_hotlinks(
        c, items, 19723, False, preview["confirmation_token"]
    )


async def test_one_node_per_file_and_instances_read_back():
    fake = model()
    items = [
        {"source_path": BATH, "origin": {"x": 1, "y": 2}, "floor_index": 0},
        {"source_path": BATH.upper(), "origin": {"x": 5, "y": 2}, "floor_index": 1,
         "angle": 1.5708, "mirrored": True},
        {"source_path": KITCHEN, "origin": {"x": 0, "y": 8, "z": 0.1}, "floor_index": 0,
         "name": "Cozinha", "single_story": 0},
    ]  # fmt: skip
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, items)
    assert preview["hotlink_nodes"] == [
        {"sourceLocation": BATH},
        {"sourceLocation": KITCHEN, "name": "Cozinha", "storyRangeType": "SingleStory",
         "refFloorIndex": 0},
    ]  # fmt: skip
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateHotlinkInstances")
    first, second, _ = request["parameters"]["hotlinkInstances"]
    assert first["hotlinkNodeId"] == second["hotlinkNodeId"]
    assert second == {
        "origin": {"x": 5.0, "y": 2.0, "z": 0.0},
        "rotationAngle": 1.5708,
        "mirrored": True,
        "floorIndex": 1,
        "hotlinkNodeId": first["hotlinkNodeId"],
    }
    assert result["status"] == "verified"
    assert len(fake.hotlink_nodes) == 2


async def test_existing_node_is_reused():
    fake = model()
    fake.hotlink_nodes.append(
        {"location": BATH, "hotlinkNodeId": {"guid": "B0000000-0000-4000-8000-000000000001"},
         "name": "Banheiro 01", "type": "Module"}
    )  # fmt: skip
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(
            c, [{"source_path": BATH, "origin": {"x": 0, "y": 0}, "floor_index": 0}]
        )
    assert preview["items"][0]["node"].startswith("existing")
    assert result["items"][0]["node_guid"] == "B0000000-0000-4000-8000-000000000001"
    assert result["status"] == "verified" and len(fake.hotlink_nodes) == 1


async def test_missing_file_fails_its_instances_only():
    fake = model(missing_hotlink_files={KITCHEN})
    items = [
        {"source_path": KITCHEN, "origin": {"x": 0, "y": 0}, "floor_index": 0},
        {"source_path": BATH, "origin": {"x": 3, "y": 0}, "floor_index": 0},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, items)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


async def test_preview_refusals():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="story 7 does not exist"):
            await hotlinks.place_hotlinks(
                c, [{"source_path": BATH, "origin": {"x": 0, "y": 0}, "floor_index": 7}], 19723
            )
        with pytest.raises(ValueError, match="other name or story"):
            await hotlinks.place_hotlinks(
                c,
                [
                    {"source_path": BATH, "origin": {"x": 0, "y": 0}, "floor_index": 0},
                    {
                        "source_path": BATH,
                        "origin": {"x": 0, "y": 0},
                        "floor_index": 0,
                        "name": "Outro",
                    },
                ],  # fmt: skip
                19723,
            )


@pytest.mark.parametrize(
    "path", ["Modulos/Banheiro.mod", r"C:\Modulos\Banheiro.pla", " C:/a.mod", "C:/a.gsm"]
)
def test_bad_paths_are_refused(path):
    with pytest.raises(ValidationError):
        hotlinks.HotlinkPlace.model_validate(
            {"source_path": path, "origin": {"x": 0, "y": 0}, "floor_index": 0}
        )
