"""Revision-derived distribution names, immutable files and source receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {"addon": ".apx", "bundle": ".mcpb", "server_source": ".zip", "addon_source": ".zip"}


def metadata(root: Path) -> dict:
    data = json.loads((root / "distribution.json").read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not re.fullmatch(r"R[0-9]{2,}", data.get("revision", "")):
        raise ValueError("Expected schema 1 and a revision such as R03.")
    if int(data["revision"][1:]) < 1:
        raise ValueError("Revision must be positive.")
    for kind in EXTENSIONS:
        name = data.get("names", {}).get(kind, "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,60}", name) or name != name.strip():
            raise ValueError(f"Unsafe material name for {kind}.")
    return data


def filename(data: dict, kind: str) -> str:
    return f"{data['names'][kind]} - {data['revision']}{EXTENSIONS[kind]}"


def revision_check(root: Path, base: str) -> None:
    data = metadata(root)
    previous = subprocess.run(
        ["git", "-C", str(root), "show", f"{base}:distribution.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if previous.returncode:
        # Distinguish first adoption from a missing/unavailable base commit.
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", f"{base}^{{commit}}"],
            check=True,
            capture_output=True,
        )
        tree = subprocess.check_output(
            ["git", "-C", str(root), "ls-tree", "--name-only", base, "distribution.json"],
            text=True,
        )
        if tree.strip():
            raise ValueError("Cannot read the base distribution metadata.")
        return
    old = json.loads(previous.stdout)
    changed = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--name-only", base, "HEAD"], text=True
    )
    if changed.strip() and int(data["revision"][1:]) <= int(old["revision"][1:]):
        raise ValueError("Published material changed: advance distribution.json revision.")


def stage(root: Path, kind: str, source: Path, output: Path, archicad: int | None = None) -> Path:
    data = metadata(root)
    if kind == "addon" and archicad is None:
        raise ValueError("An APX requires its Archicad major version.")
    if archicad is not None and archicad not in (29, 30):
        raise ValueError("Only explicitly supported Archicad 29/30 builds may be packaged.")
    folder = output / f"Archicad {archicad}" if archicad else output
    target = folder / filename(data, kind)
    payload = source.read_bytes()
    if not payload:
        raise ValueError("Cannot distribute an empty file.")
    digest = hashlib.sha256(payload).hexdigest()
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    receipt_path = folder / f"Revisoes - {data['revision']}.json"
    receipt = {
        "schema": 1,
        "revision": data["revision"],
        "source_commit": commit,
        "archicad_major": archicad,
        "files": {},
    }
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if any(existing.get(key) != receipt[key] for key in receipt if key != "files"):
            raise FileExistsError("Revision already belongs to another commit/build; advance it.")
        receipt = existing
    if target.exists() and target.read_bytes() != payload:
        raise FileExistsError("Different bytes already use this name; advance the revision.")
    folder.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    receipt["files"][target.name] = {"kind": kind, "sha256": digest}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    name = sub.add_parser("name")
    name.add_argument("kind", choices=EXTENSIONS)
    check = sub.add_parser("check")
    check.add_argument("--base", required=True)
    for action in ("stage", "source"):
        cmd = sub.add_parser(action)
        cmd.add_argument(
            "kind", choices=EXTENSIONS if action == "stage" else ("server_source", "addon_source")
        )
        if action == "stage":
            cmd.add_argument("--input", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--archicad", type=int)
    args = parser.parse_args()
    if args.action == "name":
        print(filename(metadata(ROOT), args.kind))
    elif args.action == "check":
        revision_check(ROOT, args.base)
    elif args.action == "stage":
        print(stage(ROOT, args.kind, args.input, args.output, args.archicad))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.zip"
            subprocess.run(
                ["git", "-C", str(ROOT), "archive", "--format=zip", "-o", str(source), "HEAD"],
                check=True,
            )
            print(stage(ROOT, args.kind, source, args.output, args.archicad))


if __name__ == "__main__":
    main()
