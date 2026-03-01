"""
Obsidian CLI subprocess wrapper for MegaMem MCP file operations.
Replaces WebSocket-based file operations with stateless CLI subprocess calls.

Requires: Obsidian 1.12.4+ with CLI registered (Obsidian Settings → CLI → Register CLI)

@purpose: Provide all 9 MegaMem file operation tools via obsidian CLI subprocess
@depends: Obsidian 1.12.4+ installed, Obsidian.com on PATH or at known platform path
@results: MegaMem standard response envelopes for drop-in WebSocket replacement
"""

import json
import logging
import os
import platform
import shutil
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Binary Detection ─────────────────────────────────────────────────────────


def detect_obsidian_binary() -> Optional[str]:
    """
    Find the Obsidian CLI binary path on the current platform.

    Windows: Obsidian.com is the terminal I/O redirector (NOT Obsidian.exe).
    macOS: Main binary inside the .app bundle.
    Linux: Symlink created by Obsidian registration.
    """
    system = platform.system()

    if system == "Windows":
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Obsidian\Obsidian.com"),
            os.path.expandvars(r"%APPDATA%\Obsidian\Obsidian.com"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                logger.info(f"[CLI] Found Obsidian binary at: {path}")
                return path

    elif system == "Darwin":
        mac_path = "/Applications/Obsidian.app/Contents/MacOS/Obsidian"
        if os.path.isfile(mac_path):
            return mac_path

    else:  # Linux
        linux_candidates = [
            "/usr/local/bin/obsidian",
            os.path.expanduser("~/.local/bin/obsidian"),
        ]
        for path in linux_candidates:
            if os.path.isfile(path):
                return path

    # Fallback: check PATH
    return shutil.which("obsidian") or shutil.which("Obsidian.com")


# ─── ObsidianCLI ────────────────────────────────────────────────────────────


class ObsidianCLI:
    """
    Stateless subprocess wrapper for all Obsidian CLI file operations.

    Each method call spawns a single subprocess, captures output, parses it,
    and returns the standard MegaMem response envelope. No persistent connection.

    Usage:
        cli = ObsidianCLI(binary="/path/to/Obsidian.com")
        result = cli.read_obsidian_note(vault="MyVault", path="folder/note.md")
    """

    def __init__(self, binary: str):
        self.binary = binary

    @classmethod
    def from_detected_binary(cls) -> "ObsidianCLI":
        """Auto-detect binary and return a ready instance."""
        path = detect_obsidian_binary()
        if not path:
            raise RuntimeError(
                "Obsidian CLI not found. "
                "Install Obsidian 1.12.4+ and enable CLI via Settings → General → CLI."
            )
        return cls(path)

    # ─── Internal Helpers ────────────────────────────────────────────────────

    def _run(self, vault: str, *args: str, timeout: int = 30) -> tuple[str, int]:
        """Run a vault-scoped CLI command. Returns (stdout, exit_code)."""
        cmd = [self.binary, f"vault={vault}", *args]
        logger.debug(f"[CLI] {cmd[0]} vault={vault} {args[0] if args else ''}")
        result = subprocess.run(
            cmd, capture_output=True, shell=False,
            text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        stdout = (result.stdout or "").replace("\r\n", "\n").strip()
        return stdout, result.returncode

    def _run_global(self, *args: str, timeout: int = 15) -> tuple[str, int]:
        """Run a vault-agnostic CLI command (vaults, version)."""
        cmd = [self.binary, *args]
        result = subprocess.run(
            cmd, capture_output=True, shell=False,
            text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        stdout = (result.stdout or "").replace("\r\n", "\n").strip()
        return stdout, result.returncode

    def _ok(self, payload: Any) -> dict:
        return {"success": True, "payload": payload, "error": None}

    def _err(self, message: str, error_code: str = "CLI_ERROR") -> dict:
        return {"success": False, "error": message, "error_code": error_code, "payload": {}}

    def _is_error(self, out: str, code: int) -> bool:
        return code != 0 or out.startswith("Error:")

    @staticmethod
    def _auto_md(path: str) -> str:
        """Append .md if the path doesn't already end with .md.
        Uses endswith check rather than dot-in-basename to avoid false positives
        on note names like 'Day45.01 - Some Note' which contain dots but have no extension.
        """
        return path if path.lower().endswith(".md") else path + ".md"

    def version(self) -> str:
        """Return Obsidian version string."""
        out, _ = self._run_global("version")
        return out

    # ─── Tool 1: search_obsidian_notes ───────────────────────────────────────

    def search_obsidian_notes(
        self,
        vault: str,
        query: str,
        search_mode: str = "both",
        max_results: int = 100,
        include_context: bool = True,
        path: Optional[str] = None,
    ) -> dict:
        """
        Search vault notes. search_mode=filename uses 'obsidian files' + client-side filter.
        search_mode=content|both uses search:context with full-text matching.
        """
        if search_mode == "filename":
            return self._search_by_filename(vault, query, max_results, path)

        args = ["search:context", f"query={query}", f"limit={max_results}", "format=json"]
        if path:
            args.append(f"path={path}")

        out, code = self._run(vault, *args)
        if self._is_error(out, code):
            return self._err(out or "Search failed")

        try:
            raw: list[dict] = json.loads(out) if out else []
        except json.JSONDecodeError:
            raw = []

        results = []
        for item in raw:
            file_path = item.get("file", "")
            matches = item.get("matches", [])
            basename = os.path.splitext(os.path.basename(file_path))[0]
            ext = os.path.splitext(file_path)[1].lstrip(".")
            entry: dict = {
                "path": file_path,
                "name": f"{basename}.{ext}" if ext else basename,
                "basename": basename,
                "extension": ext,
                "matchType": "content",
                "score": 100.0,
            }
            if include_context and matches:
                entry["context"] = matches[0].get("text", "")[:300]
                entry["matchLine"] = matches[0].get("line", 0)
                entry["allMatches"] = matches
            results.append(entry)

        return self._ok({
            "results": results,
            "totalResults": len(results),
            "query": query,
            "searchMode": search_mode,
        })

    def _search_by_filename(
        self,
        vault: str,
        query: str,
        max_results: int = 100,
        path: Optional[str] = None,
    ) -> dict:
        """Client-side filename search using 'obsidian files' listing + filter."""
        args = ["files"]
        if path and path != "/":
            args.append(f"folder={path}")
        out, code = self._run(vault, *args)
        if code != 0:
            return self._err(out or "File listing failed for filename search")

        # Split query into words — all must appear in basename or full path (order-independent)
        query_words = query.lower().split()

        def _matches(text: str) -> bool:
            t = text.lower()
            return all(w in t for w in query_words)

        results = []
        for file_path in out.strip().splitlines():
            if not file_path:
                continue
            basename = os.path.splitext(os.path.basename(file_path))[0]
            if _matches(basename) or _matches(file_path):
                ext = os.path.splitext(file_path)[1].lstrip(".")
                results.append({
                    "path": file_path,
                    "name": f"{basename}.{ext}" if ext else basename,
                    "basename": basename,
                    "extension": ext,
                    "matchType": "filename",
                    "score": 100.0,
                })
                if len(results) >= max_results:
                    break

        return self._ok({
            "results": results,
            "totalResults": len(results),
            "query": query,
            "searchMode": "filename",
        })

    # ─── Tool 2: read_obsidian_note ──────────────────────────────────────────

    def read_obsidian_note(
        self,
        vault: str,
        path: str,
        include_line_map: bool = False,
    ) -> dict:
        """Read a note's full content including frontmatter."""
        path = self._auto_md(path)
        out, code = self._run(vault, "read", f"path={path}")
        if self._is_error(out, code):
            return self._err(out or f"File not found: {path}", "FILE_NOT_FOUND")

        payload: dict = {
            "content": out,
            "path": path,
            "metadata": {"size": len(out.encode("utf-8")), "lastModified": None},
        }

        if include_line_map:
            lines = out.split("\n")
            payload["metadata"].update({
                "totalLines": len(lines),
                "lineMap": {str(i + 1): l for i, l in enumerate(lines)},
                "sections": self._detect_sections(lines),
            })

        return self._ok(payload)

    def _detect_sections(self, lines: list[str]) -> list[dict]:
        """Detect frontmatter and body sections from content lines."""
        sections: list[dict] = []
        in_fm = False
        fm_start = -1
        for i, line in enumerate(lines, 1):
            if line.strip() == "---":
                if not in_fm and i == 1:
                    in_fm, fm_start = True, i
                elif in_fm:
                    sections.append({"name": "frontmatter", "startLine": fm_start, "endLine": i})
                    in_fm = False
                    break
        end_of_fm = sections[-1]["endLine"] if sections else 0
        if end_of_fm < len(lines):
            sections.append({"name": "body", "startLine": end_of_fm + 1, "endLine": len(lines)})
        elif not sections and lines:
            sections.append({"name": "body", "startLine": 1, "endLine": len(lines)})
        return sections

    # ─── Tool 3: create_obsidian_note ────────────────────────────────────────

    def create_obsidian_note(
        self,
        vault: str,
        path: str,
        content: str = "",
    ) -> dict:
        """
        Create or overwrite a note. Auto-creates parent directories.
        Content newlines must be passed as literal \\n to the CLI.
        """
        path = self._auto_md(path)
        cli_content = _encode_newlines(content)
        out, code = self._run(vault, "create", f"path={path}", f"content={cli_content}", "overwrite")
        if self._is_error(out, code):
            return self._err(out or "Create failed")
        return self._ok({"path": path, "message": out})

    # ─── Tool 4: update_obsidian_note ────────────────────────────────────────

    def update_obsidian_note(
        self,
        vault: str,
        path: str,
        editing_mode: str = "full_file",
        content: Optional[str] = None,
        append_content: Optional[str] = None,
        frontmatter_changes: Optional[dict] = None,
        replacement_content: Optional[str] = None,
        range_start_line: Optional[int] = None,
        range_end_line: Optional[int] = None,
        **kwargs,
    ) -> dict:
        """
        Update a note using one of several editing modes:
        - full_file: Overwrite entire content
        - append_only: Append to end
        - prepend_only: Prepend after frontmatter
        - frontmatter_only: Set individual frontmatter properties
        - range_based: Replace lines (read→modify→rewrite)
        """
        path = self._auto_md(path)
        if editing_mode == "full_file":
            if content is None:
                return self._err("content required for full_file mode")
            out, code = self._run(vault, "create", f"path={path}",
                                  f"content={_encode_newlines(content)}", "overwrite")

        elif editing_mode == "append_only":
            text = append_content or content
            if text is None:
                return self._err("append_content required for append_only mode")
            out, code = self._run(vault, "append", f"path={path}", f"content={_encode_newlines(text)}")

        elif editing_mode == "prepend_only":
            text = content or append_content
            if text is None:
                return self._err("content required for prepend_only mode")
            out, code = self._run(vault, "prepend", f"path={path}", f"content={_encode_newlines(text)}")

        elif editing_mode == "frontmatter_only":
            if not frontmatter_changes:
                return self._err("frontmatter_changes required for frontmatter_only mode")
            for name, value in frontmatter_changes.items():
                val_str = json.dumps(value) if not isinstance(value, str) else value
                out, code = self._run(vault, "property:set", f"name={name}", f"value={val_str}", f"path={path}")
                if self._is_error(out, code):
                    return self._err(f"property:set failed for '{name}': {out}")
            return self._ok({"path": path, "updated": list(frontmatter_changes.keys())})

        elif editing_mode == "range_based":
            if replacement_content is None or range_start_line is None:
                return self._err("replacement_content and range_start_line required for range_based mode")
            read_result = self.read_obsidian_note(vault, path)
            if not read_result["success"]:
                return self._err(f"Could not read note for range edit: {read_result['error']}")
            lines = read_result["payload"]["content"].split("\n")
            end = (range_end_line) if range_end_line else range_start_line
            lines[range_start_line - 1:end] = replacement_content.split("\n")
            out, code = self._run(vault, "create", f"path={path}",
                                  f"content={_encode_newlines(chr(10).join(lines))}", "overwrite")

        else:
            return self._err(f"Unsupported editing_mode: {editing_mode}")

        if self._is_error(out, code):
            return self._err(out or f"Update failed (mode={editing_mode})")
        return self._ok({"path": path, "message": out, "mode": editing_mode})

    # ─── Tool 5: list_obsidian_vaults ────────────────────────────────────────

    def list_obsidian_vaults(self) -> dict:
        """List all known vaults. Returns name + path for each."""
        out, code = self._run_global("vaults", "verbose")
        if self._is_error(out, code):
            return self._err(out or "Could not list vaults")

        vaults = []
        for line in out.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                vaults.append({"name": parts[0], "path": parts[1], "id": parts[0]})
            elif parts[0]:
                vaults.append({"name": parts[0], "path": "", "id": parts[0]})

        return self._ok({"vaults": vaults, "totalVaults": len(vaults)})

    # ─── Tool 6: explore_vault_folders ───────────────────────────────────────

    def explore_vault_folders(
        self,
        vault: str,
        path: Optional[str] = None,
        include_files: bool = False,
        extension_filter: Optional[list] = None,
        max_depth: int = 10,
        query: Optional[str] = None,
    ) -> dict:
        """List folders (and optionally files) in the vault."""
        folder_args = ["folders"]
        if path and path != "/":
            folder_args.append(f"folder={path}")

        out, code = self._run(vault, *folder_args)
        if code != 0:
            return self._err(out or "Could not list folders")

        folders = [
            {"path": p, "name": p.split("/")[-1] or p, "type": "folder"}
            for p in out.strip().splitlines() if p
        ]

        result: dict = {
            "success": True,
            "results": folders,
            "totalFolders": len(folders),
            "path": path or "/",
            "vaultId": vault,
        }

        if include_files:
            file_args = ["files"]
            if path and path != "/":
                file_args.append(f"folder={path}")
            if extension_filter:
                for ext in extension_filter:
                    file_args.append(f"ext={ext.lstrip('.')}")
            fout, fcode = self._run(vault, *file_args)
            files = [
                {"path": p, "name": p.split("/")[-1], "type": "file"}
                for p in fout.strip().splitlines() if p
            ] if fcode == 0 else []
            result["files"] = files
            result["totalFiles"] = len(files)

        return result

    # ─── Tool 7: create_note_with_template ───────────────────────────────────

    def create_note_with_template(
        self,
        vault: str,
        request_type: str,
        file_name: str,
        content: str = "",
        target_folder: str = "",
    ) -> dict:
        """
        Create a note from a Templater template via eval.
        Uses Templater's create_new_note_from_template() — fully non-interactive.
        Template is matched by basename (fuzzy: request_type contains template name or vice versa).
        """
        # Escape for safe single-quote JS string embedding
        safe_request = request_type.replace("'", "\\'")
        safe_filename = file_name.replace("'", "\\'")
        safe_folder = target_folder.replace("'", "\\'")

        js = (
            "(async () => {"
            " const tp = app.plugins.getPlugin('templater-obsidian').templater;"
            " if (!tp) return JSON.stringify({error: 'Templater not available'});"
            f" const rt = '{safe_request}'.toLowerCase();"
            " const tplFile = app.vault.getFiles().find(f => {"
            "   const bn = f.basename.toLowerCase();"
            "   return bn === rt || bn.includes(rt) || rt.includes(bn);"
            " });"
            " if (!tplFile) return JSON.stringify({error: 'Template not found: ' + rt});"
            f" const folderPath = '{safe_folder}';"
            " const folder = folderPath"
            "   ? (app.vault.getAbstractFileByPath(folderPath) || app.vault.getRoot())"
            "   : app.vault.getRoot();"
            f" const result = await tp.create_new_note_from_template(tplFile, folder, '{safe_filename}', false);"
            " return result ? result.path : JSON.stringify({error: 'No file created'});"
            "})()"
        )

        out, code = self._run(vault, "eval", f"code={js}", timeout=60)
        if code != 0 or (out.startswith("Error:") and "not defined" not in out):
            return self._err(out or "Template creation failed via eval")

        result_val = out.lstrip("=> ").strip()
        if result_val.startswith("{"):
            try:
                err_obj = json.loads(result_val)
                return self._err(err_obj.get("error", "Template creation failed"))
            except json.JSONDecodeError:
                pass

        created_path = result_val

        # Optionally append user-provided content after template
        if content and created_path and not created_path.startswith("{"):
            self._run(vault, "append", f"path={created_path}", f"content={_encode_newlines(content)}")

        return self._ok({
            "path": created_path,
            "message": f"Created from template: {request_type}",
            "templateUsed": request_type,
        })

    # ─── Tool 8: manage_obsidian_notes ───────────────────────────────────────

    def manage_obsidian_notes(
        self,
        vault: str,
        operation: str,
        path: str,
        new_path: Optional[str] = None,
    ) -> dict:
        """Rename or delete a note. Rename updates internal wikilinks."""
        path = self._auto_md(path)
        if new_path:
            new_path = self._auto_md(new_path)
        if operation == "rename":
            if not new_path:
                return self._err("new_path required for rename operation")

            src_folder = os.path.dirname(path)
            dst_folder = os.path.dirname(new_path)
            src_name = os.path.splitext(os.path.basename(path))[0]
            dst_name = os.path.splitext(os.path.basename(new_path))[0]
            folder_changed = src_folder != dst_folder
            name_changed = src_name != dst_name

            if not folder_changed and not name_changed:
                return self._err(f"Source and destination are identical: {path}")

            if folder_changed:
                # Cross-folder move: obsidian move path=<src> to=<dst_folder>
                out, code = self._run(vault, "move", f"path={path}", f"to={dst_folder}")
                if self._is_error(out, code):
                    return self._err(out or f"Move failed: {path} -> {dst_folder}")
                if name_changed:
                    # Name also changed — rename at new location
                    moved_path = f"{dst_folder}/{os.path.basename(path)}" if dst_folder else os.path.basename(path)
                    out, code = self._run(vault, "rename", f"path={moved_path}", f"name={dst_name}")
            else:
                # Same folder, filename-only rename
                out, code = self._run(vault, "rename", f"path={path}", f"name={dst_name}")

        elif operation == "delete":
            out, code = self._run(vault, "delete", f"path={path}")

        else:
            return self._err(f"Unsupported operation: {operation}. Use 'rename' or 'delete'.")

        if self._is_error(out, code):
            return self._err(out or f"Operation '{operation}' failed on: {path}")

        return self._ok({"path": path, "newPath": new_path, "operation": operation, "message": out})

    # ─── Tool 9: manage_obsidian_folders ─────────────────────────────────────

    def manage_obsidian_folders(
        self,
        vault: str,
        operation: str,
        folder_path: str,
        new_folder_path: Optional[str] = None,
    ) -> dict:
        """
        Create, rename, or delete a vault folder.
        Create: uses app.vault.createFolder() via eval (reliable, no placeholder workaround)
        Rename/Delete: uses obsidian eval with vault adapter API
        """
        if operation == "create":
            # Use Obsidian vault API directly — more reliable than .keep workaround
            safe_path = folder_path.replace("'", "\\'")
            js = f"app.vault.createFolder('{safe_path}').then(()=>'ok').catch(e=>e.message)"
            out, code = self._run(vault, "eval", f"code={js}")
            result_val = out.lstrip("=> ").strip()
            # "Folder already exists" is acceptable — treat as success
            if code != 0 or (result_val not in ("ok", "undefined", "") and "already exists" not in result_val.lower()):
                return self._err(result_val or f"Folder create failed: {folder_path}")
            return self._ok({"folderPath": folder_path, "operation": "create"})

        elif operation == "rename":
            if not new_folder_path:
                return self._err("new_folder_path required for rename")
            safe_old = folder_path.replace("'", "\\'")
            safe_new = new_folder_path.replace("'", "\\'")
            js = f"app.vault.adapter.rename('{safe_old}','{safe_new}').then(()=>'ok').catch(e=>e.message)"
            out, code = self._run(vault, "eval", f"code={js}")
            result_val = out.lstrip("=> ").strip()
            if code != 0 or result_val not in ("ok", "undefined", ""):
                return self._err(result_val or f"Folder rename failed: {folder_path}")
            return self._ok({
                "folderPath": folder_path,
                "newFolderPath": new_folder_path,
                "operation": "rename",
            })

        elif operation == "delete":
            safe_path = folder_path.replace("'", "\\'")
            js = f"app.vault.adapter.rmdir('{safe_path}',true).then(()=>'ok').catch(e=>e.message)"
            out, code = self._run(vault, "eval", f"code={js}")
            result_val = out.lstrip("=> ").strip()
            if code != 0 or result_val not in ("ok", "undefined", ""):
                return self._err(result_val or f"Folder delete failed: {folder_path}")
            return self._ok({"folderPath": folder_path, "operation": "delete"})

        else:
            return self._err(f"Unsupported folder operation: {operation}. Use 'create', 'rename', or 'delete'.")

    # ─── Bonus: trigger_sync ──────────────────────────────────────────────────

    def trigger_sync(self, vault: str, note_path: Optional[str] = None) -> dict:
        """
        Trigger MegaMem sync via the registered 'megamem-mcp:sync-current-note' command.
        If note_path provided, opens that note first so sync targets the correct file.
        """
        if note_path:
            self._run(vault, "open", f"path={note_path}")
        out, code = self._run(vault, "command", "id=megamem-mcp:sync-current-note")
        if code != 0:
            return self._err(out or "Sync trigger failed")
        return self._ok({"message": out, "notePath": note_path})


    # ─── Periodic Notes & Template Mappings ──────────────────────────────────

    def get_template_mappings(self, vault: str, vault_path: Optional[str] = None) -> dict:
        """
        Replaces WebSocket 'templater:check' — returns templates list + templateMappings
        with Periodic Notes folder paths calculated from the Periodic Notes plugin config.

        vault_path: Absolute filesystem path to the vault root (from list_obsidian_vaults).
        If not provided, falls back to eval-based config reading from the running app.
        """
        # 1) Get all template files
        tpl_out, _ = self._run(vault, "files", "folder=06_Resources/Templates", "ext=md")
        templates = [
            {"path": p, "name": p.split("/")[-1], "basename": p.split("/")[-1].replace(".md", "")}
            for p in tpl_out.strip().splitlines() if p
        ]

        # 2) Read Periodic Notes config — prefer filesystem read (no Obsidian running needed)
        periodic_config = {}
        if vault_path:
            pn_config_path = os.path.join(vault_path, ".obsidian", "plugins", "periodic-notes", "data.json")
            try:
                with open(pn_config_path, encoding="utf-8") as f:
                    periodic_config = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        # Fallback: eval-based config reading from running Obsidian
        if not periodic_config:
            js = (
                "(()=>{"
                " const pn = app.plugins.getPlugin('periodic-notes');"
                " if (!pn) return '{}';"
                " return JSON.stringify(pn.settings || {});"
                "})()"
            )
            eval_out, _ = self._run(vault, "eval", f"code={js}")
            raw = eval_out.lstrip("=> ").strip()
            try:
                periodic_config = json.loads(raw) if raw and raw != "'{}'" else {}
            except json.JSONDecodeError:
                periodic_config = {}

        # 3) Build templateMappings — maps template basename → target folder
        template_mappings: dict[str, str] = {}
        if periodic_config:
            template_mappings.update(_build_periodic_mappings(periodic_config))

        return self._ok({
            "isInstalled": True,
            "templates": templates,
            "templateMappings": template_mappings,
        })

    def get_periodic_notes_config(self, vault: str, vault_path: Optional[str] = None) -> dict:
        """Read Periodic Notes plugin config (folder, format, template for each period type)."""
        result = self.get_template_mappings(vault, vault_path)
        if result["success"]:
            return self._ok(result["payload"].get("templateMappings", {}))
        return result


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _encode_newlines(text: str) -> str:
    """
    Encode actual newlines as \\n for Obsidian CLI content parameters.
    The CLI interprets \\n in content= values as actual newlines.
    """
    return text.replace("\n", "\\n")


def _build_periodic_mappings(config: dict) -> dict[str, str]:
    """
    Build template→folder mappings from Periodic Notes plugin config.
    Mirrors the calculatePeriodicPath logic from WebSocketService.ts.

    Periodic Notes config format:
      { "daily": {"enabled": true, "folder": "02_Journal/Daily Notes", "format": "YYYY/MM/YYYY-MM-DD", "template": "..."}, ... }
    """
    from datetime import date
    today = date.today()
    mappings: dict[str, str] = {}

    period_map = {
        "daily": {"year": today.year, "month": today.month, "day": today.day},
        "weekly": {"year": today.year, "week": today.isocalendar()[1]},
        "monthly": {"year": today.year, "month": today.month},
        "quarterly": {"year": today.year, "quarter": (today.month - 1) // 3 + 1},
        "yearly": {"year": today.year},
    }

    for period, defaults in period_map.items():
        cfg = config.get(period, {})
        if not cfg or not cfg.get("enabled", False):
            continue

        base_folder: str = cfg.get("folder", "")
        fmt: str = cfg.get("format", "")
        template_path: str = cfg.get("template", "")

        template_name = _path_basename(template_path) if template_path else f"TPL {period.capitalize()} Note"

        # Calculate date-expanded subfolder from format string
        if fmt and base_folder:
            expanded = _expand_date_format(fmt, today)
            # Format may encode a full path including filename; take directory portion
            sub = "/".join(expanded.split("/")[:-1]) if "/" in expanded else ""
            resolved = f"{base_folder}/{sub}".rstrip("/") if sub else base_folder
        else:
            resolved = base_folder

        if template_name:
            mappings[template_name] = resolved

    return mappings


def _path_basename(path: str) -> str:
    """Return filename without extension from a path string."""
    name = path.split("/")[-1]
    return name[:-3] if name.lower().endswith(".md") else name


def _expand_date_format(fmt: str, d) -> str:
    """
    Expand a moment.js-style format string using Python date.
    Handles common tokens: YYYY, MM, DD, WW (ISO week), Qx (quarter).
    """
    from datetime import date
    quarter = (d.month - 1) // 3 + 1
    iso = d.isocalendar()
    result = fmt
    result = result.replace("YYYY", str(d.year))
    result = result.replace("YY", str(d.year)[-2:])
    result = result.replace("MM", f"{d.month:02d}")
    result = result.replace("M", str(d.month))
    result = result.replace("DD", f"{d.day:02d}")
    result = result.replace("D", str(d.day))
    result = result.replace("WW", f"{iso[1]:02d}")
    result = result.replace("W", str(iso[1]))
    result = result.replace("Q", str(quarter))
    return result
