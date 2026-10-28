import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import revisions
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ELEMENT = "11111111-1111-1111-1111-111111111111"
LAYOUT = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
MISSING = "DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD"


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_revision_lists_are_read_only():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        revisions_result = await revisions.list_document_revisions(api, 19723)
        issues_result = await revisions.list_revision_issues(api, 19723)
    assert revisions_result["documentRevisions"][0]["status"] == "Actual"
    assert issues_result["revisionIssues"][0]["isIssued"] is True
    assert fake.tapir_calls == ["GetDocumentRevisions", "GetRevisionIssues"]


async def test_revision_changes_use_exact_element_and_database_wrappers():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await revisions.get_revision_changes(
            api, [ELEMENT, MISSING], [LAYOUT, MISSING], 19723
        )
    assert "revisionChanges" in result
    assert "error" in result["revisionChangesOfElements"][1]
    assert "error" in result["currentRevisionChangesOfLayouts"][1]
    assert fake.tapir_requests[-2]["parameters"]["elements"][0] == {"elementId": {"guid": ELEMENT}}
    assert fake.tapir_requests[-1]["parameters"]["layoutDatabaseIds"][0] == {
        "databaseId": {"guid": LAYOUT}
    }


@pytest.mark.parametrize("values", [[], [ELEMENT] * 101, ["bad"]])
async def test_revision_changes_reject_invalid_guid_lists(values):
    async with client(FakeArchicad(19723)) as api:
        with pytest.raises((ValueError, TypeError)):
            await revisions.get_revision_changes(api, element_guids=values, port=19723)
