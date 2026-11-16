import pytest

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import overrides, renames
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
RULE_DEMOLIR = "B0000000-0000-0000-0000-000000000001"
BUILT_IN = "C0000000-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, **request):
    preview = await renames.rename_items(c, port=19723, **request)
    result = await renames.rename_items(
        c, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"], **request
    )
    return preview, result


async def test_list_graphic_overrides_resolves_names():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        listed = await overrides.list_graphic_overrides(c, 19723)
    assert fake.own_addon_calls == ["GetGraphicOverrides"]
    assert listed["rule_groups"][0] == {
        "guid": "A0000000-0000-0000-0000-000000000001",
        "name": "LAB - Executivo",
        "rules": ["Paredes - Demolir", "Paredes - Construir"],
    }
    assert listed["rules"][2]["rule_group"] == "Renovation"
    assert listed["combinations"][0]["rules"] == ["Paredes - Demolir", "Paredes - Construir"]
    assert listed["current_combination"] == "Demolir e Construir"


async def test_list_renovation_filters():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        listed = await overrides.list_renovation_filters(c, 19723)
    assert listed["count"] == 3
    assert listed["current_filter"] == "03 New Construction"
    assert "cannot be renamed" in listed["note"]


async def test_missing_addon_is_explained():
    fake = FakeArchicad(19723, own_addon_loaded=False)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(AddOnError, match="add-on is not loaded"):
            await overrides.list_renovation_filters(c, 19723)


async def test_rename_rules_find_replace_and_read_back():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, kind="override_rules", find="Paredes - ", replace="PAR | ")
    assert [i["where"] for i in preview["items"]] == ["LAB - Executivo"] * 2
    assert result["status"] == "verified"
    sent = next(r for r in fake.own_addon_requests if r["command"] == "RenameGraphicOverrides")
    assert sent["parameters"]["renames"][0] == {
        "type": "rule",
        "guid": RULE_DEMOLIR,
        "newName": "PAR | Demolir",
    }
    assert [r["name"] for r in fake.override_rules[:2]] == ["PAR | Demolir", "PAR | Construir"]


async def test_rename_rule_groups_and_combinations_by_exact_name():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, groups = await apply(
            c, kind="override_rule_groups", renames=[{"old": "LAB - Executivo", "new": "01 LAB"}]
        )
        _, combos = await apply(
            c,
            kind="override_combinations",
            renames=[{"old": "Demolir e Construir", "new": "DM - Demolir e construir"}],
        )
    assert groups["status"] == "verified" and combos["status"] == "verified"
    assert fake.override_groups[0]["name"] == "01 LAB"
    # A combination keeps its rules: only the name is sent.
    assert fake.override_combinations[0]["ruleGuids"] == [
        RULE_DEMOLIR,
        "B0000000-0000-0000-0000-000000000002",
    ]


async def test_rule_names_clash_only_within_their_folder():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Two override_rules"):
            await renames.rename_items(
                c,
                kind="override_rules",
                renames=[{"old": "Paredes - Demolir", "new": "Paredes - Construir"}],
                port=19723,
            )
        # Same name as a rule of another folder is fine.
        preview = await renames.rename_items(
            c,
            kind="override_rules",
            renames=[{"old": "Paredes - Demolir", "new": "Demolition"}],
            port=19723,
        )
    assert preview["items"][0]["after_name"] == {"name": "Demolition"}


async def test_built_in_refused_and_ignored_rename_detected():
    fake = FakeArchicad(19723, override_rename_ignored={RULE_DEMOLIR})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, combos = await apply(
            c, kind="override_combinations", renames=[{"old": "No Overrides", "new": "Nenhuma"}]
        )
        _, rules = await apply(
            c, kind="override_rules", renames=[{"old": "Paredes - Demolir", "new": "PAR"}]
        )
    (item,) = combos["items"]
    assert item["status"] == "failed" and "Built-in" in item["error"]["message"]
    (item,) = rules["items"]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["name"]


async def test_refused_rename_call_fails_cleanly():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await renames.rename_items(
            c, kind="override_rule_groups", find="LAB", replace="ARQ", port=19723
        )
        fake.own_addon_errors.add("RenameGraphicOverrides")
        result = await renames.rename_items(
            c,
            kind="override_rule_groups",
            find="LAB",
            replace="ARQ",
            port=19723,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
        )
    assert {i["status"] for i in result["items"]} == {"failed"}
    assert "warning" not in result
