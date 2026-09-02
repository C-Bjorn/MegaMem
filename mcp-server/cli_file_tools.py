"""
Async adapter layer that wraps ObsidianCLI in the same interface as FileTools.
Drop-in replacement for FileTools when use_cli_file_tools=True.

No WebSocket dependency. Vault is resolved from the CLI vault registry.

@purpose: Provide identical async API to FileTools using CLI subprocess backend
@depends: ObsidianCLI (obsidian_cli.py), asyncio.to_thread for subprocess offload
@results: Same response envelopes as FileTools — MCP server needs no changes
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from obsidian_cli import ObsidianCLI, detect_obsidian_binary

try:
    import yaml
except ImportError:
    yaml = None

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

    def __init__(
        self,
        cli: ObsidianCLI,
        default_vault: Optional[str] = None,
        template_sources: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Args:
            cli: ObsidianCLI instance with binary path set
            default_vault: Default vault name to use when vault_id=None.
                           Populated from vault registry on startup.
            template_sources: Day77.01 native template engine — ordered list of
                           {vault_id, folder, label, registry} configured in
                           plugin settings (templateSources). Empty/None keeps
                           create_note_with_template on the frozen legacy path.
        """
        self.cli = cli
        self._default_vault = default_vault
        self._vault_paths: Dict[str, str] = {}  # name → filesystem path (for Periodic Notes config)
        self._template_sources = template_sources or []

    def update_template_sources(self, template_sources: Optional[List[Dict[str, Any]]]) -> None:
        """Update configured template sources at runtime (Task 3b
        follow-up #3, Day77.01) — single entry point for any future
        settings-reload path that updates sources on this already-running
        instance instead of via a full process restart. Always invalidates
        the underlying ObsidianCLI's registry-discovery cache so a stale
        resolved (or previously-missing) Base path can't outlive the
        config that produced it.
        """
        self._template_sources = template_sources or []
        self.cli.invalidate_registry_cache()

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
        query: str = "",
        vault_id: Optional[str] = None,
        search_mode: str = "both",
        max_results: int = 100,
        include_context: bool = True,
        path: Optional[str] = None,
        property_filter: Optional[dict] = None,
        mtime_after: Optional[str] = None,
        mtime_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.search_obsidian_notes,
            vault, query, search_mode, max_results, include_context, path,
            property_filter, mtime_after, mtime_before,
        )

    async def read_obsidian_note(
        self,
        path: str,
        vault_id: Optional[str] = None,
        include_line_map: bool = False,
    ) -> Dict[str, Any]:
        if isinstance(include_line_map, str):
            include_line_map = include_line_map.lower() in ("true", "1", "yes")
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
        if isinstance(frontmatter_changes, str):
            try:
                frontmatter_changes = json.loads(frontmatter_changes)
            except (ValueError, TypeError):
                frontmatter_changes = None
        if isinstance(range_start_line, str):
            try:
                range_start_line = int(range_start_line)
            except (ValueError, TypeError):
                range_start_line = None
        if isinstance(range_end_line, str):
            try:
                range_end_line = int(range_end_line)
            except (ValueError, TypeError):
                range_end_line = None
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
        template_source: Optional[Any] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err

        # Day77.01: native multi-source engine takes over folder/template
        # resolution entirely when template_sources is configured — skip the
        # legacy Periodic-Notes-mapping pre-resolution below in that case,
        # since the native engine's own precedence ladder (Architecture Notes)
        # supersedes it and re-deriving target_folder here would just be
        # overridden anyway.
        if self._template_sources:
            # A source's empty vault_id means "wherever these settings live"
            # (the home vault this MCP instance was configured against), NOT
            # the vault this particular call is writing to — otherwise
            # cross-vault writes (the whole point of this feature) would look
            # for templates inside the destination vault and find nothing.
            home_vault = self._default_vault or vault
            resolved_sources = [
                {**source, "vault_id": source.get("vault_id") or home_vault}
                for source in self._template_sources
            ]
            return await asyncio.to_thread(
                self.cli.create_note_with_template,
                vault, request_type, file_name, content, target_folder,
                resolved_sources, template_source,
            )

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
        target_vault_id: Optional[str] = None,
        target_path: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        if operation in ("copy_to_vault", "move_to_vault"):
            return await self._manage_notes_cross_vault(
                operation, path, vault_id, target_vault_id, target_path, overwrite
            )
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.manage_obsidian_notes, vault, operation, path, newPath
        )

    async def _manage_notes_cross_vault(
        self,
        operation: str,
        path: str,
        vault_id: Optional[str],
        target_vault_id: Optional[str],
        target_path: Optional[str],
        overwrite: bool,
    ) -> Dict[str, Any]:
        """Day75.05: orchestrate copy_to_vault / move_to_vault across two vaults
        via sequenced CLI calls (no native cross-vault Vault API exists).
        """
        if isinstance(overwrite, str):
            overwrite = overwrite.lower() in ("true", "1", "yes")
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        if not target_vault_id:
            return {
                "success": False,
                "error": "target_vault_id is required for copy_to_vault/move_to_vault",
                "error_code": "MISSING_TARGET_VAULT",
            }
        if not target_path:
            return {
                "success": False,
                "error": "target_path is required for copy_to_vault/move_to_vault",
                "error_code": "MISSING_TARGET_PATH",
            }
        fn = (
            self.cli.copy_note_cross_vault
            if operation == "copy_to_vault"
            else self.cli.move_note_cross_vault
        )
        return await asyncio.to_thread(fn, vault, path, target_vault_id, target_path, overwrite)

    async def copy_note_cross_vault(
        self,
        path: str,
        target_path: str,
        vault_id: Optional[str] = None,
        target_vault_id: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_notes(
            "copy_to_vault", path, vault_id,
            target_vault_id=target_vault_id, target_path=target_path, overwrite=overwrite,
        )

    async def move_note_cross_vault(
        self,
        path: str,
        target_path: str,
        vault_id: Optional[str] = None,
        target_vault_id: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        return await self.manage_obsidian_notes(
            "move_to_vault", path, vault_id,
            target_vault_id=target_vault_id, target_path=target_path, overwrite=overwrite,
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

    async def sync_obsidian_note(
        self,
        path: str,
        vault_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger MegaMem sync for a specific note via the registered plugin command."""
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(self.cli.trigger_sync, vault, path)

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

    # ─── Bases Tools ────────────────────────────────────────────────────────────

    async def manage_obsidian_base(
        self,
        operation: str,
        file: Optional[str] = None,
        path: Optional[str] = None,
        view: Optional[str] = None,
        format: str = "json",
        name: Optional[str] = None,
        content: Optional[str] = None,
        vault_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Route Bases operations by operation param to the underlying method.
        operation: 'list' | 'views' | 'query' | 'create'
        """
        if operation == "list":
            return await self.list_bases(vault_id=vault_id)
        elif operation == "views":
            return await self.list_base_views(file=file, path=path, vault_id=vault_id)
        elif operation == "query":
            return await self.query_base(file=file, path=path, view=view, format=format, vault_id=vault_id, limit=limit)
        elif operation == "create":
            return await self.create_base_item(file=file, path=path, view=view, name=name, content=content, vault_id=vault_id)
        else:
            return {
                "success": False,
                "error": f"Unknown operation '{operation}'. Use 'list', 'views', 'query', or 'create'.",
                "error_code": "INVALID_OPERATION",
            }

    async def list_bases(self, vault_id: Optional[str] = None) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(self.cli.list_bases, vault)

    async def list_base_views(
        self,
        file: Optional[str] = None,
        path: Optional[str] = None,
        vault_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        vault_path = self._vault_path(vault)
        if not vault_path:
            vaults_result = await asyncio.to_thread(self.cli.list_obsidian_vaults)
            if vaults_result.get("success"):
                for configured_vault in vaults_result.get("payload", {}).get("vaults", []):
                    self._vault_paths[configured_vault["name"]] = configured_vault.get("path", "")
                vault_path = self._vault_path(vault)

        if not vault_path:
            return {
                "success": False,
                "error": f"Could not find a filesystem path for vault '{vault}'.",
                "error_code": "VAULT_PATH_UNAVAILABLE",
            }

        return await asyncio.to_thread(self._read_base_views, vault_path, file, path)

    @staticmethod
    def _read_base_views(
        vault_path: str,
        file: Optional[str],
        path: Optional[str],
    ) -> Dict[str, Any]:
        """Read view names directly from a Base YAML file.

        Obsidian CLI's ``base:views`` only supports the active Base, even when
        ``file`` or ``path`` is supplied. Querying an explicitly selected Base
        is therefore intentionally handled from its on-disk YAML here.
        """
        if path:
            candidate = Path(vault_path, path)
        elif file:
            if any(character in file for character in "*?[]"):
                return {
                    "success": False,
                    "error": "Base file must be a literal basename, not a glob pattern.",
                    "error_code": "INVALID_BASE_PATH",
                }
            requested_file = Path(file)
            if requested_file.is_absolute():
                return {
                    "success": False,
                    "error": "Base file must be relative to the selected vault.",
                    "error_code": "INVALID_BASE_PATH",
                }
            filename = file if file.endswith(".base") else f"{file}.base"
            matches = list(Path(vault_path).rglob(filename))
            if len(matches) != 1:
                detail = "no matching Base file" if not matches else "multiple matching Base files"
                return {
                    "success": False,
                    "error": f"Could not resolve '{filename}': {detail}. Use path instead.",
                    "error_code": "BASE_NOT_UNIQUE",
                }
            candidate = matches[0]
        else:
            return {
                "success": False,
                "error": "file or path required for list_base_views",
                "error_code": "BASE_PATH_REQUIRED",
            }

        vault_root = Path(vault_path).resolve()
        try:
            base_path = candidate.resolve()
            base_path.relative_to(vault_root)
        except (OSError, RuntimeError, ValueError):
            return {
                "success": False,
                "error": "Base path must be inside the selected vault.",
                "error_code": "INVALID_BASE_PATH",
            }

        if base_path.suffix != ".base" or not base_path.is_file():
            return {
                "success": False,
                "error": f"Base file not found: {path or file}",
                "error_code": "BASE_NOT_FOUND",
            }

        try:
            base_content = base_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "success": False,
                "error": f"Could not read Base file: {exc}",
                "error_code": "BASE_READ_ERROR",
            }

        if yaml is not None:
            try:
                parsed = yaml.safe_load(base_content) or {}
            except yaml.YAMLError as exc:
                return {
                    "success": False,
                    "error": f"Could not parse Base YAML: {exc}",
                    "error_code": "BASE_PARSE_ERROR",
                }
            configured_views = parsed.get("views", []) if isinstance(parsed, dict) else []
            views = [
                view["name"]
                for view in configured_views
                if isinstance(view, dict) and isinstance(view.get("name"), str)
            ]
            return {"success": True, "payload": {"views": views, "totalViews": len(views)}}

        # Compatibility fallback for an installation that has not yet installed
        # the PyYAML dependency. Obsidian-generated Base files use this shape.
        lines = base_content.splitlines()
        views: List[str] = []
        views_indent: Optional[int] = None
        view_indent: Optional[int] = None
        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if views_indent is None:
                if stripped == "views:":
                    views_indent = indent
                continue
            if stripped and indent <= views_indent:
                break
            if stripped.startswith("- ") and indent > views_indent:
                if view_indent is None:
                    view_indent = indent
                if indent != view_indent:
                    continue
                inline_name = stripped.removeprefix("- ").strip()
                if inline_name.startswith("name:"):
                    name = inline_name.removeprefix("name:").strip()
                    if len(name) >= 2 and name[0] == name[-1] and name[0] in ("'", '"'):
                        name = name[1:-1]
                    if name:
                        views.append(name)
                continue
            if view_indent is None or indent != view_indent + 2 or not stripped.startswith("name:"):
                continue
            name = stripped.removeprefix("name:").strip()
            if len(name) >= 2 and name[0] == name[-1] and name[0] in ("'", '"'):
                name = name[1:-1]
            if name:
                views.append(name)

        return {"success": True, "payload": {"views": views, "totalViews": len(views)}}

    async def query_base(
        self,
        file: Optional[str] = None,
        path: Optional[str] = None,
        view: Optional[str] = None,
        format: str = "json",
        vault_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(self.cli.query_base, vault, file, path, view, format, limit)

    async def create_base_item(
        self,
        file: Optional[str] = None,
        path: Optional[str] = None,
        view: Optional[str] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
        vault_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        vault, err = self._resolve_vault(vault_id)
        if err:
            return err
        return await asyncio.to_thread(
            self.cli.create_base_item, vault, file, path, view, name, content
        )

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
