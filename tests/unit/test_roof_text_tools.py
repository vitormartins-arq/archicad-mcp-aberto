import math

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import roofs, texts, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
SQUARE = [{"x": 0, "y": 0}, {"x": 6, "y": 0}, {"x": 6, "y": 4}, {"x": 0, "y": 4}]
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[dict(s) for s in STORIES], **kwargs)


def multi(**changes):
    return {"outline": SQUARE, "floor_index": 1, "level": 6.0, "thickness": 0.25, **changes}


def single(**changes):
    line = {"start": {"x": 0, "y": 0}, "end": {"x": 6, "y": 0}}
    roof = multi(pivot_line=line, angle=math.radians(30))
    roof.update(changes)
    return {k: v for k, v in roof.items() if v is not None}


def text(**changes):
    return {"text": "Sala", "position": {"x": 2, "y": 3}, "floor_index": 0, **changes}


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def sent(fake, command, key):
    return next(r for r in fake.tapir_requests if r["command"] == command)["parameters"][key]


async def test_multi_plane_roof_preview_then_apply():
    fake = model()
    inputs = [
        multi(eaves_overhang=0.5, levels=[{"height": 0, "angle": 0.5}, {"height": 1, "angle": 0.3}])
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await roofs.create_roofs(c, inputs, 19723)
        assert preview["items"][0]["roof_class"] == "MultiPlane"
        assert "CreateRoofs" not in fake.tapir_calls
        result = await roofs.create_roofs(c, inputs, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await roofs.create_roofs(c, inputs, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    payload = sent(fake, "CreateRoofs", "roofsData")[0]
    assert payload["floorIndex"] == 1 and payload["level"] == 6.0
    assert payload["levels"] == [
        {"levelHeight": 0, "levelAngle": 0.5},
        {"levelHeight": 1, "levelAngle": 0.3},
    ]
    assert payload["eavesOverhang"] == 0.5 and "pivotLine" not in payload
    assert result["items"][0]["after"]["details"]["level"] == 3.0
    assert result["items"][0]["roof_receipt_id"]


async def test_multi_plane_roof_with_tool_defaults():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(roofs.create_roofs, c, [multi()])
    assert result["status"] == "verified"
    payload = sent(fake, "CreateRoofs", "roofsData")[0]
    assert "levels" not in payload and "eavesOverhang" not in payload


async def test_single_plane_roof():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(roofs.create_roofs, c, [single()])
    assert result["status"] == "verified"
    payload = sent(fake, "CreateRoofs", "roofsData")[0]
    assert payload["pivotLine"] == {
        "begCoordinate": {"x": 0, "y": 0},
        "endCoordinate": {"x": 6, "y": 0},
    }
    assert payload["angle"] == pytest.approx(math.radians(30))
    assert result["items"][0]["after"]["details"]["roofClass"] == "SinglePlane"


async def test_closed_outline_is_normalized():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(roofs.create_roofs, c, [multi(outline=[*SQUARE, SQUARE[0]])])
    assert result["status"] == "verified"
    assert len(sent(fake, "CreateRoofs", "roofsData")[0]["polygonCoordinates"]) == 4


@pytest.mark.parametrize(
    "roof",
    [
        multi(angle=0.5),
        single(angle=None),
        single(levels=[{"height": 0, "angle": 0.5}]),
        single(eaves_overhang=0.3),
        single(pivot_line={"start": {"x": 1, "y": 1}, "end": {"x": 1, "y": 1}}),
        single(angle=0),
        single(angle=math.pi / 2),
        multi(levels=[]),
        multi(levels=[{"height": 1, "angle": 0.5}, {"height": 0, "angle": 0.5}]),
        multi(levels=[{"height": 0, "angle": -0.1}]),
        multi(eaves_overhang=-0.1),
        multi(thickness=0),
        multi(outline=SQUARE[:2]),
        multi(outline=[{"x": 0, "y": 0}, {"x": 4, "y": 4}, {"x": 4, "y": 0}, {"x": 0, "y": 4}]),
        multi(material="Telha"),
    ],
)
async def test_invalid_roofs_refused_before_network(roof):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await roofs.create_roofs(c, [roof])
    assert not fake.calls


async def test_roof_limits_and_missing_story():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await roofs.create_roofs(c, [])
        with pytest.raises(ValueError):
            await roofs.create_roofs(c, [multi()] * 21)
        with pytest.raises(ValueError, match="story 7"):
            await roofs.create_roofs(c, [multi(floor_index=7)], 19723)
    assert "CreateRoofs" not in fake.tapir_calls


async def test_roof_partial_error_and_lost_response():
    error = {"error": {"code": -1, "message": "Failed to create roof."}}
    fake = model(create_errors={1: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(roofs.create_roofs, c, [multi(), single()])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    fake = model(lose_roof_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(roofs.create_roofs, c, [multi()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateRoofs") == 1


async def test_roof_wrong_geometry_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await roofs.create_roofs(c, [multi()], 19723)
        original = fake._tapir

        def shifted(params):
            response = original(params)
            for row in fake.details.values():
                if row["type"] == "Roof":
                    row["details"]["pivotPolygonOutline"][0]["x"] += 1
            return response

        fake._tapir = shifted
        result = await roofs.create_roofs(c, [multi()], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "verification_failed"
    assert "details.pivotPolygonOutline" in result["items"][0]["mismatches"]


async def test_text_preview_then_apply():
    fake = model()
    inputs = [text(angle=math.pi / 2, height_mm=3.5, justification="Center")]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await texts.create_texts(c, inputs, 19723)
        assert "CreateTexts" not in fake.tapir_calls
        result = await texts.create_texts(c, inputs, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    payload = sent(fake, "CreateTexts", "textsData")[0]
    assert payload == {
        "coordinate": {"x": 2, "y": 3, "z": 0.0},
        "floorIndex": 0,
        "text": "Sala",
        "angle": math.pi / 2,
        "height": 3.5,
        "justification": "Center",
    }
    assert result["items"][0]["text_receipt_id"]


async def test_text_on_upper_story_uses_its_level_and_keeps_defaults():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(texts.create_texts, c, [text(floor_index=1)])
    assert result["status"] == "verified"
    payload = sent(fake, "CreateTexts", "textsData")[0]
    assert payload["coordinate"]["z"] == 3.0 and payload["floorIndex"] == 1
    assert "height" not in payload and "justification" not in payload


async def test_text_line_endings_normalized_both_ways():
    fake = model(text_stored_as="Linha 1\r\nLinha 2")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(texts.create_texts, c, [text(text="Linha 1\r\nLinha 2")])
    assert sent(fake, "CreateTexts", "textsData")[0]["text"] == "Linha 1\nLinha 2"
    assert result["status"] == "verified"


async def test_text_full_turn_angle_still_verifies():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(texts.create_texts, c, [text(angle=2 * math.pi)])
    assert result["status"] == "verified"


async def test_text_stored_differently_fails_verification():
    fake = model(text_stored_as="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(texts.create_texts, c, [text()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["details.text"]


@pytest.mark.parametrize(
    "item",
    [
        text(text=""),
        text(text="   "),
        text(text="x" * 2001),
        text(height_mm=0),
        text(justification="Middle"),
        text(angle=float("inf")),
        text(font="Arial"),
        text(position={"x": 1}),
    ],
)
async def test_invalid_texts_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await texts.create_texts(c, [item])
    assert not fake.calls


async def test_text_limits_story_lost_response_and_journal(monkeypatch):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await texts.create_texts(c, [text()] * 21)
        with pytest.raises(ValueError, match="story 5"):
            await texts.create_texts(c, [text(floor_index=5)], 19723)
    fake = model(lose_text_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(texts.create_texts, c, [text()])
    assert result["items"][0]["status"] == "unknown"

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(texts.create_texts, c, [text()])
    assert "CreateTexts" not in fake.tapir_calls


async def test_apply_requires_explicit_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await texts.create_texts(c, [text()])
        with pytest.raises(ValueError, match="explicit port"):
            await texts.create_texts(c, [text()], None, False, preview["confirmation_token"])
    assert "CreateTexts" not in fake.tapir_calls
