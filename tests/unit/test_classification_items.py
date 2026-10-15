"""Classification creation from Tapir 1.7.0 source; simulated, never a live capture."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import classifications
from tests.unit.fake_archicad import FakeArchicad, _classification_creation_parent, fake_transport

pytestmark = pytest.mark.anyio
SYSTEM = "1C4E9A10-3B7F-4D2A-9E61-0A5B7C3D2E11"
OTHER_SYSTEM = "6A2D8F44-91C3-4B55-8E07-2F6C1B9D4A22"
PARENT = "A1000000-0000-4000-8000-000000000003"
OTHER_PARENT = "A1000000-0000-4000-8000-000000000001"
FOREIGN_PARENT = "B2000000-0000-4000-8000-000000000001"
FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_classification_items_documented.json"
    ).read_text()
)


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def entry(**changes):
    return {
        "system_guid": SYSTEM,
        "parent_guid": PARENT,
        "id": "LAB-01",
        "name": "LAB item",
        "description": "Review",
        **changes,
    }


def roots(fake):
    return fake.classification_data["items"][SYSTEM]["classificationItems"]


async def apply(c, entries):
    preview = await classifications.create_classification_items(c, entries, 19723)
    return await classifications.create_classification_items(
        c, entries, 19723, False, preview["confirmation_token"]
    )


async def test_preview_apply_native_empty_results_readback_and_receipts():
    fake = FakeArchicad(19723)
    entries = [entry(), entry(id="LAB-02", parent_guid=OTHER_PARENT)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.create_classification_items(c, entries)
        assert preview["dry_run"] and "CreateClassificationItems" not in fake.tapir_calls
        token = preview["confirmation_token"]
        result = await classifications.create_classification_items(c, entries, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await classifications.create_classification_items(c, entries, 19723, False, token)
        readback = await classifications.list_classifications(c, SYSTEM, 19723)
    assert result["status"] == "verified"
    assert result["items"][0]["write_response"] == FIXTURE["success"]
    assert result["items"][0]["parameters"] == FIXTURE["parameters"]
    assert len({i["classification_item_guid"] for i in result["items"]}) == 2
    assert all(i["classification_item_receipt_id"] for i in result["items"])
    added = next(r for r in readback["items"] if r["id"] == "LAB-01")
    assert added["parent_guid"] == PARENT and added["description"] == "Review"
    saved = json.loads(Path(result["receipt_path"]).read_text())
    assert saved["counts"]["verified"] == 2
    assert not any(
        n.startswith(("Save", "Delete", "CreateClassificationSystems")) for n in fake.tapir_calls
    )


async def test_project_change_between_classification_items_stops_remaining_writes():
    """A copied PLN may retain classification GUIDs, so the project must still match."""
    fake = FakeArchicad(19723)
    base = fake_transport(fake)
    writes = 0

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if command == "CreateClassificationItems":
            writes += 1
        response = base.handle_request(request)
        if body.get("command") == "API.GetAllClassificationsInSystem" and writes == 1:
            fake.project_name = "Copied project"
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as client:
        result = await apply(client, [entry(), entry(id="LAB-02")])

    assert result["items"][0]["status"] == "verified"
    assert result["items"][1]["not_attempted"]
    assert "context changed" in result["context_error"]
    assert writes == 1


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [entry()] * 51,
        [entry(id="")],
        [entry(name=" ")],
        [entry(id=" X ")],
        [entry(system_guid="bad")],
        [entry(parent_guid="00000000-0000-0000-0000-000000000000")],
        [entry(children=[])],
        [entry(name=1)],
        [entry(description=None)],
    ],
)
async def test_invalid_input_before_network(entries):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await classifications.create_classification_items(c, entries)
    assert not fake.calls


@pytest.mark.parametrize(
    "entries",
    [
        [entry(system_guid="11111111-1111-4111-8111-111111111111")],
        [entry(parent_guid=FOREIGN_PARENT)],
        [entry(id="Parede")],
        [entry(id="parede")],
        [entry(), entry(parent_guid=OTHER_PARENT)],
        [entry(), entry(id="lab-01")],
    ],
)
async def test_system_parent_and_duplicate_id_refusals(entries):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await classifications.create_classification_items(c, entries)
    assert "CreateClassificationItems" not in fake.tapir_calls


async def test_same_id_in_different_systems_and_maximum_batch():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, [entry(), entry(system_guid=OTHER_SYSTEM, parent_guid=FOREIGN_PARENT)]
        )
        assert result["status"] == "verified"
        result = await apply(c, [entry(id=f"BATCH-{i}") for i in range(50)])
    assert result["counts"]["verified"] == 50


@pytest.mark.parametrize("fault", ["id", "parent", "tree", "project", "port"])
async def test_stale_preview_and_explicit_port(fault):
    fake = FakeArchicad(19723)
    data = [entry()]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await classifications.create_classification_items(c, data, 19723)
        if fault == "id":
            data[0]["id"] = "Changed"
        elif fault == "parent":
            data[0]["parent_guid"] = OTHER_PARENT
        elif fault == "tree":
            _classification_creation_parent(roots(fake), PARENT)["name"] = "Changed"
        elif fault == "project":
            fake.project_name = "Other"
        with pytest.raises(ValueError, match="explicit port" if fault == "port" else "changed"):
            await classifications.create_classification_items(
                c, data, None if fault == "port" else 19723, False, preview["confirmation_token"]
            )
    assert "CreateClassificationItems" not in fake.tapir_calls


@pytest.mark.parametrize(
    "fault",
    [
        "lost",
        "malformed",
        "native_error",
        "ignored",
        "wrong_name",
        "wrong_id",
        "wrong_description",
        "wrong_parent",
        "old_changed",
        "read_lost",
    ],
)
async def test_dispatch_faults_and_independent_tree_verification(fault):
    fake = FakeArchicad(19723)
    base = fake_transport(fake)
    writes = 0

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CreateClassificationItems":
            writes += 1
            if fault == "native_error":
                return httpx.Response(
                    200,
                    json={"succeeded": True, "result": {"addOnCommandResponse": FIXTURE["failed"]}},
                )
        response = base.handle_request(request)
        if cmd == "CreateClassificationItems":
            if fault == "lost":
                raise httpx.ReadTimeout("Lost", request=request)
            if fault == "malformed":
                return httpx.Response(
                    200, json={"succeeded": True, "result": {"addOnCommandResponse": {}}}
                )
            parent = _classification_creation_parent(roots(fake), PARENT)
            row = parent["children"][-1]["classificationItem"]
            if fault == "ignored":
                parent["children"].pop()
            elif fault.startswith("wrong_") and fault != "wrong_parent":
                row[fault.removeprefix("wrong_")] = "Wrong"
            elif fault == "wrong_parent":
                moved = parent["children"].pop()
                _classification_creation_parent(roots(fake), OTHER_PARENT).setdefault(
                    "children", []
                ).append(moved)
            elif fault == "old_changed":
                parent["description"] = "Changed"
        if (
            body.get("command") == "API.GetAllClassificationsInSystem"
            and writes
            and fault == "read_lost"
        ):
            raise httpx.ReadTimeout("Read lost", request=request)
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [entry(), entry(id="LAB-02")])
    first, second = result["items"]
    if fault in ("lost", "malformed"):
        assert first["status"] == "unknown" and second["not_attempted"] and writes == 1
    elif fault == "read_lost":
        assert first["status"] == "unverified" and second["not_attempted"] and writes == 1
    elif fault == "native_error":
        assert all(i["status"] == "failed" for i in result["items"])
    else:
        assert first["status"] == "verification_failed"
        assert second["not_attempted"] and writes == 1
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("fault", ["missing_description", "duplicate_guid", "children_error"])
async def test_malformed_inventory_refused_before_write(fault):
    fake = FakeArchicad(19723)
    first = roots(fake)[0]["classificationItem"]
    if fault == "missing_description":
        first.pop("description")
    elif fault == "duplicate_guid":
        roots(fake).append(deepcopy(roots(fake)[0]))
    else:
        first["children"] = {"error": {"code": 1}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Malformed"):
            await classifications.create_classification_items(c, [entry()])
    assert "CreateClassificationItems" not in fake.tapir_calls
