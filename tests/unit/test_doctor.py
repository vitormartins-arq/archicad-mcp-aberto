from unittest.mock import AsyncMock

import pytest

from archicad_mcp_aberto import doctor

pytestmark = pytest.mark.anyio


class Client:
    host = "127.0.0.1"
    ports = (19723, 19724)

    def __init__(self, available=True):
        self.command = AsyncMock(return_value={"isAvailable": available})


async def test_ready_report_includes_optional_addon(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "discover",
        AsyncMock(
            return_value=[
                {
                    "port": 19723,
                    "status": "ready",
                    "version": 30,
                    "buildNumber": 3001,
                    "languageCode": "BRA",
                    "tapir_loaded": True,
                    "tapir_version": "1.7.0",
                    "project_name": "Teste",
                }
            ]
        ),
    )
    client = Client()
    result = await doctor.build_report(client)
    assert result["status"] == "ready"
    assert result["instances"][0]["companion_addon"] == {"loaded": True}
    assert "Port 19723: ready" in doctor.render(result)
    client.command.assert_awaited_once_with(
        19723, "IsAddOnCommandAvailable", doctor.OWN_ADDON_PROBE
    )


async def test_missing_archicad_has_action(monkeypatch):
    monkeypatch.setattr(doctor, "discover", AsyncMock(return_value=[]))
    result = await doctor.build_report(Client())
    assert result["status"] == "needs_attention"
    assert result["problems"][0]["code"] == "archicad_not_found"
    assert "Archicad: not found" in doctor.render(result)


async def test_missing_tapir_is_problem_but_companion_is_optional(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "discover",
        AsyncMock(
            return_value=[
                {
                    "port": 19723,
                    "status": "ready",
                    "version": 29,
                    "tapir_loaded": False,
                    "project_name": None,
                }
            ]
        ),
    )
    result = await doctor.build_report(Client(available=False))
    assert result["status"] == "needs_attention"
    assert [problem["code"] for problem in result["problems"]] == ["tapir_missing"]
    assert result["instances"][0]["companion_addon"] == {"loaded": False}
