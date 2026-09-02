import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SERVER_DIR = Path(__file__).parent
sys.path.insert(0, str(SERVER_DIR))

from cli_file_tools import CLIFileTools


class FakeCLI:
    def __init__(self, vault_path: str, base_paths=None):
        self.vault_path = vault_path
        self.base_paths = base_paths or []

    def list_obsidian_vaults(self):
        return {
            "success": True,
            "payload": {
                "vaults": [{"id": "Fixture", "name": "Fixture", "path": self.vault_path}]
            },
        }

    def list_bases(self, vault):
        return {
            "success": True,
            "payload": {"bases": self.base_paths, "totalBases": len(self.base_paths)},
        }

    def list_base_views(self, vault, file, path):
        return {
            "success": False,
            "error": "Active file is not a base file: unrelated.md",
            "error_code": "CLI_ERROR",
        }


class CLIFileToolsBaseViewsTests(unittest.TestCase):
    def test_list_base_views_reads_named_base_without_active_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            base_path.parent.mkdir()
            base_path.write_text(
                "filters:\n  and: []\nviews:\n  - type: table\n    name: All\n  - type: table\n    name: ClaudeDesktop\n",
                encoding="utf-8",
            )

            result = asyncio.run(
                CLIFileTools(FakeCLI(temp_dir)).list_base_views(
                    path="Bases/Skills.base", vault_id="Fixture"
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["payload"], {"views": ["All", "ClaudeDesktop"], "totalViews": 2})

    def test_list_base_views_reads_name_after_nested_view_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            base_path.parent.mkdir()
            base_path.write_text(
                "views:\n  - type: table\n    order:\n      - file.name\n    name: Later\n",
                encoding="utf-8",
            )

            result = asyncio.run(
                CLIFileTools(FakeCLI(temp_dir)).list_base_views(
                    path="Bases/Skills.base", vault_id="Fixture"
                )
            )

        self.assertEqual(result["payload"], {"views": ["Later"], "totalViews": 1})

    def test_list_base_views_resolves_literal_bracket_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills [2026].base"
            base_path.parent.mkdir()
            base_path.write_text("views:\n  - name: All\n", encoding="utf-8")

            result = asyncio.run(
                CLIFileTools(
                    FakeCLI(temp_dir, ["Bases/Skills [2026].base"])
                ).list_base_views(file="Skills [2026]", vault_id="Fixture")
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["payload"], {"views": ["All"], "totalViews": 1})

    def test_list_base_views_uses_cli_base_listing_not_physical_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            hidden_path = Path(temp_dir) / ".obsidian" / "plugin" / "Skills.base"
            base_path.parent.mkdir()
            hidden_path.parent.mkdir(parents=True)
            base_path.write_text("views:\n  - name: Visible\n", encoding="utf-8")
            hidden_path.write_text("views:\n  - name: Hidden\n", encoding="utf-8")

            result = asyncio.run(
                CLIFileTools(
                    FakeCLI(temp_dir, ["Bases/Skills.base"])
                ).list_base_views(file="Skills", vault_id="Fixture")
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["payload"], {"views": ["Visible"], "totalViews": 1})

    def test_list_base_views_rejects_ambiguous_visible_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = Path(temp_dir) / "First" / "Skills.base"
            second_path = Path(temp_dir) / "Second" / "Skills.base"
            first_path.parent.mkdir()
            second_path.parent.mkdir()
            first_path.write_text("views: []\n", encoding="utf-8")
            second_path.write_text("views: []\n", encoding="utf-8")

            result = asyncio.run(
                CLIFileTools(
                    FakeCLI(temp_dir, ["First/Skills.base", "Second/Skills.base"])
                ).list_base_views(file="Skills", vault_id="Fixture")
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "BASE_NOT_UNIQUE")

    def test_list_base_views_rejects_malformed_views_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            base_path.parent.mkdir()
            base_path.write_text("views:\n  name: Nope\n", encoding="utf-8")

            result = asyncio.run(
                CLIFileTools(FakeCLI(temp_dir)).list_base_views(
                    path="Bases/Skills.base", vault_id="Fixture"
                )
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "BASE_PARSE_ERROR")

    def test_list_base_views_reports_missing_pyyaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            base_path.parent.mkdir()
            base_path.write_text("views: []\n", encoding="utf-8")

            with mock.patch("cli_file_tools.yaml", None):
                result = asyncio.run(
                    CLIFileTools(FakeCLI(temp_dir)).list_base_views(
                        path="Bases/Skills.base", vault_id="Fixture"
                    )
                )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "MISSING_DEPENDENCY")


if __name__ == "__main__":
    unittest.main()
