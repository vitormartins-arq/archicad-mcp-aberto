import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import project_resources
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
BAD = "22222222-2222-2222-2222-222222222222"


async def test_project_resource_reads():
    fake = FakeArchicad(19723, project_resources_fixture=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        dims = await project_resources.get_dimension_data(c, [GUID, BAD], 19723)
        mvo = await project_resources.get_model_view_options(c, 19723)
        libs = await project_resources.list_libraries(c, ["Application", "Temporary"], 19723)
    assert "error" in dims["dimensionsData"][1]
    assert mvo["modelViewOptions"][0]["name"] == "Construction Document"
    assert len(libs["specialFolders"]) == 2


async def test_dimension_limit_and_folder_enum():
    async with ArchicadClient(
        transport=fake_transport(FakeArchicad(19723, project_resources_fixture=True))
    ) as c:
        with pytest.raises(ValueError):
            await project_resources.get_dimension_data(c, [], 19723)
        with pytest.raises(ValueError):
            await project_resources.list_libraries(c, ["Nope"], 19723)
