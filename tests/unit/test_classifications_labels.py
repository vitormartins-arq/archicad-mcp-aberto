import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import classifications, labels, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
MISSING = "99999999-9999-4999-8999-999999999999"
AC = "1C4E9A10-3B7F-4D2A-9E61-0A5B7C3D2E11"
UNICLASS = "6A2D8F44-91C3-4B55-8E07-2F6C1B9D4A22"
PAREDE = "A1000000-0000-4000-8000-000000000001"
LAJE = "A1000000-0000-4000-8000-000000000002"
PILAR = "A1000000-0000-4000-8000-000000000004"
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements={WALL: "Wall", SLAB: "Slab"},
        details={
            WALL: {"type": "Wall", "floorIndex": 1, "layerIndex": 1, "details": {}},
            SLAB: {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}},
        },
        stories=[dict(s) for s in STORIES],
        **kwargs,
    )


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def set_request(fake):
    command = "API.SetClassificationsOfElements"
    return next(r for r in fake.command_requests if r["command"] == command)


def change(element=WALL, system="ARCHICAD Classification", item="Parede"):
    return {"element_guid": element, "system": system, "item": item}


async def test_list_systems_and_flat_tree():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        systems = await classifications.list_classifications(c, port=19723)
        tree = await classifications.list_classifications(c, "archicad classification", 19723)
        found = await classifications.list_classifications(c, AC.lower(), 19723, query="pil")
        page = await classifications.list_classifications(c, AC, 19723, offset=1, limit=2)
    assert [s["name"] for s in systems["systems"]] == ["ARCHICAD Classification", "Uniclass"]
    assert tree["total"] == 5
    pilar = next(i for i in tree["items"] if i["id"] == "Pilar")
    assert pilar["depth"] == 1 and pilar["parent_guid"] == "A1000000-0000-4000-8000-000000000003"
    assert [i["guid"] for i in found["items"]] == [PILAR]
    assert [i["id"] for i in page["items"]] == ["Laje", "Estrutura"]
    assert not any(n.startswith("Set") for n in fake.calls)


async def test_list_refuses_unknown_system_and_bad_page():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await classifications.list_classifications(c, "OmniClass", 19723)
        with pytest.raises(ValueError):
            await classifications.list_classifications(c, None, 19723, limit=501)


async def test_preview_then_apply_and_read_back():
    fake = model(classifications={(SLAB, AC): PAREDE})
    inputs = [change(), change(SLAB, AC, LAJE.lower())]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.set_classifications(c, inputs, 19723)
        assert "API.SetClassificationsOfElements" not in fake.calls
        first, second = preview["items"]
        assert first["before"] is None and first["new"]["id"] == "Parede"
        assert first["floorName"] == "Superior" and first["layerName"] == "Walls"
        assert second["before"]["id"] == "Parede" and second["new"]["id"] == "Laje"
        assert not first["unchanged"]
        token = preview["confirmation_token"]
        result = await classifications.set_classifications(c, inputs, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await classifications.set_classifications(c, inputs, 19723, False, token)
    assert result["status"] == "verified"
    assert fake.classifications == {(WALL, AC): PAREDE, (SLAB, AC): LAJE}
    sent = set_request(fake)
    assert sent["parameters"]["elementClassifications"][0] == {
        "elementId": {"guid": WALL},
        "classificationId": {
            "classificationSystemId": {"guid": AC},
            "classificationItemId": {"guid": PAREDE},
        },
    }
    assert all(i["classification_receipt_id"] for i in result["items"])


async def test_item_none_removes_and_unchanged_is_flagged():
    fake = model(classifications={(WALL, AC): PAREDE, (SLAB, AC): LAJE})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.set_classifications(
            c, [change(item=None), change(SLAB, item="Laje")], 19723
        )
        assert preview["items"][0]["new"] is None
        assert preview["items"][1]["unchanged"] is True
        result = await apply(
            classifications.set_classifications, c, [change(item=None), change(SLAB, item="Laje")]
        )
    assert result["status"] == "verified"
    sent = set_request(fake)
    assert (
        "classificationItemId"
        not in sent["parameters"]["elementClassifications"][0]["classificationId"]
    )
    assert fake.classifications == {(SLAB, AC): LAJE}


async def test_same_element_in_two_systems():
    fake = model()
    inputs = [change(), change(system="Uniclass", item="EF_25_10")]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(classifications.set_classifications, c, inputs)
    assert result["status"] == "verified"
    assert fake.classifications[(WALL, UNICLASS)] == "B2000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ([change(system="OmniClass")], "does not exist"),
        ([change(item="Telhado")], "does not exist"),
        ([change(system="Uniclass", item="Walls")], "ambiguous"),
        ([change(), change(system=AC, item="Laje")], "only once"),
        ([change(MISSING)], "does not exist"),
    ],
)
async def test_refused_in_preview(inputs, message):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await classifications.set_classifications(c, inputs, 19723)
    assert "API.SetClassificationsOfElements" not in fake.calls


async def test_locked_element_refused():
    fake = model(locked_elements={WALL})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="non-editable"):
            await classifications.set_classifications(c, [change()], 19723)


