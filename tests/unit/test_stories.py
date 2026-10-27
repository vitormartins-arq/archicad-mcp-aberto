"""add_stories (Tapir 1.7.0 SetStories), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import stories
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
TWO = [
    {"index": 0, "floorId": 1, "dispOnSections": True, "level": 0.0, "height": 3.0,
     "name": "Térreo"},
    {"index": 1, "floorId": 2, "dispOnSections": False, "level": 3.0, "height": 3.0,
     "name": "1º Pavimento"},
]  # fmt: skip


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[dict(s) for s in TWO], **kwargs)


async def apply(c, items):
    preview = await stories.add_stories(c, items, 19723)
    return preview, await stories.add_stories(c, items, 19723, False, preview["confirmation_token"])


async def test_stories_added_above_and_below_keep_the_existing_ones():
    fake = model()
    wanted = [
        {"name": "Cobertura", "level": 9.2},
        {"name": "Subsolo", "level": -3.2, "show_on_sections": False},
        {"name": "2º Pavimento", "level": 6.1},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, wanted)
    assert [(s["index"], s["name"], s["height"], s["new"]) for s in preview["structure_after"]] == [
        (-1, "Subsolo", 3.2, True),
        (0, "Térreo", 3.0, False),
        (1, "1º Pavimento", 3.1, False),
        (2, "2º Pavimento", 3.1, True),
        (3, "Cobertura", None, True),
    ]
    request = next(r for r in fake.tapir_requests if r["command"] == "SetStories")
    assert request["parameters"]["stories"] == [
        {"index": -1, "name": "Subsolo", "level": -3.2, "dispOnSections": False},
        {"index": 0, "name": "Térreo", "level": 0.0, "dispOnSections": True},
        {"index": 1, "name": "1º Pavimento", "level": 3.0, "dispOnSections": False},
        {"index": 2, "name": "2º Pavimento", "level": 6.1, "dispOnSections": False},
        {"index": 3, "name": "Cobertura", "level": 9.2, "dispOnSections": False},
    ]
    assert result["status"] == "verified"
    assert [i["name"] for i in result["items"]] == ["Subsolo", "2º Pavimento", "Cobertura"]
    assert "existing_stories_changed" not in result


@pytest.mark.parametrize(
    ("story", "message"),
    [
        ({"name": "Mezanino", "level": 1.5}, "not above the top story"),
        ({"name": "Rente", "level": 3.005}, "not above the top story"),
        ({"name": "térreo", "level": 9.0}, "already used"),
    ],
)
async def test_preview_refuses_what_would_renumber_or_repeat(story, message):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await stories.add_stories(c, [story], 19723)
    assert "SetStories" not in fake.tapir_calls


async def test_new_stories_too_close_are_refused():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="less than 0.01 m apart"):
            await stories.add_stories(
                c, [{"name": "A", "level": 6.0}, {"name": "B", "level": 6.005}], 19723
            )


async def test_level_not_kept_fails_verification():
    fake = model(set_stories_level_drift=0.5)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"name": "Cobertura", "level": 6.0}])
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["level"]


async def test_refused_set_reports_failure_and_rereads():
    fake = model(set_stories_error={"code": -1, "message": "Failed to create new story."})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"name": "Cobertura", "level": 6.0}])
    assert result["items"][0]["status"] == "failed"
    assert "stopped halfway" in result["warning"]
    assert "existing_stories_changed" not in result


@pytest.mark.parametrize(
    "bad",
    [{"name": "", "level": 1.0}, {"name": " X", "level": 1.0}, {"name": "X"},
     {"name": "X", "level": 1.0, "height": 3.0}],
)  # fmt: skip
def test_bad_input_is_refused(bad):
    with pytest.raises(ValidationError):
        stories.StoryCreate.model_validate(bad)


async def test_count_limits():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await stories.add_stories(c, [])
