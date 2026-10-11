import pytest

from archicad_mcp_aberto.connection import (
    AmbiguousTarget,
    ArchicadBusy,
    ArchicadClient,
    CommandNotRegistered,
    NoInstance,
    discover,
    ports_from_env,
    resolve_port,
)
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def test_no_instance():
    async with client() as c:
        assert await discover(c) == []
        with pytest.raises(NoInstance):
            await resolve_port(c, None)


async def test_single_instance_is_resolved_automatically():
    async with client(FakeArchicad(19724)) as c:
        assert await resolve_port(c, None) == 19724


async def test_several_instances_are_never_guessed():
    async with client(FakeArchicad(19723), FakeArchicad(19724)) as c:
        with pytest.raises(AmbiguousTarget):
            await resolve_port(c, None)
        assert await resolve_port(c, 19724) == 19724


async def test_discover_identifies_project_and_tapir():
    a = FakeArchicad(19723, project_name="WG Formosa_R02")
    b = FakeArchicad(19724, tapir_version=None)
    async with client(a, b) as c:
        found = {i["port"]: i for i in await discover(c)}
    assert found[19723]["project_name"] == "WG Formosa_R02"
    assert found[19723]["tapir_version"] == "1.7.0"
    assert found[19724]["tapir_loaded"] is False
    assert "project_name" not in found[19724]


async def test_busy_instance_stays_listed():
    async with client(FakeArchicad(19723, busy=True)) as c:
        found = await discover(c)
        assert found[0]["status"] == "busy"
        with pytest.raises(ArchicadBusy):
            await resolve_port(c, None)


async def test_missing_tapir_command_is_not_registered():
    async with client(FakeArchicad(19723, tapir_version=None)) as c:
        with pytest.raises(CommandNotRegistered):
            await c.tapir(19723, "GetStories")


async def test_port_outside_range_is_rejected():
    async with client(FakeArchicad(19723)) as c:
        with pytest.raises(ValueError):
            await c.command(8080, "GetProductInfo")


async def test_connection_is_reused():
    async with client(FakeArchicad(19723)) as c:
        first = c._http
        await c.command(19723, "GetProductInfo")
        await c.command(19723, "GetProductInfo")
        assert c._http is first


def test_ports_from_env():
    assert ports_from_env("19723-19725") == (19723, 19724, 19725)
    assert ports_from_env("19723, 19730") == (19723, 19730)
    assert ports_from_env("")[0] == 19723
