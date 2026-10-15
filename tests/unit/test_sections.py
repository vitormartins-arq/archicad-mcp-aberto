import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import sections
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[dict(s) for s in STORIES], **kwargs)


def section(**changes):
    return {
        "start": {"x": 0, "y": 2},
        "end": {"x": 6, "y": 2},
        "floor_index": 0,
        "name": "Corte AA",
        **changes,
    }


async def apply(c, inputs):
    preview = await sections.create_sections(c, inputs, 19723)
    return await sections.create_sections(c, inputs, 19723, False, preview["confirmation_token"])


async def test_preview_then_apply_verifies_story_and_project_map():
    fake = model()
    inputs = [section(depth=8), section(name="Corte BB", floor_index=1)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await sections.create_sections(c, inputs, 19723)
        assert "CreateSections" not in fake.tapir_calls
        assert preview["dry_run"] and preview["items"][0]["status"] == "ready"
        result = await sections.create_sections(
            c, inputs, 19723, False, preview["confirmation_token"]
        )
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateSections")
    assert sent["parameters"]["sectionsData"] == [
        {
            "startCoordinate": {"x": 0.0, "y": 2.0},
            "endCoordinate": {"x": 6.0, "y": 2.0},
            "depth": 8.0,
            "name": "Corte AA",
            "floorIndex": 0,
        },
        {
            "startCoordinate": {"x": 0.0, "y": 2.0},
            "endCoordinate": {"x": 6.0, "y": 2.0},
            "depth": 1.0,
            "name": "Corte BB",
            "floorIndex": 1,
        },
    ]
    assert result["status"] == "verified"
    assert [i["reference_id"] for i in result["items"]] == ["S-01", "S-02"]
    assert all(i["navigator_guid"] and i["section_receipt_id"] for i in result["items"])
    assert fake.tapir_calls.count("CreateSections") == 1


async def test_existing_or_repeated_name_and_missing_story_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(c, [section()])
        with pytest.raises(ValueError, match="already exists"):
            await sections.create_sections(c, [section(name="corte aa")], 19723)
        with pytest.raises(ValueError, match="appears twice"):
            await sections.create_sections(c, [section(name="X"), section(name="x")], 19723)
        with pytest.raises(ValueError, match="story 5"):
            await sections.create_sections(c, [section(name="Y", floor_index=5)], 19723)
    assert fake.tapir_calls.count("CreateSections") == 1


@pytest.mark.parametrize(
    "item",
    [
        section(end={"x": 0, "y": 2}),
        section(name=" Corte"),
        section(name=""),
        section(depth=0),
        section(depth=float("inf")),
        section(extra=1),
    ],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await sections.create_sections(c, [item], 19723)
    assert fake.calls == []


async def test_wrong_story_or_project_map_name_is_verification_failed():
    fake = model(section_wrong_floor=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [section()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["floorIndex"]
    fake = model(section_stored_name="Outro nome")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [section()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["navigator_name"]
    assert result["status"] == "needs_review"


async def test_limits_partial_error_lost_response_and_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await sections.create_sections(c, [])
        with pytest.raises(ValueError):
            await sections.create_sections(c, [section(name=f"C{i}") for i in range(21)])
        preview = await sections.create_sections(c, [section()])
        with pytest.raises(ValueError, match="explicit port"):
            await sections.create_sections(
                c, [section()], None, False, preview["confirmation_token"]
            )
    error = {"error": {"code": -1, "message": "Failed to create section."}}
    fake = model(create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [section(), section(name="Corte BB")])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_section_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [section()])
    assert result["items"][0]["status"] == "unknown"
    assert "do not retry" in result["warning"]
    assert fake.tapir_calls.count("CreateSections") == 1
