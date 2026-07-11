from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from taproom.catalog import Catalog
from taproom.packages import package_manifest
from taproom.sources import load_capabilities, load_mcp_servers, load_skills, load_taps


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
            catalog = Catalog(load_skills([("public", "fixture", root)]))
            results = catalog.search("understand an inherited codebase")
            self.assertEqual(results[0]["id"], "public:skill:fixture~development~legacy-review")

    def test_same_named_skills_get_path_qualified_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for category in ("development", "game-development"):
                skill = root / category / "performance-optimization"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    "---\nname: performance-optimization\ndescription: Find performance bottlenecks.\n---\n",
                    encoding="utf-8",
                )
            catalog = Catalog(load_skills([("public", "fixture", root)]))
            self.assertEqual(len(catalog.by_id), 2)
            self.assertIn("public:skill:fixture~development~performance-optimization", catalog.by_id)
            self.assertIn("public:skill:fixture~game-development~performance-optimization", catalog.by_id)

    def test_manifest_hashes_files_and_records_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "utility" / "sample"
            (skill / "bin").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: sample\ndescription: Sample skill.\n---\n", encoding="utf-8")
            launcher = skill / "bin" / "sample"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o755)
            outside = root / "outside.bin"
            outside.write_bytes(b"not part of the skill")
            (skill / "outside-link").symlink_to(outside)
            (skill / ".venv").mkdir()
            (skill / ".venv" / "installed-package.py").write_text("ignored", encoding="utf-8")
            (skill / ".env.local").write_text("TOKEN=secret", encoding="utf-8")
            (skill / "secrets.env").write_text("TOKEN=secret", encoding="utf-8")
            capability = load_skills([("public", "fixture", root)])[0]
            manifest = package_manifest(capability)
            files = {item["path"]: item for item in manifest["files"]}
            self.assertTrue(files["bin/sample"]["executable"])
            self.assertTrue(files["SKILL.md"]["hash"].startswith("sha256:"))
            self.assertNotIn("outside-link", files)
            self.assertNotIn(".venv/installed-package.py", files)
            self.assertNotIn(".env.local", files)
            self.assertNotIn("secrets.env", files)

    def test_load_mcp_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "travel" / "weather"
            server.mkdir(parents=True)
            (server / "server.json").write_text(
                '{"name":"weather","category":"travel","description":"Forecast weather.","version":"1.2.0","tags":["forecast"],"transport":"stdio","launch":{"command":"uv","args":["run","server.py"],"cwd":"."},"requirements":{"platforms":["any"],"commands":["uv"]}}',
                encoding="utf-8",
            )
            (server / "server.py").write_text(
                '# /// script\n# requires-python = ">=3.11"\n# dependencies = ["fastmcp==3.4.4"]\n# ///\n',
                encoding="utf-8",
            )
            capability = load_mcp_servers([("public", "fixture", root)])[0]
            self.assertEqual(capability.id, "public:mcp:fixture~travel~weather")
            self.assertEqual(capability.version, "1.2.0")
            plan = package_manifest(capability)["plan"]
            self.assertTrue(plan["requirements_declared"])
            self.assertEqual(plan["detected_dependencies"]["python"], ["fastmcp==3.4.4"])
            self.assertEqual(plan["unresolved"], [])

    def test_config_loads_multiple_named_taps_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, name in (
                ("public-skills/analysis/inspect", "inspect"),
                ("private-skills/analysis/private-inspect", "private-inspect"),
            ):
                skill = root / relative
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Inspect a test artifact.\n---\n",
                    encoding="utf-8",
                )
            server = root / "private-mcp" / "debug" / "x64dbg"
            server.mkdir(parents=True)
            (server / "server.json").write_text(
                '{"name":"x64dbg","description":"Debug a Windows process."}',
                encoding="utf-8",
            )
            config = root / "taproom.toml"
            config.write_text(
                """version = 1
[[taps]]
name = "public"
visibility = "public"
[[taps.sources]]
name = "skilltap"
kind = "skill"
path = "public-skills"

[[taps]]
name = "private"
visibility = "private"
[[taps.sources]]
name = "skilltap"
kind = "skill"
path = "private-skills"
[[taps.sources]]
name = "rekit"
kind = "mcp"
path = "private-mcp"
""",
                encoding="utf-8",
            )
            taps = load_taps(config)
            capabilities = Catalog(load_capabilities(taps))
            self.assertEqual([tap.name for tap in taps], ["public", "private"])
            self.assertEqual(len(capabilities.by_id), 3)
            self.assertIn("public:skill:skilltap~analysis~inspect", capabilities.by_id)
            self.assertIn("private:skill:skilltap~analysis~private-inspect", capabilities.by_id)
            self.assertIn("private:mcp:rekit~debug~x64dbg", capabilities.by_id)
            private_results = capabilities.search("inspect a test artifact", tap="private")
            self.assertEqual({result["tap"] for result in private_results}, {"private"})


if __name__ == "__main__":
    unittest.main()
