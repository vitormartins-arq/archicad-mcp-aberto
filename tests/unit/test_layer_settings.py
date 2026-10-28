"""Layer attributes/combination inventory against source-derived MockTransport only."""

import json
from copy import deepcopy

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import layer_settings, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport, layer_guid

pytestmark = pytest.mark.anyio
ERROR = {"error": {"code": -1, "message": "Failed to modify."}}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, layers={1: "Archicad", 2: "Editable", 3: "Other"}, **kwargs)


async def apply(c, changes):
    preview = await layer_settings.set_layer_settings(c, changes, 19723)
    return await layer_settings.set_layer_settings(
        c, changes, 19723, False, preview["confirmation_token"]
    )


async def test_combination_headers_filter_and_page_before_optional_details():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        headers = await layer_settings.list_layer_combinations(c, 19723)
        assert headers["total"] == 2 and all(
            "guid" in r and "layers" not in r for r in headers["items"]
        )
        assert "GetLayerCombinations" not in fake.tapir_calls
        detail = await layer_settings.list_layer_combinations(
            c, 19723, query="CADASTRO", include_layers=True
        )
        assert detail["total"] == 1 and detail["items"][0]["layers"][0]["attributeId"][
            "guid"
        ] == layer_guid(1)
        page = await layer_settings.list_layer_combinations(c, 19723, offset=1, limit=1)
        assert page["total"] == 2 and len(page["items"]) == 1
        empty = await layer_settings.list_layer_combinations(
            c, 19723, query="missing", include_layers=True
        )
        assert empty["total"] == 0 and not empty["items"]
    assert fake.tapir_calls.count("GetLayerCombinations") == 1


async def test_combination_details_keep_native_middle_error():
    fake = model(layer_combination_read_errors={2: ERROR})
    fake.layer_combinations[3] = {"name": "Third", "layers": {}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await layer_settings.list_layer_combinations(c, 19723, include_layers=True)
    assert len(result["items"]) == 3
    assert (
        "layers" in result["items"][0]
        and "error" in result["items"][1]
        and "layers" in result["items"][2]
    )


async def test_combination_details_chunked_after_pagination():
    fake = model()
    fake.layer_combinations = {i: {"name": f"C{i}", "layers": {}} for i in range(1, 207)}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await layer_settings.list_layer_combinations(
            c, 19723, offset=1, limit=205, include_layers=True
        )
    calls = [r for r in fake.tapir_requests if r["command"] == "GetLayerCombinations"]
    assert result["total"] == 206 and len(result["items"]) == 205
    assert [len(r["parameters"]["attributes"]) for r in calls] == [100, 100, 5]


@pytest.mark.parametrize("args", [{"offset": -1}, {"limit": 0}, {"limit": 501}, {"offset": True}])
async def test_invalid_combination_page_before_network(args):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await layer_settings.list_layer_combinations(c, **args)
    assert not fake.calls


async def test_flags_apply_preserve_identity_name_and_unspecified_flags():
    fake = model(
        layer_flags={
            2: {"isHidden": True, "isLocked": True, "isWireframe": True, "intersectionGroupNr": 8}
        }
    )
    changes = [{"layer": "Editable", "hidden": False, "locked": False}]
    before = deepcopy(fake.layers)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layer_settings.set_layer_settings(c, changes, 19723)
        assert "CreateLayers" not in fake.tapir_calls
        assert preview["items"][0]["before"]["isHidden"] is True
        result = await layer_settings.set_layer_settings(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await layer_settings.set_layer_settings(
                c, changes, 19723, False, preview["confirmation_token"]
            )
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["layer_settings_receipt_id"] and item["layer_guid"] == layer_guid(2)
    assert item["after"] == {
        "attributeId": {"guid": layer_guid(2)},
        "index": 2,
        "name": "Editable",
        "isHidden": False,
        "isLocked": False,
        "isWireframe": True,
        "intersectionGroupNr": 8,
    }
    assert fake.layers == before
    assert "Do not rely on Undo" in result["note"]
    assert next(r["parameters"] for r in fake.tapir_requests if r["command"] == "CreateLayers") == {
        "layerDataArray": [
            {
                "attributeId": {"guid": layer_guid(2)},
                "name": "Editable",
                "isHidden": False,
                "isLocked": False,
            }
        ],
        "overwriteExisting": True,
    }


async def test_layer_guid_and_zero_intersection_group_supported():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, [{"layer": layer_guid(2).lower(), "intersection_group": 0, "wireframe": True}]
        )
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["intersectionGroupNr"] == 0
    assert result["items"][0]["after"]["isWireframe"] is True


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"layer": "Editable"}],
        [{"layer": " ", "hidden": True}],
        [{"layer": "Editable", "hidden": 1}],
        [{"layer": "Editable", "intersection_group": -1}],
        [{"layer": "Editable", "intersection_group": 32768}],
        [{"layer": "Editable", "name": "Renamed"}],
        [{"layer": "Editable", "locked": True}] * 51,
    ],
)
async def test_invalid_changes_before_network(entries):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await layer_settings.set_layer_settings(c, entries)
    assert not fake.calls


@pytest.mark.parametrize(
    "entries, reason",
    [
        ([{"layer": "Archicad", "hidden": True}], "protected"),
        ([{"layer": "missing", "hidden": True}], "does not exist"),
        (
            [{"layer": "Editable", "hidden": True}, {"layer": layer_guid(2), "locked": True}],
            "only once",
        ),
    ],
)
async def test_missing_protected_and_alias_duplicate_layers_refused(entries, reason):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=reason):
            await layer_settings.set_layer_settings(c, entries, 19723)
    assert "CreateLayers" not in fake.tapir_calls


