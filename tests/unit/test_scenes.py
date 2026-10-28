"""3D scene tools tested only through MockTransport; the add-on is the fake's."""

import json
import math
from copy import deepcopy

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import ValidationError

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import scenes
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ZONE = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
SMALL = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
WALL = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"
NAME, NUMBER, AREA = (f"{i}0000000-0000-4000-8000-000000000000" for i in (1, 2, 3))
ONE_POINT = {
    "name": "Peso Livre - 1P 01",
    "folder": "PESO LIVRE",
    "camera": {"x": 0.5, "y": 4, "z": 1.3},
    "target": {"x": 12, "y": 4},
}
ISOMETRIC = {"name": "ISOMETRICA TERREO", "parallel": {"azimuth": 0.785}, "cut_height": 1.5}


def box(x0, y0, z0, x1, y1, z1):
    return {
        "boundingBox3D": {"xMin": x0, "yMin": y0, "zMin": z0, "xMax": x1, "yMax": y1, "zMax": z1}
    }


def model(**extra):
    fake = FakeArchicad(
        19723,
        elements={ZONE: "Zone", SMALL: "Zone", WALL: "Wall"},
        builtin_property_ids={"Zone_ZoneName": NAME, "Zone_ZoneNumber": NUMBER},
        bounding_boxes_3d={
            ZONE: box(0, 0, 0, 12, 6, 3),
            SMALL: box(20, 0, 0, 22, 2, 3),
            WALL: box(0, -0.2, 0, 12, 0, 3),
        },
        **extra,
    )
    fake.builtin_property_ids["Zone_CalculatedArea"] = AREA
    values = {ZONE: ("PESO LIVRE", "04", 72.0), SMALL: ("COPA", "05", 4.0)}
    for guid, (name, number, area) in values.items():
        fake.property_values[(guid, NAME)] = {"type": "string", "status": "normal", "value": name}
        fake.property_values[(guid, NUMBER)] = {
            "type": "string",
            "status": "normal",
            "value": number,
        }
        fake.property_values[(guid, AREA)] = {"type": "number", "status": "normal", "value": area}
    return fake


def client(*instances):
    return ArchicadClient(ports=(19723,), transport=fake_transport(*instances))


async def test_read_scene_model_names_rooms_and_suggests_cameras():
    fake = model(tapir_version=None)
    async with client(fake) as c:
        result = await scenes.read_scene_model(c)
    rooms = {z["name"]: z for z in result["zones"]}
    big = rooms["PESO LIVRE"]
    assert big["number"] == "04" and big["area"] == 72.0
    shots = big["suggested"]["shots"]
    assert [s["kind"] for s in shots] == ["1P", "2P"]
    one = shots[0]
    # Level, along the longer side, 0.5 m from the wall and off the axis.
    assert one["camera"] == {"x": 0.5, "y": 4.0, "z": 1.3}
    assert one["target"] == {"x": 12, "y": 4.0}
    assert one["name"] == "PESO LIVRE - 1P 01" and one["folder"] == "PESO LIVRE"
    assert rooms["COPA"]["suggested"] == {"skip": "smaller than 6 m2"}
    assert result["element_boxes"]["Wall"] == [[0, -0.2, 12, 0, 0, 3]]
    assert fake.tapir_calls == [] and fake.own_addon_calls == []


ROOM = {
    "name": "SALA",
    "area": 72.0,
    "box": {"xMin": 0, "yMin": 0, "zMin": 0, "xMax": 12, "yMax": 6, "zMax": 3},
}


@pytest.mark.parametrize("name", ["DML", "Depósito 2", "DEP. LIMPEZA", "Almoxarifado"])
def test_service_rooms_are_skipped(name):
    result = scenes.suggest_cameras({**ROOM, "name": name})
    assert result["skip"].startswith("service room")


def test_camera_moves_when_a_wall_blocks_the_view():
    # A partition across the room at x 6 hides the far wall for every view along x.
    wall = (5.9, 0, 6.1, 6)
    shots = scenes.suggest_cameras(ROOM, [wall])["shots"]
    one = shots[0]
    assert one["camera"]["x"] == one["target"]["x"]  # looks along y instead
    assert not scenes._blockers(one["camera"], one["target"], [wall])


def test_camera_never_stands_in_a_room_nested_in_this_box():
    nested = (9, 3, 12, 6)  # a smaller room in the far corner, like the gym in the parking
    result = scenes.suggest_cameras(ROOM, [], [nested])
    for shot in result["shots"]:
        assert not scenes._inside(shot["camera"]["x"], shot["camera"]["y"], nested)


