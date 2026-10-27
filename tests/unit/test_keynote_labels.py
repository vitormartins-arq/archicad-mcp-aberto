"""Keynote labels (Tapir 1.7.0 CreateKeynoteLabels), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import labels
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ITEM = "5A6B7C8D-0000-4000-8000-000000000001"
MISSING = "5A6B7C8D-0000-4000-8000-0000000000FF"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    fake = FakeArchicad(19723, stories=[{"index": 0, "name": "Térreo", "level": 0.0}], **kwargs)
    folder = {
        "keynoteFolderId": {"guid": "5A6B7C8D-0000-4000-8000-0000000000F0"},
        "key": "A",
        "title": "Acabamentos",
        "reference": "",
        "subFolders": [],
        "items": [
            {
                "keynoteItemId": {"guid": ITEM},
                "key": "A.01",
                "title": "Piso cerâmico",
                "description": "Assentado com argamassa",
                "reference": "NBR 13753",
            }
        ],
    }
    fake.keynotes["foldersInRoot"].append(folder)
    return fake


def label(**changes):
    return {"keynote_item_guid": ITEM.lower(), "position": {"x": 2, "y": 3}, **changes}


async def apply(c, items):
    preview = await labels.create_keynote_labels(c, items, 19723)
    result = await labels.create_keynote_labels(
        c, items, 19723, False, preview["confirmation_token"]
    )
    return preview, result


async def test_keynote_label_placed_and_verified():
    fake = model(shown_story=0)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [label(content_fields=["Key", "Title"])])
    assert preview["items"][0]["keynote"] == {
        "key": "A.01",
        "title": "Piso cerâmico",
        "path": ["A", "A.01"],
    }
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateKeynoteLabels")
    assert sent["parameters"]["labelsData"] == [
        {
            "keynoteItemId": {"guid": ITEM},
            "position": {"x": 2.0, "y": 3.0},
            "contentFields": ["Key", "Title"],
        }
    ]
    item = result["items"][0]
    assert item["status"] == "verified"
    assert item["floorIndex"] == 0 and item["text_read"] == "A.01\nPiso cerâmico"


async def test_all_fields_by_default_and_keynotes_unchanged():
    fake = model()
    before = repr(fake.keynotes)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [label()])
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateKeynoteLabels")
    assert "contentFields" not in sent["parameters"]["labelsData"][0]
    assert result["items"][0]["status"] == "verified"
    assert repr(fake.keynotes) == before
    assert not {"CreateKeynoteItems", "ModifyKeynoteItems", "DeleteKeynoteItems"} & set(
        r["command"] for r in fake.tapir_requests
    )


async def test_unknown_keynote_item_refused_in_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="no keynote item"):
            await labels.create_keynote_labels(c, [label(keynote_item_guid=MISSING)], 19723)
    assert "CreateKeynoteLabels" not in [r["command"] for r in fake.tapir_requests]


async def test_failed_item_reported_and_others_verified():
    fake = model(
        create_errors={0: {"error": {"code": -1, "message": "Failed to create the label."}}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [label(), label(position={"x": 5, "y": 5})])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


async def test_moved_label_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await labels.create_keynote_labels(c, [label()], 19723)
        fake.keynote_label_shift = 0.5
        result = await labels.create_keynote_labels(
            c, [label()], 19723, False, preview["confirmation_token"]
        )
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert "details.begCoordinate.x" in item["mismatches"]


@pytest.mark.parametrize(
    "bad",
    [
        {"keynote_item_guid": "not-a-guid"},
        {"content_fields": []},
        {"content_fields": ["Key", "Key"]},
        {"content_fields": ["Notes"]},
        {"position": None},
    ],
)
async def test_invalid_input_refused(bad):
    with pytest.raises(ValidationError):
        labels.KeynoteLabelCreate.model_validate(label(**bad))


async def test_count_limits():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await labels.create_keynote_labels(c, [])
        with pytest.raises(ValueError, match="between 1 and 20"):
            await labels.create_keynote_labels(c, [label()] * 21)
