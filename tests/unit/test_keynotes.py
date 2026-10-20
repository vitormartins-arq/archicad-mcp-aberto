import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import keynotes
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALLS = "CCCCCCCC-0000-4000-8000-000000000001"
GHOST = "CCCCCCCC-0000-4000-8000-000000000009"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def tree():
    item = {
        "keynoteItemId": {"guid": "CCCCCCCC-0000-4000-8000-000000000002"},
        "key": "01.01",
        "title": "Alvenaria",
        "description": "",
        "reference": "",
        "uiText": "01.01 Alvenaria",
    }
    folder = {
        "keynoteFolderId": {"guid": WALLS},
        "key": "01",
        "title": "Paredes",
        "reference": "",
        "uiText": "01 Paredes",
        "subFolders": [],
        "items": [item],
    }
    return {"foldersInRoot": [folder], "itemsInRoot": []}


def model(**kwargs):
    return FakeArchicad(19723, keynotes=tree(), **kwargs)


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


async def test_list_keynotes_flattens_with_paths():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        result = await keynotes.list_keynotes(c, 19723)
    assert (result["folder_count"], result["item_count"]) == (1, 1)
    assert result["folders"][0]["path"] == ["01"]
    assert result["items"][0] == {
        "guid": "CCCCCCCC-0000-4000-8000-000000000002",
        "parent_folder_guid": WALLS,
        "path": ["01", "01.01"],
        "key": "01.01",
        "title": "Alvenaria",
        "description": "",
        "reference": "",
    }


async def test_create_folder_and_items_preview_then_apply_reads_back():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await keynotes.create_keynote_folders(c, [{"key": "02", "title": "Pisos"}], 19723)
        assert "CreateKeynoteFolders" not in fake.tapir_calls
        folders = await keynotes.create_keynote_folders(
            c, [{"key": "02", "title": "Pisos"}], 19723, False, preview["confirmation_token"]
        )
        assert folders["status"] == "verified"
        new_folder = folders["items"][0]["guid"]
        inputs = [
            {"parent_folder_guid": WALLS.lower(), "key": "01.02", "title": "Drywall"},
            {
                "parent_folder_guid": new_folder,
                "key": "02.01",
                "title": "Porcelanato",
                "description": "60 x 60 cm",
                "reference": "Memorial 3.2",
            },
            {"key": "99"},
        ]
        result = await apply(keynotes.create_keynote_items, c, inputs)
        listed = await keynotes.list_keynotes(c, 19723)
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateKeynoteItems")
    assert sent["parameters"]["itemsData"][0] == {
        "key": "01.02",
        "parentFolderId": {"guid": WALLS},
        "title": "Drywall",
    }
    assert sent["parameters"]["itemsData"][2] == {"key": "99"}
    assert result["status"] == "verified"
    assert all(i["keynote_receipt_id"] for i in result["items"])
    assert ["02", "02.01"] in [i["path"] for i in listed["items"]]


async def test_existing_or_repeated_key_and_missing_parent_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await keynotes.create_keynote_items(c, [{"key": "01.01"}], 19723)
        with pytest.raises(ValueError, match="already exists"):
            await keynotes.create_keynote_folders(c, [{"key": "01", "title": "X"}], 19723)
        with pytest.raises(ValueError, match="appears twice"):
            await keynotes.create_keynote_items(c, [{"key": "A"}, {"key": "a"}], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await keynotes.create_keynote_items(
                c, [{"key": "B", "parent_folder_guid": GHOST}], 19723
            )
    assert not any(cmd.startswith("CreateKeynote") for cmd in fake.tapir_calls)


@pytest.mark.parametrize(
    "item",
    [{"key": ""}, {"key": " A"}, {"key": "A", "parent_folder_guid": "x"}, {"key": "A", "x": 1}],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await keynotes.create_keynote_items(c, [item], 19723)
        with pytest.raises(ValueError):
            await keynotes.create_keynote_folders(c, [{"key": "A"}], 19723)  # title required
    assert fake.calls == []


async def test_partial_error_changed_title_and_lost_response():
    error = {"error": {"code": -1, "message": "Failed to create the keynote item."}}
    fake = model(create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(keynotes.create_keynote_items, c, [{"key": "A"}, {"key": "B"}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(keynote_stored_title="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(keynotes.create_keynote_items, c, [{"key": "A", "title": "Um"}])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["title"]
    fake = model(lose_keynote_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(keynotes.create_keynote_items, c, [{"key": "A"}])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateKeynoteItems") == 1


async def test_limits_and_explicit_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await keynotes.create_keynote_items(c, [])
        with pytest.raises(ValueError):
            await keynotes.create_keynote_items(c, [{"key": f"K{i}"} for i in range(101)])
        with pytest.raises(ValueError):
            await keynotes.create_keynote_folders(
                c, [{"key": f"F{i}", "title": "t"} for i in range(51)]
            )
        preview = await keynotes.create_keynote_items(c, [{"key": "A"}])
        with pytest.raises(ValueError, match="explicit port"):
            await keynotes.create_keynote_items(
                c, [{"key": "A"}], None, False, preview["confirmation_token"]
            )