@pytest.mark.parametrize(
    "item",
    [
        {"element_guid": "x", "system": "Uniclass", "item": None},
        {"element_guid": WALL, "system": " ", "item": None},
        {"element_guid": WALL, "system": "Uniclass", "item": ""},
        {"element_guid": WALL, "system": "Uniclass"},
        {**change(), "property": "x"},
    ],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await classifications.set_classifications(c, [item])
        with pytest.raises(ValueError):
            await classifications.set_classifications(c, [])
        with pytest.raises(ValueError):
            await classifications.set_classifications(c, [change()] * 101)
    assert not fake.calls


async def test_failed_ignored_and_lost_writes():
    error = {"success": False, "error": {"code": 4012, "message": "Not available."}}
    fake = model(classification_set_errors={1: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(classifications.set_classifications, c, [change(), change(SLAB)])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert result["status"] == "needs_review"

    fake = model(classification_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(classifications.set_classifications, c, [change()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["classificationItemId"]

    fake = model(lose_classification_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(classifications.set_classifications, c, [change()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.calls.count("API.SetClassificationsOfElements") == 1


async def test_classification_changed_since_preview_is_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.set_classifications(c, [change()], 19723)
        fake.classifications[(WALL, AC)] = LAJE
        with pytest.raises(ValueError, match="changed since preview"):
            await classifications.set_classifications(
                c, [change()], 19723, False, preview["confirmation_token"]
            )
    assert "API.SetClassificationsOfElements" not in fake.calls


def label(**changes):
    return {"text": "Parede de tijolo", "element_guid": WALL, **changes}


def free(**changes):
    return {"text": "Nota", "position": {"x": 2, "y": 3}, "floor_index": 0, **changes}


def sent_labels(fake):
    return next(r for r in fake.tapir_requests if r["command"] == "CreateLabels")["parameters"][
        "labelsData"
    ]


async def test_attached_label_preview_then_apply():
    fake = model()
    inputs = [label(position={"x": 1, "y": 0}, height_mm=3.5)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await labels.create_labels(c, inputs, 19723)
        assert preview["items"][0]["floorIndex"] == 1
        assert preview["items"][0]["attached_type"] == "Wall"
        assert "CreateLabels" not in fake.tapir_calls
        result = await labels.create_labels(c, inputs, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert sent_labels(fake) == [
        {
            "labelClass": "Text",
            "text": "Parede de tijolo",
            "parentElementId": {"guid": WALL},
            "begCoordinate": {"x": 1, "y": 0},
            "style": {"height": 3.5},
        }
    ]
    item = result["items"][0]
    assert item["label_receipt_id"] and item["element_guid"] != WALL


async def test_attached_label_without_position_and_free_label():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(labels.create_labels, c, [label(), free(floor_index=1)])
    assert result["status"] == "verified"
    first, second = sent_labels(fake)
    assert "begCoordinate" not in first and "floorInd" not in first
    assert second["floorInd"] == 1 and "parentElementId" not in second
    assert "style" not in second


async def test_label_line_endings_and_wrong_text():
    fake = model(text_stored_as="Linha 1\r\nLinha 2")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(labels.create_labels, c, [free(text="Linha 1\r\nLinha 2")])
    assert sent_labels(fake)[0]["text"] == "Linha 1\nLinha 2"
    assert result["status"] == "verified"
    fake = model(text_stored_as="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(labels.create_labels, c, [label()])
    assert result["items"][0]["mismatches"] == ["details.text"]


async def test_label_on_wrong_owner_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await labels.create_labels(c, [label()], 19723)
        original = fake._tapir

        def moved(params):
            response = original(params)
            for row in fake.details.values():
                if row["type"] == "Label":
                    row["details"]["ownerElementId"] = {"guid": SLAB}
            return response

        fake._tapir = moved
        result = await labels.create_labels(
            c, [label()], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert "details.ownerElementId" in result["items"][0]["mismatches"]


@pytest.mark.parametrize(
    "item",
    [
        label(text=""),
        label(text="  "),
        label(text="x" * 2001),
        label(floor_index=0),
        free(position=None),
        free(floor_index=None),
        {"text": "Nota"},
        label(element_guid="x"),
        label(height_mm=0),
        label(font="Arial"),
    ],
)
async def test_invalid_labels_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await labels.create_labels(c, [{k: v for k, v in item.items() if v is not None}])
    assert not fake.calls


async def test_label_limits_missing_parent_story_and_lost_response():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await labels.create_labels(c, [])
        with pytest.raises(ValueError):
            await labels.create_labels(c, [free()] * 21)
        with pytest.raises(ValueError, match="does not exist"):
            await labels.create_labels(c, [label(element_guid=MISSING)], 19723)
        with pytest.raises(ValueError, match="story 4"):
            await labels.create_labels(c, [free(floor_index=4)], 19723)
    assert "CreateLabels" not in fake.tapir_calls
    error = {"error": {"code": -1, "message": "Failed to create label."}}
    fake = model(create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(labels.create_labels, c, [free(), label()])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_label_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(labels.create_labels, c, [free()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateLabels") == 1


async def test_apply_requires_explicit_port_and_journal(monkeypatch):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.set_classifications(c, [change()])
        with pytest.raises(ValueError, match="explicit port"):
            await classifications.set_classifications(
                c, [change()], None, False, preview["confirmation_token"]
            )

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(labels.create_labels, c, [free()])
    assert "API.SetClassificationsOfElements" not in fake.calls
    assert "CreateLabels" not in fake.tapir_calls
