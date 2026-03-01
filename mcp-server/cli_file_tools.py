"""
Async adapter layer that wraps ObsidianCLI in the same interface as FileTools.
Drop-in replacement for FileTools when use_cli_file_tools=True.

No WebSocket dependency. Vault is resolved from the CLI vault registry.

@purpose: Provide identical async API to FileTools using CLI subprocess backend
@depends: ObsidianCLI (obsidian_cli.py), asyncio.to_thread for subprocess offload
@results: Same response envelopes as FileTools — MCP server needs no changes
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from obsidian_cli import ObsidianCLI, detect_obsidian_binary

logger = logging.getLogger(__name__)


class CLIFileTools:
    """
    Async wrapper around ObsidianCLI providing the same public interface as FileTools.

    Key differences from FileTools:
    - No WebSocket server dependency — stateless subprocess calls per operation
    - Vault resolved from CLI registry; no heartbeat or connection tracking required
    - create_note_with_template uses Templater JS API via eval (non-interactive)
    - Periodic Notes folder paths derived from plugin config on disk or via eval
    """

    def __init__(self, cli: ObsidianCLI, default_vault: Optional[str] = None):
        """
        Args:
            cli: ObsidianCLI instance with binary path set
            default_vault: Default vault name to use when vault_id=None.
                           Populated from vault registry on startup.
        """
        self.cli = cli
        self._default_vault = default_vault
        self._vault_paths: Dict[str, str] = {}  # name → filesystem path (for Periodic Notes config)

    @classmethod
    def from_detected_binary(cls, default_vault: Optional[str] = None) -> "CLIFileTools":
        """Auto-detect binary and return ready instance. No subprocess calls at init time."""
        cli = ObsidianCLI.from_detected_binary()
        return cls(cli, default_vault)

    # ─── Vault Resolution ────────────────────────────────────────────────────

    def _resolve_vault(self, vault_id: Optional[str]) -> tuple[str | None, dict | None]:
        """
        Resolve vault name. Returns (vault_name, error_dict).
        Mirrors FileTools._validate_vault_connection() return signature.
        """
        if vault_id:
            return vault_id, None
        if self._default_vault:
            return self._default_vault, None
        return None, {
            "success": False,
            "error": "No vault specified and no default vault set.",
            "error_code": "NO_ACTIVE_VAULT",
        }

    def _vault_path(self, vault: str) -> Optional[str]:
        return self._vault_paths.get(vault)

    # ─── Public API — matches FileTools method signatures ────────────────────

    async def search_obsidian_notes(
        self,
        query: str,
        vault_id: Optional[str] = None,
        search_mode: str = "both",
        max_results: int = 100,
        include_context: bool = True,
        path: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.search_obsidian_notes,
            vault, query, search_mode, max_results, include_context, path,
        )

    async def read_obsidian_note(
        self,
        path: str,
        vault_id: Optional[str] = None,
        include_line_map: bool = False,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.read_obsidian_note, vault, path, include_line_map
        )

    async def update_obsidian_note(
        self,
        path: str,
        content: Optional[str] = None,
        vault_id: Optional[str] = None,
        editing_mode: str = "full_file",
        frontmatter_changes: Optional[Dict[str, Any]] = None,
        append_content: Optional[str] = None,
        replacement_content: Optional[str] = None,
        range_start_line: Optional[int] = None,
        range_start_char: Optional[int] = None,
        range_end_line: Optional[int] = None,
        range_end_char: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.update_obsidian_note,
            vault, path, editing_mode, content, append_content,
            frontmatter_changes, replacement_content,
            range_start_line, range_end_line,
        )

    async def create_obsidian_note(
        self,
        path: str,
        content: str = "",
        vault_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(self.cli.create_obsidian_note, vault, path, content)

    async def list_obsidian_vaults(self, vault_id: Optional[str] = None) -> Dict[str, Any]:
        result = await asyncio.to_thread(self.cli.list_obsidian_vaults)
        # Refresh cached vault paths
        if result.get("success"):
            for v in result["payload"].get("vaults", []):
                self._vault_paths[v["name"]] = v.get("path", "")
        return result

    async def explore_vault_folders(
        self,
        vault_id: Optional[str] = None,
        path: Optional[str] = None,
        query: Optional[str] = None,
        format: str = "smart",
        max_depth: int = 10,
        include_files: bool = False,
        extension_filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.explore_vault_folders,
            vault, path, include_files, extension_filter, max_depth, query,
        )

    async def create_note_with_template(
        self,
        request_type: str,
        file_name: str,
        content: str = "",
        target_folder: str = "",
        vault_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err

        # Resolve target_folder from Periodic Notes config if not provided
        resolved_folder = target_folder
        if not resolved_folder:
            try:
                vault_path = self._vault_path(vault)
                mappings_result = await asyncio.to_thread(
                    self.cli.get_template_mappings, vault, vault_path
                )
                if mappings_result.get("success"):
                    template_mappings = mappings_result["payload"].get("templateMappings", {})
                    request_lower = request_type.lower()
                    for tname, tfolder in template_mappings.items():
                        if request_lower in tname.lower() or tname.lower() in request_lower:
                            resolved_folder = tfolder
                            logger.info(f"[CLI] Resolved folder '{resolved_folder}' for template '{request_type}'")
                            break
            except Exception as e:
                logger.warning(f"[CLI] Template mapping lookup failed: {e}")

        return await asyncio.to_thread(
            self.cli.create_note_with_template,
            vault, request_type, file_name, content, resolved_folder,
        )

    async def manage_obsidian_notes(
        self,
        operation: str,
        path: str,
        vault_id: Optional[str] = None,
        newPath: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.manage_obsidian_notes, vault, operation, path, newPath
        )

    async def manage_obsidian_folders(
        self,
        operation: str,
        folderPath: str,
        vault_id: Optional[str] = None,
        newFolderPath: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.manage_obsidian_folders, vault, operation, folderPath, newFolderPath
        )

    # ─── Legacy method aliases (match FileTools method names called by MCP server) ──

    async def rename_obsidian_note(
        self, path: str, new_path: Optional[str], vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_notes("rename", path, vault_id, new_path)

    async def delete_obsidian_note(
        self, path: str, vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_notes("delete", path, vault_id)

    async def create_obsidian_folder(
        self, folder_path: str, vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_folders("create", folder_path, vault_id)

    async def rename_obsidian_folder(
        self, folder_path: str, new_folder_path: Optional[str], vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_folders("rename", folder_path, vault_id, new_folder_path)

    async def delete_obsidian_folder(
        self, folder_path: str, vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_folders("delete", folder_path, vault_id)

    # ─── Connected Vault Helpers (replaces WebSocket VaultRegistry API) ──────

    def get_connected_vaults(self) -> List[str]:
        """Return list of known vault names (replaces WebSocketServer.get_connected_vaults)."""
        result = self.cli.list_obsidian_vaults()
        if result.get("success"):
            return [v["name"] for v in result["payload"]["vaults"]]
        return []

    def get_active_vault(self) -> Optional[str]:
        """Return the default vault name."""
        return self._default_vault

    def set_active_vault(self, vault_name: str) -> None:
        """Set the default vault for subsequent calls."""
        self._default_vault = vault_name
        logger.info(f"[CLI] Active vault set to: {vault_name}")

    def is_cli_backend(self) -> bool:
        """Marker method for runtime detection. FileTools does not have this."""
        return True
