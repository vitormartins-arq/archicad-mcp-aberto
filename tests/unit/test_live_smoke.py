"""Smoke runner tests. All HTTP requests go to the fake Archicad, never localhost."""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from tests.live import smoke
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport, ok

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"


@dataclass
class SmokeFake(FakeArchicad):
    untitled: object = True
    boxes: dict = field(default_factory=dict)
    fail_boxes: bool = False
    become_named_after_walls: bool = False

    def _tapir(self, params):
        response = super()._tapir(params)
        name = params["addOnCommandId"]["commandName"]
        if name == "GetProjectInfo":
            response["result"]["addOnCommandResponse"]["isUntitled"] = self.untitled
        if name == "CreateWalls" and self.become_named_after_walls:
            self.untitled = False
        return response

    def handle(self, body):
        if body["command"] == "API.Get2DBoundingBoxes":
            self.calls.append(body["command"])
            # Graphisoft official wrapper/documentation-derived format, not a live capture:
            # https://archicadapi.graphisoft.com/archicadPythonPackage/archicad.html
            rows = [
                {"error": {"code": 1, "message": "No bounds"}}
                if self.fail_boxes
                else {"boundingBox2D": deepcopy(self.boxes[e["elementId"]["guid"]])}
                for e in body["parameters"]["elements"]
            ]
            return ok({"boundingBoxes2D": rows})
        return super().handle(body)


@pytest.fixture(autouse=True)
def receipt_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))


def client(*fakes):
    return ArchicadClient(ports=(19723, 19724), transport=fake_transport(*fakes))


async def run(fake, tmp_path, write=False, other=None):
    async with client(fake, *([other] if other else [])) as c:
        report = await smoke.run_smoke(
            c, port=fake.port, write_enabled=write, report_dir=tmp_path / "reports"
        )
    assert json.loads(Path(report["report_path"]).read_text(encoding="utf-8")) == report
    assert not any("Save" in name or "Delete" in name for name in fake.calls + fake.tapir_calls)
    return report


async def test_default_only_reads_at_most_five_walls_with_polygons(tmp_path):
    fake = SmokeFake(19723, untitled=False)
    for index in range(8):
        guid = f"{index + 1:08d}-1111-1111-1111-111111111111"
        fake.elements[guid] = "Wall"
        fake.details[guid] = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    before = deepcopy(fake.elements)
    report = await run(fake, tmp_path)
    assert report["status"] == "passed" and report["writes"] == []
    assert fake.elements == before
    details = next(r for r in fake.tapir_requests if r["command"] == "GetDetailsOfElements")
    assert len(details["parameters"]["elements"]) == 5
    assert "floorPlanPolygons" in details["parameters"]["fields"]
    assert "CreateWalls" not in fake.tapir_calls and "CreateSlabs" not in fake.tapir_calls


async def test_empty_read_project_skips_details(tmp_path):
    fake = SmokeFake(19723)
    report = await run(fake, tmp_path)
    assert report["status"] == "passed"
    assert report["reads"]["wall_details"]["detailsOfElements"] == []
    assert "GetDetailsOfElements" not in fake.tapir_calls


@pytest.mark.parametrize("untitled", [False, None, "true", 1])
async def test_write_refuses_named_or_unconfirmed_project(tmp_path, untitled):
    fake = SmokeFake(19723, project_name="Vitor project", untitled=untitled)
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "failed"
    assert "untitled" in report["error"]["message"]
    assert fake.elements == {} and report["writes"] == []


async def test_write_creates_l_walls_and_slab_and_checks_receipts(tmp_path):
    fake = SmokeFake(19723, stories=[{"index": 0, "name": "Ground", "level": 3}])
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "passed"
    assert list(fake.elements.values()) == ["Wall", "Wall", "Slab"]
    walls, slabs = report["writes"]
    assert walls["inputs"][0]["end"] == walls["inputs"][1]["start"]
    assert slabs["inputs"][0]["level"] == 3
    for entry, count in zip(report["writes"], [2, 1], strict=True):
        assert entry["preview"]["dry_run"] is True
        assert entry["receipt"]["dry_run"] is False
        assert entry["receipt"]["counts"]["verified"] == count
        assert Path(entry["receipt"]["receipt_path"]).exists()
    assert fake.tapir_calls.count("CreateWalls") == fake.tapir_calls.count("CreateSlabs") == 1


async def test_corner_is_beyond_existing_elements_and_other_instance_untouched(tmp_path):
    fake = SmokeFake(
        19723,
        elements={GUID: "Object"},
        boxes={GUID: {"xMin": 90, "yMin": 190, "xMax": 100, "yMax": 200}},
    )
    other = SmokeFake(19724, untitled=False)
    report = await run(fake, tmp_path, write=True, other=other)
    assert report["status"] == "passed"
    assert report["corner"]["x"] == 110 and report["corner"]["y"] == 210
    assert other.elements == {} and "CreateWalls" not in other.tapir_calls


async def test_unavailable_extent_prevents_writes(tmp_path):
    fake = SmokeFake(19723, elements={GUID: "Object"}, fail_boxes=True)
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "failed" and report["writes"] == []
    assert len(fake.elements) == 1


async def test_changed_project_blocks_second_batch(tmp_path):
    fake = SmokeFake(19723, become_named_after_walls=True)
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "failed"
    assert list(fake.elements.values()) == ["Wall", "Wall"]
    assert "CreateSlabs" not in fake.tapir_calls


async def test_partial_wall_failure_stops_before_slabs_and_keeps_receipt(tmp_path):
    fake = SmokeFake(19723, create_errors={0: CREATE_WALLS_FIXTURE["create_error"]})
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "failed"
    assert report["writes"][0]["receipt"]["counts"]["failed"] == 1
    assert len(fake.elements) == 1 and "CreateSlabs" not in fake.tapir_calls


async def test_lost_response_keeps_unknown_receipt_without_retry(tmp_path):
    fake = SmokeFake(19723, lose_create_response=True)
    report = await run(fake, tmp_path, write=True)
    assert report["status"] == "failed"
    assert report["writes"][0]["receipt"]["counts"]["unknown"] == 2
    assert fake.tapir_calls.count("CreateWalls") == 1
    assert "CreateSlabs" not in fake.tapir_calls


@pytest.mark.parametrize("directory", [smoke.REPOSITORY, smoke.REPOSITORY / "reports"])
async def test_repository_report_path_refused_before_requests(directory):
    fake = SmokeFake(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="outside"):
            await smoke.run_smoke(c, port=19723, report_dir=directory)
    assert fake.calls == []


async def test_unwritable_report_prevents_requests(tmp_path, monkeypatch):
    fake = SmokeFake(19723)

    def fail(*args):
        raise OSError("Disk failure")

    monkeypatch.setattr(smoke, "_save", fail)
    async with client(fake) as c:
        with pytest.raises(OSError):
            await smoke.run_smoke(c, port=19723, write_enabled=True, report_dir=tmp_path)
    assert fake.calls == []


@pytest.mark.parametrize("port", [None, True, 8080, 19744])
async def test_invalid_port_prevents_requests(tmp_path, port):
    fake = SmokeFake(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="explicit"):
            await smoke.run_smoke(c, port=port, report_dir=tmp_path)
    assert fake.calls == []


def test_cli_requires_port_and_defaults_to_read_only():
    with pytest.raises(SystemExit):
        smoke.parser().parse_args([])
    args = smoke.parser().parse_args(["--port", "19724"])
    assert args.port == 19724 and not args.write
    assert args.report_dir == Path.home() / ".archicad-mcp-aberto" / "smoke"
