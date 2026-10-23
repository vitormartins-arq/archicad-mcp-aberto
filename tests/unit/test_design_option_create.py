"""create_design_options (Tapir 1.7.0, Archicad 29+), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import design_option_create as tool
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
BRICK = "20000000-0000-4000-8000-000000000001"  # existing option F-01 in set "Facade"
STUDY = {
    "sets": ["Layout"],
    "options": [
        {"name": "Cozinha aberta", "id": "L-01", "set": "Layout"},
        {"name": "Cozinha fechada", "id": "L-02", "set": "Layout"},
        {"name": "Concreto", "id": "F-03", "set": "Facade"},
    ],
    "combinations": [{"name": "Aberta com tijolo", "options": ["L-01", "F-01"]}],
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, **kwargs):
    preview = await tool.create_design_options(c, port=19723, **kwargs)
    result = await tool.create_design_options(
        c, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"], **kwargs
    )
    return preview, result


async def test_sets_options_and_combination_in_one_call():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, **STUDY)
    assert [i["kind"] for i in preview["items"]] == ["set", "option", "option", "option",
                                                     "combination"]  # fmt: skip
    commands = [r["command"] for r in fake.tapir_requests if r["command"].startswith("Create")]
    assert commands == [
        "CreateDesignOptionSets",
        "CreateDesignOptions",
        "CreateDesignOptionCombinations",
    ]
    assert result["status"] == "verified"
    new_option = next(o for o in fake.do_options if o["id"] == "L-01")["designOptionId"]["guid"]
    request = next(
        r for r in fake.tapir_requests if r["command"] == "CreateDesignOptionCombinations"
    )
    assert request["parameters"] == {
        "designOptionCombinations": [
            {
                "name": "Aberta com tijolo",
                "activeDesignOptions": [
                    {"designOptionId": {"guid": new_option}},
                    {"designOptionId": {"guid": BRICK}},
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sets": ["Facade"]}, "already exists"),
        ({"options": [{"name": "X", "id": "F-01", "set": "Facade"}]}, "id 'F-01' already"),
        ({"options": [{"name": "X", "id": "X-1", "set": "facade"}]}, "case-sensitive"),
        ({"combinations": [{"name": "brick scheme", "options": []}]}, "already exists"),
        ({"combinations": [{"name": "Nova", "options": ["Z-9"]}]}, "no design option"),
        ({"sets": ["A", "a"]}, "twice"),
    ],
)
async def test_preview_refuses_existing_or_unknown(kwargs, message):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await tool.create_design_options(c, port=19723, **kwargs)
    assert not any(r["command"].startswith("Create") for r in fake.tapir_requests)


async def test_failed_option_fails_its_combination():
    fake = FakeArchicad(
        19723, design_option_errors={"Cozinha aberta": {"code": -1, "message": "No"}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, **STUDY)
    assert [i["status"] for i in result["items"]] == [
        "verified", "failed", "verified", "verified", "failed"]  # fmt: skip
    assert result["items"][-1]["error"] == "One of its options was not created."


async def test_ignored_active_options_fail_verification():
    fake = FakeArchicad(19723, combination_drops_options=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, combinations=[{"name": "Só tijolo", "options": ["F-01"]}])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["active options"]


def test_bad_input_is_refused():
    with pytest.raises(ValidationError, match="at least one"):
        tool.DesignOptionsCreate.model_validate({})
    with pytest.raises(ValidationError):
        tool.OptionCreate.model_validate({"name": " X", "id": "1", "set": "S"})
    with pytest.raises(ValidationError):
        tool.DesignOptionsCreate.model_validate({"sets": [" Layout"]})
