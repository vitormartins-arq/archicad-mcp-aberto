"""list_schedules joins Project Map schedules, saved views and layout drawings."""

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import schedules
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

G = "00000000-0000-4000-8000-{:012d}".format


def node(n, name, kind, children=(), source=None, prefix=""):
    item = {"navigatorItemId": {"guid": G(n)}, "name": name, "type": kind, "prefix": prefix}
    if source is not None:
        item["sourceNavigatorItemId"] = {"guid": G(source)}
    if children:
        item["children"] = [{"navigatorItem": c} for c in children]
    return item


def trees():
    project = node(
        1,
        "Projeto",
        "ProjectItem",
        [
            node(
                2,
                "Mapas",
                "FolderItem",
                [
                    node(3, "Portas", "ScheduleItem", source=900),
                    node(4, "Paredes", "ScheduleItem", source=901),
                ],
            )
        ],
    )
    views = node(
        10,
        "Mapa",
        "UndefinedItem",
        [
            node(
                11,
                "Tabelas",
                "FolderItem",
                [
                    node(12, "Portas", "ScheduleItem", source=900),
                    node(13, "Portas (cópia)", "ScheduleItem", source=900),
                ],
            )
        ],
    )
    book = node(
        20,
        "Livro",
        "BookItem",
        [
            node(
                21,
                "Executivo",
                "SubsetItem",
                [
                    node(
                        22,
                        "Planta",
                        "LayoutItem",
                        [node(23, "Portas", "DrawingItem", source=12)],
                        prefix="03.01",
                    ),
                    node(
                        24,
                        "Memorial",
                        "LayoutItem",
                        [node(25, "Portas", "DrawingItem", source=13)],
                        prefix="03.02",
                    ),
                ],
                prefix="03",
            )
        ],
    )
    return {"ProjectMap": project, "PublicViewMap": views, "LayoutBook": book}


async def run(**kwargs):
    fake = FakeArchicad(19723)
    fake.navigator_trees.update(trees())
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        return await schedules.list_schedules(c, 19723, **kwargs)


async def test_schedule_folder_views_and_layouts():
    result = await run()
    assert result["total"] == 2 and result["on_layouts"] == 1
    doors, walls = result["schedules"]
    assert doors["name"] == "Portas" and doors["folder"] == "Mapas"
    assert doors["scheme_guid"] == G(900)
    assert [v["name"] for v in doors["views"]] == ["Portas", "Portas (cópia)"]
    assert doors["views"][0]["folder"] == "Tabelas"
    assert [p["layout"] for p in doors["layouts"]] == ["03.01 Planta", "03.02 Memorial"]
    assert doors["layouts"][0]["subset"] == "03 Executivo"
    assert walls["views"] == [] and walls["layouts"] == []


async def test_query_and_only_on_layouts():
    assert [s["name"] for s in (await run(query="pared"))["schedules"]] == ["Paredes"]
    assert [s["name"] for s in (await run(only_on_layouts=True))["schedules"]] == ["Portas"]
