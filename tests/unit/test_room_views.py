"""Room enlargement views (SaveStoryView of our add-on), against the simulated Archicad."""

import pytest

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import room_views
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
NAME, NUMBER, AREA = (f"{i}0000000-0000-4000-8000-000000000000" for i in (1, 2, 3))
STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}, {"index": 1, "name": "1º", "level": 3.0}]
# guid -> (name, number, story, plan box)
ROOMS = {
    "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA": ("COZINHA", "10", 0, (0, 0, 4, 3)),
    "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB": ("BANHO", "2", 0, (5, 0, 7, 2)),
    "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC": ("BANHO", "11", 1, (5, 0, 7, 2.5)),
}


def model(**extra):
    fake = FakeArchicad(
        19723,
        stories=[dict(s) for s in STORIES],
        elements={guid: "Zone" for guid in ROOMS},
        builtin_property_ids={
            "Zone_ZoneName": NAME,
            "Zone_ZoneNumber": NUMBER,
            "Zone_CalculatedArea": AREA,
        },
        **extra,
    )
    for guid, (name, number, story, (x0, y0, x1, y1)) in ROOMS.items():
        fake.details[guid] = {"type": "Zone", "floorIndex": story}
        fake.bounding_boxes_3d[guid] = {
            "boundingBox3D": {"xMin": x0, "yMin": y0, "zMin": 0, "xMax": x1, "yMax": y1, "zMax": 3}
        }
        for prop, value in ((NAME, name), (NUMBER, number), (AREA, 6.0)):
            kind = "number" if prop == AREA else "string"
            fake.property_values[(guid, prop)] = {"type": kind, "status": "normal", "value": value}
    return fake


def client(fake):
    return ArchicadClient(ports=(19723,), transport=fake_transport(fake))


async def apply(c, **kwargs):
    preview = await room_views.save_room_plan_views(c, **kwargs)
    result = await room_views.save_room_plan_views(
        c, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"], **kwargs
    )
    return preview, result


async def test_one_numbered_view_per_room_in_its_folder():
    fake = model()
    async with client(fake) as c:
        preview, result = await apply(c, folder_path=["03 | AMPLIACOES"])
    assert fake.saved_story_views and len(fake.saved_story_views) == 3
    names = [v["name"] for v in preview["views"]]
    # Story first, then zone number in natural order; repeated names get the number.
    assert names == ["AMP 01 - BANHO 2", "AMP 02 - COZINHA", "AMP 03 - BANHO 11"]
    first = preview["views"][0]
    assert first["folder_path"] == ["03 | AMPLIACOES", "BANHO 2"]
    assert first["zoom"] == {"xMin": 4.5, "yMin": -0.5, "xMax": 7.5, "yMax": 2.5}
    assert first["drawing_scale"] == 25 and first["story"] == "Térreo"
    assert [v["status"] for v in result["views"]] == ["verified"] * 3
    sent = fake.saved_story_views[2]
    assert sent["storyIndex"] == 1 and sent["drawingScale"] == 25


async def test_room_and_story_filters_and_layer_combination():
    fake = model(layer_combinations={1: {"name": "AMPLIAÇÃO", "layers": {}}})
    async with client(fake) as c:
        preview = await room_views.save_room_plan_views(
            c, ["AMP"], rooms=["cozinha"], prefix="AMPL", first_number=7, margin=0.2,
            scale=None, layer_combination="ampliação",
        )  # fmt: skip
        (view,) = preview["views"]
        assert view["name"] == "AMPL 07 - COZINHA"
        assert view["layer_combination"] == "AMPLIAÇÃO" and "drawing_scale" not in view
        upstairs = await room_views.save_room_plan_views(c, ["AMP"], stories=[1])
        assert [v["room"] for v in upstairs["views"]] == ["BANHO 11"]


async def test_ignored_setting_is_caught():
    fake = model(story_view_ignored={"drawingScale"})
    async with client(fake) as c:
        _, result = await apply(c, folder_path=["AMP"], rooms=["COZINHA"])
    assert result["views"][0]["mismatches"] == ["drawing_scale"]


async def test_refusals():
    async with client(model()) as c:
        with pytest.raises(ValueError, match="No room"):
            await room_views.save_room_plan_views(c, ["AMP"], rooms=["SALA"])
        with pytest.raises(ValueError, match="Stories"):
            await room_views.save_room_plan_views(c, ["AMP"], stories=[5])
        with pytest.raises(ValueError, match="Layer combination"):
            await room_views.save_room_plan_views(c, ["AMP"], layer_combination="Nada")
        with pytest.raises(ValueError, match="explicit port"):
            await room_views.save_room_plan_views(c, ["AMP"], dry_run=False)
        preview = await room_views.save_room_plan_views(c, ["AMP"])
        with pytest.raises(ValueError, match="changed"):
            await room_views.save_room_plan_views(
                c, ["AMP"], margin=1.0, port=19723, dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )  # fmt: skip
    for bad in ({"folder_path": []}, {"folder_path": ["A"], "scale": 0}):
        with pytest.raises(ValueError):
            await room_views.save_room_plan_views(None, **bad)


async def test_missing_addon_says_how_to_install():
    async with client(model(own_addon_loaded=False)) as c:
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await room_views.save_room_plan_views(c, ["AMP"])
