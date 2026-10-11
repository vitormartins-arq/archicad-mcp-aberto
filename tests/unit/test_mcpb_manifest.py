"""The Claude Desktop bundle manifest stays in step with the package and the server."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from archicad_mcp_aberto.server import create_server

ROOT = Path(__file__).parents[2]
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_required_fields():
    for key in ("manifest_version", "name", "version", "description", "author", "server"):
        assert MANIFEST[key]
    assert MANIFEST["author"]["name"]
    server = MANIFEST["server"]
    assert server["type"] == "uv"
    assert (ROOT / server["entry_point"]).is_file()
    assert server["mcp_config"]["command"] == "uv"


def test_version_matches_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert MANIFEST["version"] == project["version"]
    assert MANIFEST["name"] == project["name"]
    assert project["name"] in MANIFEST["server"]["mcp_config"]["args"]


def test_every_user_config_has_a_default():
    # Without a default the host could pass the literal placeholder to the server.
    for name, option in MANIFEST["user_config"].items():
        assert "default" in option, name
        assert f"${{user_config.{name}}}" in MANIFEST["server"]["mcp_config"]["env"].values()


@pytest.mark.anyio
async def test_tool_list_matches_the_server():
    registered = {tool.name for tool in await create_server().list_tools()}
    assert {tool["name"] for tool in MANIFEST["tools"]} == registered
