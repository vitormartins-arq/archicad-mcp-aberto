"""Minimal client for the Archicad JSON API and the ArchicadMcpAberto add-on commands.

The port comes from the ARCHICAD_PORT environment variable (default 19723). With several
Archicad instances open, pick the port of the right project first (see resolve_port in
the MCP server); never guess.
"""

import json
import os
import sys
import urllib.request

PORT = int(os.environ.get("ARCHICAD_PORT", "19723"))


def call(cmd, params=None, timeout=300):
    body = {"command": cmd}
    if params is not None:
        body["parameters"] = params
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def addon(name, params=None, ns="ArchicadMcpAberto", timeout=300):
    return call(
        "API.ExecuteAddOnCommand",
        {
            "addOnCommandId": {"commandNamespace": ns, "commandName": name},
            "addOnCommandParameters": params or {},
        },
        timeout,
    )


def addon_result(name, params=None):
    """Run an add-on command and return its response, raising on any error."""
    r = addon(name, params)
    if not r.get("succeeded"):
        raise RuntimeError(f"{name}: {r.get('error')}")
    resp = r["result"]["addOnCommandResponse"]
    if isinstance(resp, dict) and "error" in resp:
        raise RuntimeError(f"{name}: {resp['error']}")
    return resp


if __name__ == "__main__":
    # python acapi.py api API.GetProductInfo
    # python acapi.py addon Get3DCamera
    # python acapi.py addon Set3DCutPlanes '{"enabled": false}'
    kind, name = sys.argv[1], sys.argv[2]
    p = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    r = {"api": call, "addon": addon}[kind](name, p)
    print(json.dumps(r, ensure_ascii=False)[:6000])
