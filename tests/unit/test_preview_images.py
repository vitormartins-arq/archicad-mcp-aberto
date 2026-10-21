import pytest
from mcp.types import ImageContent, TextContent

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import preview_images
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"


async def test_preview_tools_return_mcp_image_content():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        element = await preview_images.get_element_preview(c, [GUID], port=19723)
        zone = await preview_images.get_zone_image(c, [GUID], port=19723)
        favorite = await preview_images.get_favorite_preview(c, ["Wall"], port=19723)
    for response in (element, zone, favorite):
        result = response["content"]
        converted = [
            item.to_image_content() if hasattr(item, "to_image_content") else item
            for item in result
        ]
        assert isinstance(converted[0], TextContent) and isinstance(converted[1], ImageContent)
        assert converted[1].mimeType == "image/png"
    assert fake.tapir_requests[0]["parameters"]["format"] == "png"


@pytest.mark.parametrize("count", [0, 11])
async def test_preview_limit(count):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError):
            await preview_images.get_element_preview(c, [GUID] * count, port=19723)


async def test_preview_size_limit():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError):
            await preview_images.get_element_preview(c, [GUID], width=2048, port=19723)
