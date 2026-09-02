import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).parent
sys.path.insert(0, str(SERVER_DIR))

from cli_file_tools import CLIFileTools


class FakeCLI:
    def __init__(self, vault_path: str):
        self.vault_path = vault_path

    def list_obsidian_vaults(self):
        return {
            "success": True,
            "payload": {
                "vaults": [{"id": "Fixture", "name": "Fixture", "path": self.vault_path}]
            },
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

    def test_list_base_views_rejects_glob_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "Bases" / "Skills.base"
            base_path.parent.mkdir()
            base_path.write_text("views: []\n", encoding="utf-8")

            result = asyncio.run(
                CLIFileTools(FakeCLI(temp_dir)).list_base_views(
                    file="*", vault_id="Fixture"
                )
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INVALID_BASE_PATH")


if __name__ == "__main__":
    unittest.main()