def test_blocked_everywhere_says_so():
    walls = [(5.9, 0, 6.1, 6), (0, 2.9, 12, 3.1)]
    result = scenes.suggest_cameras(ROOM, walls)
    assert any("crosses" in w for w in result["warnings"])


def test_same_room_names_get_the_zone_number():
    zones = [
        {"name": "BAN FEM", "number": "12"},
        {"name": "BAN FEM", "number": "13"},
        {"name": "RECEPCAO", "number": "01"},
        {"name": "WC", "number": None},
        {"name": "WC", "number": None},
    ]
    scenes._label_rooms(zones)
    labels = [z["label"] for z in zones]
    assert labels[:3] == ["BAN FEM 12", "BAN FEM 13", "RECEPCAO"]
    assert len(set(labels)) == len(labels)


async def test_image_and_save_wait_longer_than_other_calls():
    fake = model()
    seen = {}
    async with client(fake) as c:
        original = c.own_addon

        async def spy(port, name, parameters=None, *, timeout=None):
            seen[name] = timeout
            return await original(port, name, parameters, timeout=timeout)

        c.own_addon = spy
        await scenes.shoot_3d_scenes(c, [ONE_POINT])
    assert seen["Get3DWindowImage"] == scenes.SLOW_COMMAND_TIMEOUT
    assert seen["Set3DCamera"] is None


async def test_height_band_keeps_one_story():
    fake = model()
    async with client(fake) as c:
        result = await scenes.read_scene_model(c, min_z=4.0)
    assert result["element_boxes"]["Wall"] == []


async def test_shoot_returns_images_and_puts_the_3d_window_back():
    fake = model()
    fake.cut_3d = {
        "enabled": True,
        "planes": [{"cutStatus": 8, "pa": 0, "pb": 0, "pc": 1, "pd": 3.28, "cutPen": 1}],
    }
    before_camera, before_cut = deepcopy(fake.camera_3d), deepcopy(fake.cut_3d)
    async with client(fake) as c:
        report, images = await scenes.shoot_3d_scenes(c, [ONE_POINT, ISOMETRIC])
    assert [r["status"] for r in report["scenes"]] == ["shot", "shot"]
    assert [name for name, _ in images] == ["Peso Livre - 1P 01", "ISOMETRICA TERREO"]
    assert images[0][1].startswith(b"\xff\xd8")
    sets = [r["parameters"] for r in fake.own_addon_requests if r["command"] == "Set3DCamera"]
    perspective = sets[0]["perspective"]
    assert perspective["target"]["z"] == 1.3  # level camera
    assert perspective["twoPointPerspective"] is False
    assert math.isclose(perspective["viewCone"], math.radians(60))
    cuts = [r["parameters"] for r in fake.own_addon_requests if r["command"] == "Set3DCutPlanes"]
    assert cuts[0] == {"enabled": False}
    assert cuts[1]["planes"][0]["pd"] == 1.5
    assert fake.camera_3d["camera"] == before_camera["camera"]
    assert fake.camera_3d["target"] == before_camera["target"]
    assert fake.cut_3d == before_cut
    assert fake.saved_3d_views == []


async def test_one_failed_shot_does_not_stop_the_others():
    fake = model(own_addon_errors={"Show3DAll"})
    async with client(fake) as c:
        report, images = await scenes.shoot_3d_scenes(c, [ISOMETRIC, ONE_POINT])
    assert [r["status"] for r in report["scenes"]] == ["failed", "shot"]
    assert len(images) == 1


async def test_missing_addon_says_how_to_install():
    fake = model(own_addon_loaded=False)
    async with client(fake) as c:
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await scenes.shoot_3d_scenes(c, [ONE_POINT])
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await scenes.save_3d_scenes(c, [ONE_POINT], ["AMBIENTES"])


