import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import locks, zones
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
ZONE = "33333333-3333-4333-8333-333333333333"
MISSING = "99999999-9999-4999-8999-999999999999"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    types = {WALL: "Wall", SLAB: "Slab", ZONE: "Zone"}
    return FakeArchicad(
        19723,
        elements=dict(types),
        details={
            g: {"type": t, "floorIndex": 0, "layerIndex": 1, "details": {}}
            for g, t in types.items()
        },
        layers={1: "Walls", 2: "Travada"},
        **kwargs,
    )


async def apply(tool, c, guids):
    preview = await tool(c, guids, 19723)
    return await tool(c, guids, 19723, False, preview["confirmation_token"])


async def test_lock_then_unlock():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await locks.lock_elements(c, [WALL.lower(), SLAB], 19723)
        assert "LockElements" not in fake.tapir_calls
        assert preview["items"][0]["element_guid"] == WALL
        assert preview["items"][0]["layerName"] == "Walls"
        token = preview["confirmation_token"]
        locked = await locks.lock_elements(c, [WALL, SLAB], 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await locks.lock_elements(c, [WALL, SLAB], 19723, False, token)
        assert fake.locked_elements == {WALL, SLAB}
        unlocked = await apply(locks.unlock_elements, c, [WALL])
    assert locked["status"] == "verified"
    assert [i["editable_after"] for i in locked["items"]] == [False, False]
    assert all(i["lock_receipt_id"] for i in locked["items"])
    assert unlocked["status"] == "verified" and fake.locked_elements == {SLAB}
    request = next(r for r in fake.tapir_requests if r["command"] == "LockElements")
    assert request["parameters"] == {
        "elements": [{"elementId": {"guid": WALL}}, {"elementId": {"guid": SLAB}}]
    }


async def test_lock_and_unlock_refusals():
    fake = model(locked_elements={SLAB})
    fake.details[ZONE]["layerIndex"] = 2
    fake.layer_flags[2] = {"isLocked": True}
    fake.details[WALL]["hotlinkId"] = {"guid": MISSING}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Locked/non-editable"):
            await locks.lock_elements(c, [SLAB])
        with pytest.raises(ValueError, match="hotlink"):
            await locks.lock_elements(c, [WALL])
        with pytest.raises(ValueError, match="does not exist"):
            await locks.lock_elements(c, [MISSING])
        with pytest.raises(ValueError, match="hotlink"):
            await locks.unlock_elements(c, [WALL])
        with pytest.raises(ValueError, match="locked layer"):
            await locks.unlock_elements(c, [ZONE])
        with pytest.raises(ValueError, match="does not exist"):
            await locks.unlock_elements(c, [MISSING])
        for bad in ([], [SLAB, SLAB.lower()], ["not-a-guid"]):
            with pytest.raises(ValueError):
                await locks.lock_elements(c, bad)
        with pytest.raises(ValueError):
            await locks.lock_elements(c, [str(i) for i in range(101)])
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already editable"):
            await locks.unlock_elements(c, [WALL])
    assert not {"LockElements", "UnlockElements"} & set(fake.tapir_calls)


async def test_lock_failed_ignored_and_lost():
    fake = model(lock_refused=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(locks.lock_elements, c, [WALL])
    assert result["items"][0]["status"] == "failed"
    assert result["items"][0]["error"]["message"] == "Failed to lock elements."
    fake = model(lock_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(locks.lock_elements, c, [WALL])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["status"] == "needs_review"
    fake = model(lose_lock_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(locks.lock_elements, c, [WALL, SLAB])
        preview = await locks.lock_elements(c, [ZONE])
        with pytest.raises(ValueError, match="explicit port"):
            await locks.lock_elements(c, [ZONE], None, False, preview["confirmation_token"])
    assert [i["status"] for i in result["items"]] == ["unknown", "unknown"]
    assert fake.tapir_calls.count("LockElements") == 1


async def test_lock_reported_failed_but_partly_applied():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await locks.lock_elements(c, [WALL, SLAB], 19723)
        original = fake._tapir

        def partial(params):
            if params["addOnCommandId"]["commandName"] == "LockElements":
                fake.locked_elements.add(WALL)
                fake.lock_refused = True
            return original(params)

        fake._tapir = partial
        result = await locks.lock_elements(
            c, [WALL, SLAB], 19723, False, preview["confirmation_token"]
        )
    assert [i["status"] for i in result["items"]] == ["unknown", "failed"]


async def test_lock_plan_changed_since_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await locks.lock_elements(c, [WALL], 19723)
        fake.details[WALL]["layerIndex"] = 2
        with pytest.raises(ValueError, match="changed since preview"):
            await locks.lock_elements(c, [WALL], 19723, False, preview["confirmation_token"])
    assert "LockElements" not in fake.tapir_calls


async def test_update_zones_preview_then_apply():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await zones.update_zones(c, 19723, undo_top_trim=True)
        assert "UpdateZones" not in fake.tapir_calls
        assert preview["items"][0]["zone_count"] == 1
        token = preview["confirmation_token"]
        result = await zones.update_zones(
            c, 19723, undo_top_trim=True, dry_run=False, confirmation_token=token
        )
        with pytest.raises(ValueError, match="consumed"):
            await zones.update_zones(
                c, 19723, undo_top_trim=True, dry_run=False, confirmation_token=token
            )
    assert fake.zone_updates == [
        {"keepStampPosition": True, "undoTopTrim": True, "undoBottomTrim": False}
    ]
    item = result["items"][0]
    assert item["status"] == "unverified" and item["zone_count_after"] == 1
    assert result["status"] == "needs_review" and item["zone_update_receipt_id"]


async def test_update_zones_refusals_and_outcomes():
    fake = model()
    del fake.elements[ZONE]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="no zones"):
            await zones.update_zones(c, 19723)
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await zones.update_zones(c, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await zones.update_zones(
                c, None, dry_run=False, confirmation_token=preview["confirmation_token"]
            )
        with pytest.raises(ValueError, match="changed since preview"):
            await zones.update_zones(
                c,
                19723,
                keep_stamp_position=False,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )
    assert "UpdateZones" not in fake.tapir_calls
    for flag, status in (
        ("zone_update_refused", "failed"),
        ("lose_zone_update_response", "unknown"),
    ):
        fake = model(**{flag: True})
        async with ArchicadClient(transport=fake_transport(fake)) as c:
            preview = await zones.update_zones(c, 19723)
            result = await zones.update_zones(
                c, 19723, dry_run=False, confirmation_token=preview["confirmation_token"]
            )
        assert result["items"][0]["status"] == status
