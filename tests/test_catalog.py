from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from taproom.catalog import Catalog
from taproom.sources import load_mcp_servers, load_skills, skill_manifest


class CatalogTests(unittest.TestCase):
    def test_load_and_search_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "development" / "legacy-review"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: legacy-review\ndescription: Investigate inherited and abandoned codebases.\n---\n",
                encoding="utf-8",
            )
            catalog = Catalog(load_skills([("fixture", root)]))
            results = catalog.search("understand an inherited codebase")
            self.assertEqual(results[0]["id"], "fixture:skill:legacy-review")

    def test_manifest_hashes_files_and_records_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "utility" / "sample"
            (skill / "bin").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: sample\ndescription: Sample skill.\n---\n", encoding="utf-8")
            launcher = skill / "bin" / "sample"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o755)
            capability = load_skills([("fixture", root)])[0]
            manifest = skill_manifest(capability)
            files = {item["path"]: item for item in manifest["files"]}
            self.assertTrue(files["bin/sample"]["executable"])
            self.assertTrue(files["SKILL.md"]["hash"].startswith("sha256:"))

    def test_load_mcp_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "travel" / "weather"
            server.mkdir(parents=True)
            (server / "server.json").write_text(
                '{"name":"weather","category":"travel","description":"Forecast weather.","version":"1.2.0","tags":["forecast"]}',
                encoding="utf-8",
            )
            capability = load_mcp_servers([("fixture", root)])[0]
            self.assertEqual(capability.id, "fixture:mcp:weather")
            self.assertEqual(capability.version, "1.2.0")


if __name__ == "__main__":
    unittest.main()

