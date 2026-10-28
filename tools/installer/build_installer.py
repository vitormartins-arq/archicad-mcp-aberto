"""Build a self-contained Windows installer without third-party build dependencies."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent


def safe_name(name):
    parts = PurePosixPath(name).parts
    if (
        not name
        or "\\" in name
        or ":" in name
        or name.startswith("/")
        or any(p in ("", ".", "..") or p.endswith((".", " ")) for p in name.split("/"))
        or any(re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", p, re.I) for p in parts)
    ):
        raise ValueError(f"Unsafe package path: {name}")
    return name


def package_data(source, product, major, payload_revision):
    if product == "LAB - Complemento MCP":
        if source.suffix.lower() != ".apx":
            raise ValueError("Companion input must be an APX from a verified matching-major build.")
        return {"LAB - Complemento MCP.apx": source.read_bytes()}
    with zipfile.ZipFile(source) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        names = [safe_name(i.filename) for i in entries]
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError("Duplicate ZIP members.")
        manifest = json.loads(z.read("update.json"))
        if (
            manifest.get("product") != f"vitor.obj-suavizado.ac{major}"
            or manifest.get("archicad_version") != major
            or manifest.get("version") != payload_revision
        ):
            raise ValueError("Importer payload version/product does not match the installer.")
        inventory = manifest["files"]
        if set(names) != set(inventory) | {"update.json"}:
            raise ValueError("Incomplete update inventory.")
        data = {n: z.read(n) for n in names}
        for n, digest in inventory.items():
            if hashlib.sha256(data[n]).hexdigest() != digest:
                raise ValueError(f"Invalid payload hash: {n}")
        for n in (
            "ImportadorOBJ.apx",
            "engine/obj_engine.py",
            "engine/updater.py",
            "engine/archicad_target.json",
        ):
            if n not in data:
                raise ValueError(f"Missing runtime file: {n}")
        if json.loads(data["engine/archicad_target.json"])["archicad_version"] != major:
            raise ValueError("Wrong Archicad major in runtime.")
        if not any(n.startswith("runtime/") for n in data):
            raise ValueError("Portable runtime missing.")
        return data


def compile_installer(source, output, root, major, payload_revision, channel):
    # Derive public name/revision from the existing per-repository source of truth.
    if (root / "distribution.json").exists():
        metadata = json.loads((root / "distribution.json").read_text())
        product = metadata["names"]["addon"]
        revision = metadata["revision"]
    else:
        product = "LAB - Importador de Blocos e Texturas"
        revision = json.loads((root / "config.json").read_text())["version"]
    if product not in ("LAB - Complemento MCP", "LAB - Importador de Blocos e Texturas"):
        raise ValueError("Unsupported LAB product.")
    if not re.fullmatch(r"R\d{2,}|\d+\.\d+\.\d+", revision):
        raise ValueError("Invalid material revision.")
    expected = f"{product} - {revision}.exe"
    target = output / f"Archicad {major}" / expected
    if target.exists():
        raise FileExistsError("Preserve the previous installer; advance the material revision.")
    data = package_data(source, product, major, payload_revision)
    apx = "LAB - Complemento MCP.apx" if product.endswith("MCP") else "ImportadorOBJ.apx"
    csc = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    with tempfile.TemporaryDirectory(prefix="lab-installer-") as tmp:
        stage = Path(tmp)
        sample = stage / "sample.apx"
        sample.write_bytes(data[apx])
        reader = stage / "mdid.exe"
        subprocess.run(
            [str(csc), "/nologo", "/main:Mdid", "/out:" + str(reader), str(HERE / "Mdid.cs")],
            check=True,
        )
        mdid = (
            subprocess.check_output([str(reader), str(sample)], text=True)
            .strip()
            .rsplit(" = ", 1)[1]
        )
        expected_mdid = (
            "08-00-00-00-62-51-33-42-3A-42-26-11"
            if product.endswith("MCP")
            else "08-00-00-00-62-51-33-42-75-41-27-4E"
        )
        if mdid != expected_mdid:
            raise ValueError("APX belongs to a different registered add-on (MDID).")
        config = dict(
            product=product,
            revision=revision,
            payload_revision=payload_revision,
            archicad=major,
            channel=channel,
            apx=apx,
            mdid=mdid,
            files={n: hashlib.sha256(b).hexdigest() for n, b in data.items()},
        )
        (stage / "package.json").write_text(json.dumps(config, ensure_ascii=True), encoding="utf-8")
        with zipfile.ZipFile(stage / "payload.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in sorted(data.items()):
                z.writestr(n, b)
        candidate = stage / "installer.exe"
        subprocess.run(
            [
                str(csc),
                "/nologo",
                "/target:winexe",
                "/platform:x64",
                "/main:Installer",
                "/out:" + str(candidate),
                "/win32manifest:" + str(HERE / "installer.manifest"),
                "/resource:" + str(stage / "payload.zip") + ",payload.zip",
                "/resource:" + str(stage / "package.json") + ",package.json",
                "/r:System.Windows.Forms.dll",
                "/r:System.Drawing.dll",
                "/r:System.Web.Extensions.dll",
                "/r:System.IO.Compression.dll",
                str(HERE / "Installer.cs"),
                str(HERE / "InstallCore.cs"),
                str(HERE / "Mdid.cs"),
            ],
            check=True,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as f:
            f.write(candidate.read_bytes())
    receipt = dict(
        product=product,
        revision=revision,
        payload_revision=payload_revision,
        archicad_major=major,
        channel=channel,
        source_commit=subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        payload_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        installer_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        signed=False,
        mdid=mdid,
        files=config["files"],
    )
    target.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archicad", type=int, choices=(29, 30), required=True)
    parser.add_argument("--payload-revision", required=True)
    parser.add_argument("--channel", required=True, choices=("main", "candidata", "em teste"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        compile_installer(
            args.input, args.output, args.root, args.archicad, args.payload_revision, args.channel
        )
    )