async def test_save_previews_then_saves_one_folder_per_room():
    fake = model()
    folder = ["02 | MODELO 3D", "AMBIENTES"]
    async with client(fake) as c:
        preview = await scenes.save_3d_scenes(c, [ONE_POINT, ISOMETRIC], folder, as_cameras=False)
        assert fake.saved_3d_views == []
        assert preview["views"][0]["folder_path"] == [*folder, "PESO LIVRE"]
        result = await scenes.save_3d_scenes(
            c,
            [ONE_POINT, ISOMETRIC],
            folder,
            port=19723,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
            as_cameras=False,
        )
        assert result["saved"] == 2
        with pytest.raises(ValueError, match="consumed"):
            await scenes.save_3d_scenes(
                c,
                [ONE_POINT, ISOMETRIC],
                folder,
                port=19723,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
                as_cameras=False,
            )
    first, second = fake.saved_3d_views
    assert first["folderPath"] == [*folder, "PESO LIVRE"]
    assert first["camera"]["isPerspective"] and first["cut"]["enabled"] is False
    assert second["folderPath"] == folder
    assert not second["camera"]["isPerspective"] and second["cut"]["planes"][0]["pd"] == 1.5
    assert fake.camera_3d["isPerspective"] and fake.cut_3d["enabled"] is False


async def test_save_adds_a_camera_to_each_perspective_by_default():
    fake = model()
    folder = ["02 | MODELO 3D", "CÂMERAS BIMx"]
    async with client(fake) as c:
        preview = await scenes.save_3d_scenes(c, [ONE_POINT, ISOMETRIC], folder)
        assert [v["kind"] for v in preview["views"]] == ["camera", "view"]
        assert preview["camera_path"] == "00 BIMx - Apresentação"
        assert preview["views"][0]["camera_name"] == "1 PESO LIVRE - 1P 01"
        result = await scenes.save_3d_scenes(
            c,
            [ONE_POINT, ISOMETRIC],
            folder,
            port=19723,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
        )
    assert result["saved"] == 2 and result["views"][0]["camera_guid"]
    (camera,) = fake.saved_cameras
    # One path for every room, numbered with the room name; no View Map item, no folder.
    assert camera["name"] == "1 PESO LIVRE - 1P 01"
    assert camera["folderPath"] == [] and camera["viewMap"] is False
    assert camera["pathName"] == "00 BIMx - Apresentação"
    assert result["views"][0]["camera_name_set"] is True
    assert [v["name"] for v in fake.saved_3d_views] == ["Peso Livre - 1P 01", "ISOMETRICA TERREO"]
    assert result["views"][1].get("camera_guid") is None


async def test_save_refuses_a_changed_camera_choice():
    fake = model()
    async with client(fake) as c:
        preview = await scenes.save_3d_scenes(c, [ONE_POINT], ["AMBIENTES"])
        with pytest.raises(ValueError, match="changed"):
            await scenes.save_3d_scenes(
                c, [ONE_POINT], ["AMBIENTES"], port=19723, dry_run=False,
                confirmation_token=preview["confirmation_token"], as_cameras=False,
            )  # fmt: skip
    assert fake.saved_cameras == [] and fake.saved_3d_views == []


async def test_save_refuses_changed_inputs_and_missing_port():
    fake = model()
    async with client(fake) as c:
        preview = await scenes.save_3d_scenes(c, [ONE_POINT], ["AMBIENTES"])
        token = preview["confirmation_token"]
        with pytest.raises(ValueError, match="explicit port"):
            await scenes.save_3d_scenes(
                c, [ONE_POINT], ["AMBIENTES"], dry_run=False, confirmation_token=token
            )
        with pytest.raises(ValueError, match="changed"):
            await scenes.save_3d_scenes(
                c, [ONE_POINT], ["OUTRA"], port=19723, dry_run=False, confirmation_token=token
            )
    assert fake.saved_3d_views == []


@pytest.mark.parametrize(
    "scene",
    [
        {"name": "x"},
        {"name": "x", "camera": {"x": 0, "y": 0, "z": 1.3}},
        {"name": "x", "camera": {"x": 0, "y": 0, "z": 1.3}, "target": {"x": 0.1, "y": 0}},
        {**ONE_POINT, "cut_height": 1.5},
        {**ONE_POINT, "parallel": {}},
        {**ONE_POINT, "view_cone": 60},
    ],
)
def test_scene_validation(scene):
    with pytest.raises(ValidationError):
        scenes.Scene.model_validate(scene)


async def test_shoot_tool_returns_image_content():
    server = create_server(lambda: client(model()))
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("shoot_3d_scenes", {"scenes": [ONE_POINT]})
    blocks = result.content
    assert not result.isError
    assert json.loads(blocks[0].text)["scenes"][0]["status"] == "shot"
    assert blocks[1].text == "Peso Livre - 1P 01"
    assert blocks[2].type == "image" and blocks[2].mimeType == "image/jpeg"
