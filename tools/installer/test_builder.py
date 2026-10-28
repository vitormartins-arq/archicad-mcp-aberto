import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "installer_builder", Path(__file__).with_name("build_installer.py")
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class InstallerBuilderTests(unittest.TestCase):
    def test_windows_paths_are_unambiguous(self):
        for p in (
            "../a.apx",
            "x/../a.apx",
            "C:/file",
            "/file",
            "a\\b",
            "file:stream",
            "CON",
            "engine/NUL.py",
            "file.",
            "file ",
            "x//y",
        ):
            with self.subTest(path=p), self.assertRaises(ValueError):
                builder.safe_name(p)
        self.assertEqual(builder.safe_name("engine/vendor/file.py"), "engine/vendor/file.py")


if __name__ == "__main__":
    unittest.main()
