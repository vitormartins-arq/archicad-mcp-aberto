"""HTTP client for the Archicad JSON API, with one reused connection per session.

Reusing the client matters: on Archicad 29 a small read took a median of 216.6 ms
with a new client per call and 4.1 ms with a reused one.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from types import TracebackType
from typing import Any

import httpx

from archicad_mcp_aberto.connection.errors import (
    ArchicadUnavailable,
    TapirError,
    from_api_error,
)

DEFAULT_HOST = "127.0.0.1"
# Archicad picks the first free port from 19723 upward, one per running instance.
DEFAULT_PORTS: tuple[int, ...] = tuple(range(19723, 19744))
TAPIR_NAMESPACE = "TapirCommand"


def ports_from_env(value: str | None = None) -> tuple[int, ...]:
    """Read ARCHICAD_MCP_PORTS ("19723-19743" or "19723,19724")."""
    value = value if value is not None else os.environ.get("ARCHICAD_MCP_PORTS")
    if not value:
        return DEFAULT_PORTS
    ports: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(p) for p in part.split("-", 1))
            ports.extend(range(start, end + 1))
        elif part:
            ports.append(int(part))
    if not ports:
        raise ValueError("ARCHICAD_MCP_PORTS is empty.")
    return tuple(dict.fromkeys(ports))


class ArchicadClient:
    """Talks to every Archicad instance on this machine through one HTTP client."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        ports: Sequence[int] = DEFAULT_PORTS,
        *,
        timeout: float = 12.0,
        probe_timeout: float = 1.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.host = host
        self.ports = tuple(ports)
        self.timeout = timeout
        self.probe_timeout = probe_timeout
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ArchicadClient:
        # trust_env=False: never send local Archicad traffic through a system proxy.
        self._http = httpx.AsyncClient(
            trust_env=False, timeout=self.timeout, transport=self._transport
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def check_port(self, port: int) -> None:
        if port not in self.ports:
            raise ValueError(
                f"Port {port} is outside the Archicad range "
                f"{self.ports[0]}-{self.ports[-1]}. Run discover_archicad first."
            )

    async def post(
        self, port: int, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict:
        """Send one raw request and return the decoded JSON body."""
        if self._http is None:
            raise RuntimeError("ArchicadClient must be used inside 'async with'.")
        self.check_port(port)
        try:
            response = await self._http.post(
                f"http://{self.host}:{port}", json=payload, timeout=timeout or self.timeout
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ArchicadUnavailable(
                f"Archicad on port {port} did not answer or sent an invalid response. "
                "Run discover_archicad again; the instance may have closed."
            ) from exc
        if not isinstance(data, dict):
            raise ArchicadUnavailable(f"Archicad on port {port} sent an unexpected response.")
        return data

    async def command(
        self,
        port: int,
        name: str,
        parameters: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run an official JSON API command (`API.<name>`) and return its result."""
        payload: dict[str, Any] = {"command": f"API.{name}"}
        if parameters is not None:
            payload["parameters"] = parameters
        data = await self.post(port, payload, timeout=timeout)
        if not data.get("succeeded"):
            raise from_api_error(data.get("error", data))
        result = data.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    async def tapir(
        self,
        port: int,
        name: str,
        parameters: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run a Tapir add-on command through API.ExecuteAddOnCommand."""
        request: dict[str, Any] = {
            "addOnCommandId": {"commandNamespace": TAPIR_NAMESPACE, "commandName": name}
        }
        if parameters is not None:
            request["addOnCommandParameters"] = parameters
        result = await self.command(port, "ExecuteAddOnCommand", request, timeout=timeout)
        response = result.get("addOnCommandResponse")
        if not isinstance(response, dict):
            raise TapirError(f"Tapir command {name} returned no response.")
        if response.get("error"):
            raise TapirError(f"Tapir error in {name}.", detail=response["error"])
        return response