async def test_ambiguous_name_refused_but_existing_guid_identifies_layer():
    fake = model()
    fake.layers[3] = "editable"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="ambiguous"):
            await layer_settings.set_layer_settings(
                c, [{"layer": "Editable", "locked": True}], 19723
            )
        result = await apply(c, [{"layer": layer_guid(2), "locked": True}])
    assert result["status"] == "verified" and fake.layer_flags[2]["isLocked"] is True


async def test_partial_error_and_ignored_change():
    fake = model(layer_settings_errors={1: ERROR})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, [{"layer": "Editable", "locked": True}, {"layer": "Other", "locked": True}]
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    fake = model(layer_settings_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"layer": "Editable", "locked": True}])
    assert result["items"][0]["status"] == "verification_failed"


async def test_changed_flags_and_apply_port_guards():
    fake = model()
    changes = [{"layer": "Editable", "locked": True}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layer_settings.set_layer_settings(c, changes, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await layer_settings.set_layer_settings(
                c, changes, None, False, preview["confirmation_token"]
            )
        fake.layer_flags[2] = {"isWireframe": True}
        with pytest.raises(ValueError, match="changed"):
            await layer_settings.set_layer_settings(
                c, changes, 19723, False, preview["confirmation_token"]
            )
    assert "CreateLayers" not in fake.tapir_calls


async def test_lost_response_does_not_retry():
    fake = model(lose_layer_settings_response=True)
    changes = [{"layer": "Editable", "locked": True}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layer_settings.set_layer_settings(c, changes, 19723)
        result = await layer_settings.set_layer_settings(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await layer_settings.set_layer_settings(
                c, changes, 19723, False, preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown" and fake.tapir_calls.count("CreateLayers") == 1


async def test_disappearing_attribute_can_be_created_by_native_base_but_never_verified_as_target():
    fake = model()

    def handler(request):
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CreateLayers":
            fake.layers.pop(2)
        return httpx.Response(200, json=fake.handle(body))

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [{"layer": "Editable", "locked": True}])
    assert result["items"][0]["status"] == "unknown"
    assert "unexpected layer GUID" in result["items"][0]["error"]
    assert result["items"][0]["write_response"]["attributeId"]["guid"] == layer_guid(4)


@pytest.mark.parametrize("bad", [None, "bad", {}, {"guid": "bad"}])
async def test_malformed_attribute_id_is_unknown_not_exception_after_write(bad):
    fake = model()

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CreateLayers":
            response["result"]["addOnCommandResponse"] = {"attributeIds": [{"attributeId": bad}]}
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [{"layer": "Editable", "locked": True}])
    assert result["items"][0]["status"] == "unknown" and result["receipt_path"]


async def test_receipt_failure_prevents_dispatch(monkeypatch):
    fake = model()
    changes = [{"layer": "Editable", "locked": True}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layer_settings.set_layer_settings(c, changes, 19723)

        def denied(*args):
            raise OSError("No receipt")

        monkeypatch.setattr(write, "_journal", denied)
        with pytest.raises(OSError, match="No receipt"):
            await layer_settings.set_layer_settings(
                c, changes, 19723, False, preview["confirmation_token"]
            )
    assert "CreateLayers" not in fake.tapir_calls


async def test_shared_timeout_applies_to_write_and_layer_readback(monkeypatch):
    fake = model()
    seen = []

    class TimedClient(ArchicadClient):
        async def tapir(self, port, name, parameters=None, *, timeout=None):
            if timeout is not None:
                seen.append((name, timeout))
            return await super().tapir(port, name, parameters, timeout=timeout)

    monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", "45")
    async with TimedClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"layer": "Editable", "locked": True}])
    assert (
        result["status"] == "verified"
        and ("CreateLayers", 45) in seen
        and ("GetLayers", 45) in seen
    )


async def test_create_layer_combinations_preview_apply_and_verify():
    fake = model()
    data = [
        {
            "name": "Presentation",
            "layers": [
                {
                    "layer": "Editable",
                    "visible": False,
                    "locked": True,
                    "wireframe": True,
                    "intersection_group": 7,
                }
            ],
        }
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layer_settings.create_layer_combinations(c, data, 19723)
        assert "CreateLayerCombinations" not in fake.tapir_calls
        result = await layer_settings.create_layer_combinations(
            c, data, 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verified"
    sent = next(row for row in fake.tapir_requests if row["command"] == "CreateLayerCombinations")
    assert sent["parameters"]["layerCombinationDataArray"][0]["layers"][0]["isHidden"] is True
    assert sent["parameters"].get("overwriteExisting") is None


async def test_create_layer_combinations_refuses_existing_name_and_missing_layer():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="already exists"):
            await layer_settings.create_layer_combinations(
                c,
                [{"name": "1ª ETAPA | CADASTRO", "layers": [{"layer": "Editable"}]}],
                19723,
            )
        with pytest.raises(ValueError, match="does not exist"):
            await layer_settings.create_layer_combinations(
                c, [{"name": "New", "layers": [{"layer": "Missing"}]}], 19723
            )


async def test_create_layer_combinations_limit():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError):
            await layer_settings.create_layer_combinations(c, [], 19723)
        with pytest.raises(ValueError):
            await layer_settings.create_layer_combinations(
                c, [{"name": f"C{i}", "layers": [{"layer": "Editable"}]} for i in range(21)], 19723
            )
