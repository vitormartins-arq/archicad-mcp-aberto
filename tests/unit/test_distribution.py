"""Exercise material identity and collision/revision safeguards without Archicad."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("distribution", ROOT / "tools/distribution.py")
distribution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = {
            "schema": 1,
            "revision": "R03",
            "names": {
                "addon": "LAB - Complemento MCP",
                "bundle": "LAB - Servidor MCP",
                "server_source": "LAB - Servidor MCP",
                "addon_source": "LAB - Complemento MCP Fonte",
            },
        }
        self.save()
        self.git("init", "-q")
        self.git("config", "user.email", "distribution-test@example.invalid")
        self.git("config", "user.name", "Offline fixture")
        self.commit()
        self.apx = self.root / "original.apx"
        self.apx.write_bytes(b"APX fixture, not an executable")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def save(self):
        (self.root / "distribution.json").write_text(json.dumps(self.data), encoding="utf-8")

    def commit(self):
        self.git("add", "distribution.json")
        self.git("commit", "-qm", "Fixture")

    def test_names_follow_only_the_material_revision(self):
        for revision in ("R03", "R04", "R100"):
            self.data["revision"] = revision
            self.save()
            self.assertEqual(
                distribution.filename(distribution.metadata(self.root), "addon"),
                f"LAB - Complemento MCP - {revision}.apx",
            )

    def test_bad_revision_and_path_names_are_refused(self):
        for revision in ("R00", "R3", "../R03", "r03", "v1.0", "R03-PR88"):
            self.data["revision"] = revision
            self.save()
            with self.assertRaises(ValueError):
                distribution.metadata(self.root)
        self.data["revision"] = "R03"
        self.data["names"]["addon"] = "../outside"
        self.save()
        with self.assertRaises(ValueError):
            distribution.metadata(self.root)

    def test_major_versions_are_separate_and_payload_is_unchanged(self):
        for major in (29, 30):
            target = distribution.stage(self.root, "addon", self.apx, self.root / "out", major)
            self.assertEqual(target.parent.name, f"Archicad {major}")
            self.assertEqual(target.read_bytes(), self.apx.read_bytes())
            receipt = json.loads((target.parent / "Revisoes - R03.json").read_text())
            self.assertEqual(receipt["source_commit"], self.git("rev-parse", "HEAD"))
            self.assertEqual(receipt["archicad_major"], major)
        with self.assertRaises(ValueError):
            distribution.stage(self.root, "addon", self.apx, self.root / "out")

    def test_same_bytes_may_repeat_but_different_bytes_cannot_overwrite(self):
        target = distribution.stage(self.root, "addon", self.apx, self.root / "out", 30)
        distribution.stage(self.root, "addon", self.apx, self.root / "out", 30)
        previous = target.read_bytes()
        self.apx.write_bytes(b"Changed material")
        with self.assertRaises(FileExistsError):
            distribution.stage(self.root, "addon", self.apx, self.root / "out", 30)
        self.assertEqual(target.read_bytes(), previous)

    def test_different_commit_cannot_reuse_a_distribution_folder(self):
        distribution.stage(self.root, "addon", self.apx, self.root / "out", 30)
        self.data["names"]["bundle"] = "LAB - MCP Server"
        self.save()
        self.commit()
        with self.assertRaises(FileExistsError):
            distribution.stage(self.root, "addon", self.apx, self.root / "out", 30)

    def test_changed_material_requires_a_revision_advance(self):
        base = self.git("rev-parse", "HEAD")
        self.data["names"]["bundle"] = "LAB - MCP Server"
        self.save()
        self.commit()
        with self.assertRaises(ValueError):
            distribution.revision_check(self.root, base)
        self.data["revision"] = "R04"
        self.save()
        self.commit()
        distribution.revision_check(self.root, base)

    def test_first_adoption_and_invalid_base_are_distinguished(self):
        self.git("rm", "distribution.json")
        self.git("commit", "-qm", "Pre-policy fixture")
        base = self.git("rev-parse", "HEAD")
        self.save()
        distribution.revision_check(self.root, base)
        with self.assertRaises(subprocess.CalledProcessError):
            distribution.revision_check(self.root, "missing-ref")


if __name__ == "__main__":
    unittest.main()
