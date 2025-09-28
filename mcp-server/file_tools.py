"""
File management tools for interacting with Obsidian notes and vaults.
These tools use the WebSocket server to communicate with the Obsidian plugin.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING, cast
from websocket_server import WebSocketServer

if TYPE_CHECKING:
    from remote_rpc_bridge import RemoteRPCBridge
else:
    try:
        from remote_rpc_bridge import RemoteRPCBridge
    except ImportError:
        RemoteRPCBridge = None

logger = logging.getLogger(__name__)


class FileTools:
    """File management tools for Obsidian integration.

    Accepts either a local WebSocketServer or remote RemoteRPCBridge for inter-process communication.
    Both provide the same interface for file operations and vault management.
    """

    def __init__(self, server: Union[WebSocketServer, "RemoteRPCBridge"]):
        """Initialize FileTools with either local WebSocket server or remote RPC bridge.

        Args:
            server: Either a WebSocketServer instance or RemoteRPCBridge instance
        """
        self.server = server

    def _snake_to_camel(self, snake_str: str) -> str:
        """Convert snake_case to camelCase"""
        components = snake_str.split('_')
        return components[0] + ''.join(word.capitalize() for word in components[1:])

    async def _validate_vault_connection(self, vault_id: Optional[str] = None) -> tuple[str, None] | tuple[None, dict]:
        """
        Validate vault connection and resolve vault ID.

        Args:
            vault_id: Optional vault ID to validate. If None, uses active vault.

        Returns:
            tuple: (resolved_vault_id, error_dict) where error_dict is None if validation succeeds
        """
        try:
            # Use injected WebSocket server instance
            server = self.server

            if not server:
                return (None, {"success": False, "error": "WebSocket server not available", "error_code": "NO_SERVER"})

            # Get connected vaults - handle both sync and async server implementations
            if hasattr(server, 'get_connected_vaults') and asyncio.iscoroutinefunction(server.get_connected_vaults):
                connected_vaults = await server.get_connected_vaults()
            else:
                connected_vaults = server.get_connected_vaults()
            
            if hasattr(server, 'get_all_vault_info') and asyncio.iscoroutinefunction(server.get_all_vault_info):
                all_vault_info = await server.get_all_vault_info()
            else:
                all_vault_info = server.get_all_vault_info()
            
            if hasattr(server, 'get_active_vault') and asyncio.iscoroutinefunction(server.get_active_vault):
                active_vault_debug = cast(Optional[str], await server.get_active_vault())
            else:
                active_vault_debug = cast(Optional[str], server.get_active_vault())

            vault_list = list(cast(List[str], connected_vaults)) if connected_vaults else []
            if not vault_list:
                return (None, {"success": False, "error": "No Obsidian vaults are currently connected", "error_code": "NO_VAULTS"})

            # Validate vault_id if provided
            if vault_id is not None:
                # Ensure connected_vaults is a list for membership check
                if vault_id not in vault_list:
                    return (None, {"success": False, "error": f"Vault '{vault_id}' is not connected. Connected vaults: {vault_list}", "error_code": "INVALID_VAULT"})
                return (vault_id, None)

            # Use active vault if None provided - use the already fetched value
            active_vault = str(active_vault_debug) if active_vault_debug else None

            if not active_vault:
                return (None, {"success": False, "error": f"No vault specified and no active vault set. Connected vaults: {vault_list}", "error_code": "NO_ACTIVE_VAULT"})

            return (active_vault, None)

        except Exception as e:
            logger.error(f"Error validating vault connection: {e}")
            return (None, {"success": False, "error": str(e), "error_code": "VALIDATION_ERROR"})

    async def search_obsidian_notes(self, query: str, vault_id: Optional[str] = None, search_mode: str = "both", max_results: int = 100, include_context: bool = True, path: Optional[str] = None) -> Dict[str, Any]:
        """Search for notes in Obsidian vault by filename and/or content.

        Args:
            query: Search query string
            vault_id: Optional vault ID
            search_mode: What to search - 'filename', 'content', or 'both' (default: 'both')
            max_results: Maximum number of results to return (default: 100)
            include_context: Whether to include context snippets for content matches (default: True)
            path: Optional path to restrict search within the vault

        Returns:
            Dict with search results including paths, match types, and optional context
        """
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        # Validate search_mode
        valid_modes = {'filename', 'content', 'both'}
        if (search_mode or "").lower() not in valid_modes:
            logger.info(
                f"[SEARCH] Invalid search_mode '{search_mode}' provided; defaulting to 'both'")
            search_mode = 'both'
        else:
            search_mode = (search_mode or "both").lower()

        # Coerce numeric/bool types defensively
        try:
            max_results = int(max_results)
        except Exception:
            logger.info(
                f"[SEARCH] Could not coerce max_results '{max_results}' to int; defaulting to 100")
            max_results = 100
        include_context = bool(include_context)

        params = {
            "query": query,
            "searchMode": search_mode,
            "maxResults": max_results,
            "includeContext": include_context,
            "vaultId": resolved_vault_id
        }
        # Include optional path when provided
        if path:
            params["path"] = path

        logger.info(
            f"[SEARCH] Searching notes (mode={search_mode}, max={max_results}, path={path}) for query: '{query}'")

        response = await self.server.request_file_operation(resolved_vault_id, "file:search", params)
        return response or {"error": "No response from vault"}

    async def read_obsidian_note(self, path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Read a specific note from Obsidian."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": path,
            "vaultId": resolved_vault_id
        }

        response = await self.server.request_file_operation(resolved_vault_id, "file:read", params)
        return response or {"error": "No response from vault"}

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
        editor_method: Optional[str] = None,
        # Direct parameters for editor operations - following working pattern
        line: Optional[int] = None,
        char: Optional[int] = None,
        fromLine: Optional[int] = None,
        fromChar: Optional[int] = None,
        toLine: Optional[int] = None,
        toChar: Optional[int] = None,
        heading: Optional[str] = None,
        **editor_params
    ) -> Dict[str, Any]:
        """
        Update an existing Obsidian note with support for multiple editing modes

        Args:
            path: Path to the note
            content: Full content for full_file mode (optional for other modes)
            vault_id: Vault identifier
            editing_mode: One of "full_file", "frontmatter_only", "append_only", "range_based", "editor_based"
            frontmatter_changes: Dict of frontmatter changes for frontmatter_only mode
            append_content: Content to append for append_only mode
            replacement_content: Content to replace range for range_based mode
            range_start_line: Starting line number for range_based mode
            range_start_char: Starting character position for range_based mode
            range_end_line: Ending line number for range_based mode (optional)
            range_end_char: Ending character position for range_based mode (optional)
            editor_method: Method name for editor_based mode
            **editor_params: Additional parameters for editor_based mode
        """
        logger.info(f"Updating Obsidian note: {path} (mode: {editing_mode})")

        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        # Parameter validation based on editing mode
        if editing_mode == "full_file":
            if content is None:
                return {"success": False, "error": "content parameter required for full_file mode"}
            operation = "file:write"
            params = {
                "path": path,
                "content": content,
                "vaultId": resolved_vault_id
            }
        elif editing_mode == "frontmatter_only":
            if frontmatter_changes is None:
                return {"success": False, "error": "frontmatter_changes parameter required for frontmatter_only mode"}
            operation = "file:frontmatter_edit"
            params = {
                "path": path,
                "vaultId": resolved_vault_id,
                "frontmatterChanges": frontmatter_changes
            }
        elif editing_mode == "append_only":
            if append_content is None:
                return {"success": False, "error": "append_content parameter required for append_only mode"}
            operation = "file:append"
            params = {
                "path": path,
                "vaultId": resolved_vault_id,
                "appendContent": append_content
            }
        elif editing_mode == "range_based":
            if replacement_content is None or range_start_line is None or range_start_char is None:
                return {"success": False, "error": "replacement_content, range_start_line, and range_start_char parameters required for range_based mode"}
            operation = "file:range_edit"
            params = {
                "path": path,
                "vaultId": resolved_vault_id,
                "replacementContent": replacement_content,
                "rangeStartLine": range_start_line,
                "rangeStartChar": range_start_char
            }
            if range_end_line is not None:
                params["rangeEndLine"] = range_end_line
            if range_end_char is not None:
                params["rangeEndChar"] = range_end_char
        elif editing_mode == "editor_based":
            if editor_method is None:
                return {"success": False, "error": "editor_method parameter required for editor_based mode"}
            operation = "file:editor_edit"
            params = {
                "path": path,
                "vaultId": resolved_vault_id,
                "editorMethod": editor_method
            }
            # Include content parameter if provided - following working pattern
            if content is not None:
                params["content"] = content
            if replacement_content is not None:
                params["content"] = replacement_content
            if append_content is not None:
                params["content"] = append_content
            # Include direct parameters - following working pattern like frontmatter_only
            # Convert to strings for dict compatibility (TypeScript will parse back to numbers)
            if line is not None:
                params["line"] = str(line)
            if char is not None:
                params["char"] = str(char)
            if fromLine is not None:
                params["fromLine"] = str(fromLine)
            if fromChar is not None:
                params["fromChar"] = str(fromChar)
            if toLine is not None:
                params["toLine"] = str(toLine)
            if toChar is not None:
                params["toChar"] = str(toChar)
            if heading is not None:
                params["heading"] = str(heading)
        else:
            return {"success": False, "error": f"Invalid editing_mode: {editing_mode}. Must be one of: full_file, frontmatter_only, append_only, range_based, editor_based"}

        try:
            response = await self.server.request_file_operation(resolved_vault_id, operation, params)
            if response and response.get("success"):
                logger.info(
                    f"Successfully updated note: {path} (mode: {editing_mode})")
                return response
            else:
                logger.error(
                    f"Failed to update note: {path} (mode: {editing_mode}) - {response.get('error', 'Unknown error') if response else 'No response'}")
                return response or {"success": False, "error": "No response from vault"}
        except Exception as e:
            logger.error(
                f"Error updating note {path} (mode: {editing_mode}): {str(e)}")
            return {"success": False, "error": str(e)}

    async def create_obsidian_note(self, path: str, content: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new note in Obsidian."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": path,
            "content": content,
            "vaultId": resolved_vault_id
        }

        response = await self.server.request_file_operation(resolved_vault_id, "file:create", params)
        return response or {"error": "No response from vault"}

    async def list_obsidian_vaults(self) -> Dict[str, Any]:
        """
        List all available Obsidian vaults by requesting them from the plugin.
        """
        try:
            if not self.server:
                return {"success": False, "error": "WebSocket server not available", "error_code": "NO_SERVER"}

            # This operation needs a client to talk to, but it can be any client.
            # We'll pick the first available one. If none, we can't proceed.
            # Handle both sync (WebSocketServer) and async (RemoteRPCBridge) modes
            if hasattr(self.server, 'get_connected_vaults') and asyncio.iscoroutinefunction(self.server.get_connected_vaults):
                connected_clients = await self.server.get_connected_vaults()
            else:
                connected_clients = self.server.get_connected_vaults()

            client_list = list(cast(List[str], connected_clients)) if connected_clients else []
            if not client_list:
                return {
                    "success": False,
                    "error": "No Obsidian clients are currently connected. Please restart Obsidian and ensure the MCP plugin is enabled and connected.",
                    "error_code": "NO_CLIENTS",
                    "user_action": "restart_obsidian"
                }

            # Send the request to the first available client
            target_vault_id = client_list[0]

            response = await self.server.request_file_operation(target_vault_id, "vault:list", {})
            return response or {"success": False, "error": "No response from vault for list_vaults request"}

        except Exception as e:
            logger.error(f"Error listing vaults: {e}")
            return {
                "success": False,
                "error": f"Failed to list vaults: {str(e)}. Try restarting Obsidian and ensuring the MCP plugin is properly connected.",
                "error_code": "LIST_VAULTS_ERROR",
                "user_action": "restart_obsidian"
            }

    async def delete_obsidian_note(self, path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Delete a note from Obsidian."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": path,
            "vaultId": resolved_vault_id
        }

        response = await self.server.request_file_operation(resolved_vault_id, "file:delete", params)
        return response or {"error": "No response from vault"}

    async def list_obsidian_notes(self, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """List all notes in a vault."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "vaultId": resolved_vault_id
        }

        response = await self.server.request_file_operation(resolved_vault_id, "file:list", params)
        return response or {"error": "No response from vault"}

    async def get_obsidian_note_metadata(self, path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Get metadata for a specific note."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": path,
            "vaultId": resolved_vault_id
        }

        response = await self.server.request_file_operation(resolved_vault_id, "file:metadata", params)
        return response or {"error": "No response from vault"}

    async def explore_vault_folders(
        self,
        path: str = "",
        query: str = "",
        format: str = "smart",
        max_depth: int = 3,
        vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Explore folder structure in the vault.

        Parameters:
            path: explicit path to explore (preferred if provided)
            query: natural language or path query to focus exploration (e.g., 'archive', 'projects/2025')
            format: one of ['tree', 'flat', 'paths', 'smart']
            max_depth: max recursion depth for folder traversal
            vault_id: optional vault id

        Behavior:
            - Validates vault
            - Sends a 'folder:explore' request to the plugin via request_file_operation
            - Uses a standardized response structure:
              {
                success: bool,
                results: [...],
                totalFolders: int,
                formatUsed: str,
                query: Optional[str],
                path: Optional[str],
                vaultId: str
              }
        """
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        # Normalize format
        allowed_formats = {"tree", "flat", "paths", "smart"}
        fmt = (format or "smart").lower()
        if fmt not in allowed_formats:
            fmt = "smart"

        params = {
            "format": fmt,
            "maxDepth": int(max_depth),
            "vaultId": resolved_vault_id
        }

        # Prefer explicit path when provided
        if path:
            params["path"] = path
        elif query:
            params["query"] = query
        else:
            # Request root listing when neither provided
            params["path"] = "/"

        try:
            # Request the folder exploration from the plugin
            response = await self.server.request_file_operation(resolved_vault_id, "folder:explore", params, timeout=30.0)

            # Normalize plugin response into expected structure
            if response is None:
                return {"success": False, "error": "No response from vault", "vaultId": resolved_vault_id}

            # If plugin returned structured result with payload, unwrap
            if isinstance(response, dict) and "payload" in response and response.get("success", True):
                payload = response.get("payload", {})
                success_flag = bool(response.get("success", True))
            else:
                payload = response if isinstance(response, dict) else {
                    "raw": response}
                success_flag = True

            results = payload.get("results") if isinstance(
                payload, dict) else None
            total = payload.get("totalFolders") if isinstance(
                payload, dict) else None

            # Fallbacks to common keys
            if results is None:
                results = payload.get("folders") if isinstance(
                    payload, dict) else []
            if total is None:
                total = len(results) if isinstance(results, list) else 0

            # Ensure results is a list
            if results is None:
                results = []
            if not isinstance(results, list):
                results = [results]

            # If plugin returned no folders, synthesize root entry so client sees something
            if len(results) == 0:
                root_entry = {"path": params.get(
                    "path", "/"), "name": "", "type": "folder"}
                results = [root_entry]
                total = 1

            return {
                "success": success_flag,
                "results": results,
                "totalFolders": total,
                "formatUsed": fmt,
                "query": query or None,
                "path": path or params.get("path"),
                "vaultId": resolved_vault_id
            }
        except Exception as e:
            logger.error(f"Error exploring vault folders: {e}")
            return {"success": False, "error": str(e), "vaultId": resolved_vault_id}

    async def create_note_with_template(
        self,
        request_type: str,
        file_name: str,
        content: str = "",
        target_folder: str = "",
        vault_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new note using a template discovered in the vault via the plugin.
        This performs:
         - templater:check
         - file:create_with_template

        Behavior improvements:
        - Trust plugin-provided templateMappings (use as-is; do not attempt date expansion here)
        - If target_folder not provided, MCP will look up matched_template in templateMappings and use the mapping exactly
        - Includes templateMappings and resolved targetFolder in all responses for traceability
        - Logs mapping and folder decisions using logger
        """
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        try:
            # 1) Ask plugin if templater is available and list templates
            templater_check = await self.server.request_file_operation(resolved_vault_id, "templater:check", {})
            if templater_check is None:
                return {"success": False, "error": "No response from vault for templater:check"}

            # Normalize response shapes (support payload-wrapped and direct responses)
            templater_payload = templater_check.get("payload") if isinstance(
                templater_check, dict) and "payload" in templater_check else templater_check
            success_flag = bool(templater_check.get("success", True)) if isinstance(
                templater_check, dict) else True

            if not success_flag:
                return {"success": False, "error": "Templater check failed", "details": templater_check}

            if not isinstance(templater_payload, dict):
                # If payload is a simple list or other type, coerce into dict
                templater_payload = {"templates": templater_payload}

            # Extract mappings and templates
            is_installed = templater_payload.get("isInstalled", False)
            templates = templater_payload.get("templates", []) if isinstance(
                templater_payload, dict) else []
            template_mappings = templater_payload.get(
                "templateMappings", {}) if isinstance(templater_payload, dict) else {}

            # Log mapping and available templates
            logger.info(
                f"[TEMPLATE] templater_check is_installed={is_installed}, templates_count={len(templates) if isinstance(templates, list) else 0}")
            logger.info(
                f"[TEMPLATE] templateMappings received: {template_mappings}")

            # Attempt to find best matching template name (exact => fuzzy)
            matched_template: Optional[str] = None
            request_lower = (request_type or "").lower()

            # templates might be list of strings or dicts with basename
            for t in (templates or []):
                tname = t.get("basename") if isinstance(t, dict) else t
                if not isinstance(tname, str):
                    continue
                if tname == request_type:
                    matched_template = tname
                    break
                # fuzzy contains check
                if request_lower and (request_lower in tname.lower() or tname.lower() in request_lower):
                    matched_template = tname

            # If target_folder not provided, try mapping
            resolved_target_folder = (target_folder or "").strip()
            if not resolved_target_folder and matched_template:
                mapped = template_mappings.get(matched_template, "") if isinstance(
                    template_mappings, dict) else ""
                if mapped:
                    resolved_target_folder = mapped
                    logger.info(
                        f"[TEMPLATE] Using mapped folder '{resolved_target_folder}' for template '{matched_template}'")

            if not resolved_target_folder:
                logger.info(
                    "[TEMPLATE] No target folder determined; leaving blank so plugin may choose default (e.g., inbox or root)")

            # 2) Build params and request creation via plugin (plugin will choose best-match and fallback if needed)
            params = {
                "searchTerm": request_type,
                "fileName": file_name,
                "targetFolder": resolved_target_folder,
                "userContent": content or "",
                # include mappings so plugin has context if needed
                "templateMappings": template_mappings
            }

            logger.info(
                f"[TEMPLATE] Calling file:create_with_template with params: searchTerm={request_type}, fileName={file_name}, targetFolder='{resolved_target_folder}'")

            create_resp = await self.server.request_file_operation(resolved_vault_id, "file:create_with_template", params)
            if create_resp is None:
                return {
                    "success": False,
                    "error": "No response from vault for file:create_with_template",
                    "params": params,
                    "templateMappings": template_mappings
                }

            # Handle two-call flow: exact-match or requiresSelection
            if isinstance(create_resp, dict) and create_resp.get("requiresSelection"):
                available = create_resp.get("availableTemplates") or []
                return {
                    "success": False,
                    "requiresSelection": True,
                    "availableTemplates": available,
                    "message": create_resp.get("error") or "Template selection required",
                    "details": create_resp,
                    "templateMappings": template_mappings,
                    "suggestedFolder": resolved_target_folder
                }

            # Normalize plugin create response
            if isinstance(create_resp, dict):
                if create_resp.get("success", True) is False:
                    # Include mappings for debugging
                    return {
                        "success": False,
                        "error": "Vault failed to create file with template",
                        "details": create_resp,
                        "templateMappings": template_mappings,
                        "suggestedFolder": resolved_target_folder
                    }

                payload = create_resp.get(
                    "payload") if "payload" in create_resp else create_resp
                created_path = payload.get("path") if isinstance(
                    payload, dict) else None
                template_used = payload.get("templateUsed") if isinstance(
                    payload, dict) else matched_template

                result = {
                    "success": True,
                    "vaultId": resolved_vault_id,
                    "path": created_path,
                    "targetFolder": resolved_target_folder,
                    "templateUsed": template_used,
                    "templateMappings": template_mappings,
                    "payload": payload
                }
                return result
            else:
                return {
                    "success": True,
                    "vaultId": resolved_vault_id,
                    "result": create_resp,
                    "targetFolder": resolved_target_folder,
                    "templateMappings": template_mappings
                }

        except Exception as e:
            logger.error("Error in create_note_with_template", exc_info=True)
            return {"success": False, "error": str(e)}


    async def create_obsidian_folder(self, folder_path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new folder in Obsidian vault."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "folderPath": folder_path,
            "vaultId": resolved_vault_id
        }

        logger.info(f"[FOLDER] Creating folder: {folder_path}")
        response = await self.server.request_file_operation(resolved_vault_id, "folder:create", params)
        return response or {"error": "No response from vault"}

    async def rename_obsidian_folder(self, folder_path: str, new_folder_path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Rename/move a folder in Obsidian vault."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "oldPath": folder_path,
            "newPath": new_folder_path,
            "vaultId": resolved_vault_id
        }

        logger.info(
            f"[FOLDER] Renaming folder: {folder_path} -> {new_folder_path}")
        response = await self.server.request_file_operation(resolved_vault_id, "folder:rename", params)
        return response or {"error": "No response from vault"}

    async def delete_obsidian_folder(self, folder_path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Delete a folder from Obsidian vault."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": folder_path,
            "vaultId": resolved_vault_id
        }

        logger.info(f"[FOLDER] Deleting folder: {folder_path}")
        response = await self.server.request_file_operation(resolved_vault_id, "folder:delete", params)
        return response or {"error": "No response from vault"}

    async def rename_obsidian_note(self, old_path: str, new_path: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
        """Rename/move a note in Obsidian vault."""
        # Validate vault connection
        resolved_vault_id, error = await self._validate_vault_connection(vault_id)
        if error is not None:
            return error
        
        # Type guard: resolved_vault_id is guaranteed to be str here
        assert resolved_vault_id is not None

        params = {
            "path": old_path,
            "newPath": new_path,
            "vaultId": resolved_vault_id
        }

        logger.info(f"[NOTE] Renaming note: {old_path} -> {new_path}")
        response = await self.server.request_file_operation(resolved_vault_id, "file:rename", params)
        return response or {"error": "No response from vault"}
