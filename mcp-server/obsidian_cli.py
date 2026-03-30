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
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Content larger than this threshold is written via eval+tempfile instead of CLI argv.
# Windows CreateProcess caps the command line at 8191 chars; 4096 is a safe margin.
_LARGE_CONTENT_THRESHOLD = 4096

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
        # macOS CLI registration (Obsidian Settings → General → CLI → Register CLI) adds
        # /Applications/Obsidian.app/Contents/MacOS to PATH via ~/.zprofile.
        # The binary is the same main Obsidian binary — it acts as a CLI bridge
        # to the running Obsidian app via IPC. Obsidian MUST be running for CLI calls to work.
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

    def _make_subprocess_env(self) -> Optional[dict]:
        """
        macOS: Obsidian CLI locates its IPC socket via TMPDIR.
        Claude Desktop spawns MCP servers through a stripped environment that
        drops TMPDIR entirely. tempfile.gettempdir() returns /tmp when TMPDIR
        is unset, but Obsidian's socket lives in /var/folders/.../T/ (user-specific).
        Fix: use `getconf DARWIN_USER_TEMP_DIR` to read the real path from the kernel.
        Returns None on Windows/Linux — full env inherited unchanged.
        """
        if platform.system() != "Darwin":
            return None
        env: dict = {}
        # TMPDIR: getconf DARWIN_USER_TEMP_DIR reads from the kernel without needing
        # TMPDIR to be set — gives the correct /var/folders/.../T/ path.
        tmpdir = os.environ.get("TMPDIR")
        if not tmpdir:
            try:
                r = subprocess.run(
                    ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    tmpdir = r.stdout.strip()
            except Exception:
                pass
        import tempfile
        env["TMPDIR"] = tmpdir or tempfile.gettempdir()
        env["HOME"] = os.environ.get("HOME") or os.path.expanduser("~")
        env["PATH"] = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["USER"] = os.environ.get("USER") or ""
        if not env["USER"]:
            try:
                import pwd
                env["USER"] = pwd.getpwuid(os.getuid()).pw_name
            except Exception:
                pass
        # Use INFO so this appears in logs — confirms the env is being built
        logger.info(f"[CLI] subprocess env: TMPDIR={env.get('TMPDIR')} HOME={env.get('HOME')}")
        return env

    def _run(self, vault: str, *args: str, timeout: int = 30) -> tuple[str, int]:
        """Run a vault-scoped CLI command. Returns (stdout, exit_code).
        On macOS, timeout is capped at 10s — CLI calls respond in <1s when working,
        and a short cap prevents the 30s hang from outlasting Claude Desktop's patience.
        """
        if platform.system() == "Darwin":
            timeout = min(timeout, 10)
        cmd = [self.binary, f"vault={vault}", *args]
        logger.debug(f"[CLI] {cmd[0]} vault={vault} {args[0] if args else ''}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, shell=False,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout, env=self._make_subprocess_env()
            )
            stdout = (result.stdout or "").replace("\r\n", "\n").strip()
            return stdout, result.returncode
        except subprocess.TimeoutExpired:
            logger.error(f"[CLI] Timeout ({timeout}s): vault={vault} {args[0] if args else ''}")
            return f"Error: Command timed out after {timeout}s", 1
        except Exception as e:
            logger.error(f"[CLI] Subprocess error: {e}")
            return f"Error: {e}", 1

    def _run_global(self, *args: str, timeout: int = 15) -> tuple[str, int]:
        """Run a vault-agnostic CLI command (vaults, version).
        On macOS, timeout is capped at 10s for the same reason as _run().
        """
        if platform.system() == "Darwin":
            timeout = min(timeout, 10)
        cmd = [self.binary, *args]
        try:
            result = subprocess.run(
                cmd, capture_output=True, shell=False,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout, env=self._make_subprocess_env()
            )
            stdout = (result.stdout or "").replace("\r\n", "\n").strip()
            return stdout, result.returncode
        except subprocess.TimeoutExpired:
            logger.error(f"[CLI] Timeout ({timeout}s): {' '.join(args)}")
            return f"Error: Command timed out after {timeout}s", 1
        except Exception as e:
            logger.error(f"[CLI] Subprocess error: {e}")
            return f"Error: {e}", 1

    def _ok(self, payload: Any) -> dict:
        return {"success": True, "payload": payload, "error": None}

    def _err(self, message: str, error_code: str = "CLI_ERROR") -> dict:
        return {"success": False, "error": message, "error_code": error_code, "payload": {}}

    def _is_error(self, out: str, code: int) -> bool:
        return code != 0 or out.startswith("Error:")

    @staticmethod
    def _auto_md(path: str) -> str:
        """Append .md only when the path has no file extension.
        Uses os.path.splitext to distinguish real extensions (.pdf, .png, .csv)
        from dotted note stems like 'Day46.01 - Some Note' (no ext → .md appended).
        Examples:
          'Day46.01 - Some Note'  → 'Day46.01 - Some Note.md'   (no ext)
          'notes/my-note'         → 'notes/my-note.md'           (no ext)
          'file.pdf'              → 'file.pdf'                    (has ext)
          'image.png'             → 'image.png'                   (has ext)
          'note.md'               → 'note.md'                     (already .md)
        """
        _, ext = os.path.splitext(path)
        return path if ext else path + ".md"

    def _write_via_eval(self, vault: str, path: str, content: str, verb: str) -> tuple[str, int]:
        """Write large content via OS temp file + Obsidian eval, bypassing argv size limits.
        Obsidian runs in Electron — require('fs') is available in the eval context.
        Temp file is cleaned up inside the JS and again in the Python finally block.
        @purpose: fix WinError 206 / spawnSync argv overflow for notes > 4096 chars
        @depends: Obsidian eval command, Node.js fs module, app.vault Obsidian API
        @results: (stdout, exit_code) matching _run() return signature
        """
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        try:
            tmp.write(content)
            tmp.close()
            tmp_js = tmp.name.replace("\\", "/")  # POSIX slashes — Node.js accepts on Windows
            safe_path = path.replace("'", "\\'")

            if verb in ("create", "overwrite"):
                js = (
                    f"(async()=>{{ const c=require('fs').readFileSync('{tmp_js}','utf8');"
                    f" const f=app.vault.getFileByPath('{safe_path}');"
                    f" if(f) await app.vault.modify(f,c);"
                    f" else await app.vault.create('{safe_path}',c);"
                    f" try{{require('fs').unlinkSync('{tmp_js}')}}catch(e){{}} return 'ok'; }})()"
                )
            elif verb == "append":
                js = (
                    f"(async()=>{{ const c=require('fs').readFileSync('{tmp_js}','utf8');"
                    f" const f=app.vault.getFileByPath('{safe_path}');"
                    f" if(f) await app.vault.append(f,c);"
                    f" try{{require('fs').unlinkSync('{tmp_js}')}}catch(e){{}} return 'ok'; }})()"
                )
            elif verb == "prepend":
                js = (
                    f"(async()=>{{ const c=require('fs').readFileSync('{tmp_js}','utf8');"
                    f" const f=app.vault.getFileByPath('{safe_path}');"
                    f" if(f){{ const ex=await app.vault.read(f); await app.vault.modify(f,c+'\\n'+ex); }}"
                    f" try{{require('fs').unlinkSync('{tmp_js}')}}catch(e){{}} return 'ok'; }})()"
                )
            else:
                return f"Error: unsupported verb for large write: {verb}", 1

            return self._run(vault, "eval", f"code={js}")
        finally:
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except Exception:
                pass

    def _content_cmd(self, vault: str, verb: str, path: str, content: str) -> tuple[str, int]:
        """Route content write: CLI arg for small content, eval+tempfile for large.
        verb: 'create' (overwrite), 'append', or 'prepend'
        """
        if len(content) > _LARGE_CONTENT_THRESHOLD:
            return self._write_via_eval(vault, path, content, verb)
        encoded = _encode_newlines(content)
        if verb in ("create", "overwrite"):
            return self._run(vault, "create", f"path={path}", f"content={encoded}", "overwrite")
        return self._run(vault, verb, f"path={path}", f"content={encoded}")

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
        Large content (> 4096 chars) is written via eval+tempfile to avoid WinError 206.
        """
        path = self._auto_md(path)
        out, code = self._content_cmd(vault, "create", path, content)
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
            out, code = self._content_cmd(vault, "create", path, content)

        elif editing_mode == "append_only":
            text = append_content or content
            if text is None:
                return self._err("append_content required for append_only mode")
            out, code = self._content_cmd(vault, "append", path, text)

        elif editing_mode == "prepend_only":
            text = content or append_content
            if text is None:
                return self._err("content required for prepend_only mode")
            out, code = self._content_cmd(vault, "prepend", path, text)

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
            out, code = self._content_cmd(vault, "create", path, chr(10).join(lines))

        else:
            return self._err(f"Unsupported editing_mode: {editing_mode}")

        if self._is_error(out, code):
            return self._err(out or f"Update failed (mode={editing_mode})")
        return self._ok({"path": path, "message": out, "mode": editing_mode})

    # ─── Tool 5: list_obsidian_vaults ────────────────────────────────────────

    def list_obsidian_vaults(self) -> dict:
        """List all known vaults. Returns name + path for each.
        On macOS the GUI binary cannot serve CLI commands, so reads directly from obsidian.json.
        """
        if platform.system() == "Darwin":
            return self._list_vaults_from_config()

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

    def _list_vaults_from_config(self) -> dict:
        """Read vault list from Obsidian's local config file (macOS path).
        obsidian.json structure: {"vaults": {"<uuid>": {"path": "...", "ts": ...}}}
        """
        config_path = os.path.expanduser(
            "~/Library/Application Support/obsidian/obsidian.json"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            vaults = [
                {
                    "name": os.path.basename(v["path"]),
                    "path": v["path"],
                    # Use vault NAME (not UUID) as id — CLI commands use vault=<name>,
                    # and vault_id is passed directly to _run(). UUID breaks CLI calls.
                    "id": os.path.basename(v["path"]),
                }
                for vid, v in data.get("vaults", {}).items()
                if "path" in v
            ]
            return self._ok({"vaults": vaults, "totalVaults": len(vaults)})
        except FileNotFoundError:
            return self._err(
                "obsidian.json not found — is Obsidian installed?",
                "VAULT_CONFIG_NOT_FOUND",
            )
        except Exception as e:
            return self._err(f"Could not read vault config: {e}", "VAULT_CONFIG_READ_ERROR")

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

        Folder resolution (3 tiers, computed in Python before template creation):
          1. target_folder param (explicit override)
          2. Templater folder_templates — match by template basename
          2b. Periodic Notes plugin config — match by template basename, expand date format
          3. MegaMem inboxFolder setting
        Folder is pre-created via manage_obsidian_folders (proven CLI pattern) before Templater runs.
        """
        safe_request = request_type.replace("'", "\\'")
        safe_filename = file_name.replace("'", "\\'")

        # ── Step 1: Resolve destination folder ───────────────────────────────────
        if not target_folder:
            target_folder = self._resolve_template_folder(vault, request_type)

        # ── Step 2: Pre-create the folder segment-by-segment (proven reliable) ──
        if target_folder:
            segs = target_folder.split("/")
            for i in range(1, len(segs) + 1):
                self.manage_obsidian_folders(vault, "create", "/".join(segs[:i]))

        # ── Step 3: Run Templater with explicit pre-existing folder ───────────────
        safe_folder = target_folder.replace("'", "\\'")
        js = (
            "(async () => {"
            " const tp = app.plugins.getPlugin('templater-obsidian').templater;"
            " if (!tp) return JSON.stringify({error: 'Templater not available'});"
            f" const rt = '{safe_request}'.toLowerCase();"
            " const _f = app.vault.getFiles();"
            " const tplFile = _f.find(f => f.basename.toLowerCase() === rt)"
            "   || _f.find(f => f.basename.toLowerCase().startsWith(rt))"
            "   || _f.find(f => f.basename.toLowerCase().includes(rt) || rt.includes(f.basename.toLowerCase()));"
            " if (!tplFile) return JSON.stringify({error: 'Template not found: ' + rt});"
            f" const folder = app.vault.getAbstractFileByPath('{safe_folder}') || app.vault.getRoot();"
            f" const result = await tp.create_new_note_from_template(tplFile, folder, '{safe_filename}', false);"
            " return result"
            "   ? JSON.stringify({path: result.path, templateUsed: tplFile.basename})"
            "   : JSON.stringify({error: 'No file created'});"
            "})()"
        )

        out, code = self._run(vault, "eval", f"code={js}", timeout=60)
        if code != 0 or (out.startswith("Error:") and "not defined" not in out):
            return self._err(out or "Template creation failed via eval")

        result_val = out.lstrip("=> ").strip()
        created_path = ""
        template_used = request_type
        try:
            result_obj = json.loads(result_val)
            if "error" in result_obj:
                return self._err(result_obj["error"])
            created_path = result_obj.get("path", "")
            template_used = result_obj.get("templateUsed", request_type)
        except (json.JSONDecodeError, TypeError):
            created_path = result_val  # fallback: raw path string

        # Optionally append user-provided content after template
        if content and created_path:
            self._content_cmd(vault, "append", created_path, content)

        return self._ok({
            "path": created_path,
            "message": f"Created from template: {template_used}",
            "templateUsed": template_used,
        })

    def _resolve_template_folder(self, vault: str, request_type: str) -> str:
        """
        Resolve destination folder for a template using a synchronous JS eval.
        No folder creation — just reads plugin settings and returns the path string.
        Tiers: Templater folder_templates → Periodic Notes config → MegaMem inboxFolder.
        Returns empty string if none matched (caller falls to vault root).
        """
        safe_request = request_type.replace("'", "\\'")
        js = (
            f"(()=>{{ const rt = '{safe_request}'.toLowerCase();"
            " const _af = app.vault.getFiles();"
            " const tplFile = _af.find(f => f.basename.toLowerCase() === rt)"
            "   || _af.find(f => f.basename.toLowerCase().startsWith(rt))"
            "   || _af.find(f => f.basename.toLowerCase().includes(rt) || rt.includes(f.basename.toLowerCase()));"
            " if (!tplFile) return JSON.stringify({folder:''});"
            " const tplSettings = app.plugins.getPlugin('templater-obsidian')?.settings;"
            " const mappings = tplSettings?.folder_templates || [];"
            " const match = mappings.find(m => {"
            "   const mBase = m.template.split('/').pop().replace(/\\.md$/i,'').toLowerCase();"
            "   const tbn = tplFile.basename.toLowerCase();"
            "   return tbn === mBase || tbn.includes(mBase) || mBase.includes(tbn);"
            " });"
            " if (match?.folder) return JSON.stringify({folder: match.folder});"
            " const pnCfg = app.plugins.getPlugin('periodic-notes')?.settings;"
            " if (pnCfg) {"
            "   for (const period of ['daily','weekly','monthly','quarterly','yearly']) {"
            "     const cfg = pnCfg[period];"
            "     if (!cfg?.enabled || !cfg.folder || !cfg.template) continue;"
            "     const pnBase = cfg.template.split('/').pop().replace(/\\.md$/i,'').toLowerCase();"
            "     const tbn = tplFile.basename.toLowerCase();"
            "     if (tbn === pnBase || tbn.includes(pnBase) || pnBase.includes(tbn)) {"
            "       let resolved = cfg.folder.replace(/\\/+$/,'');"
            "       const fmt = cfg.format || '';"
            "       if (fmt) {"
            "         const parts = fmt.split('/');"
            "         const m = window.moment ? window.moment() : null;"
            "         if (m && parts.length > 1) {"
            "           resolved += '/' + parts.slice(0,parts.length-1).map(p=>m.format(p)).join('/');"
            "         } else if (m && /YYYY/.test(fmt)) {"
            "           resolved += '/' + m.format('YYYY');"
            "           if (/MM/.test(fmt)) resolved += '/' + m.format('MM');"
            "         }"
            "       }"
            "       return JSON.stringify({folder: resolved});"
            "     }"
            "   }"
            " }"
            " const mmSettings = app.plugins.getPlugin('megamem-mcp')?.settings;"
            " const inboxPath = mmSettings?.mcpTools?.defaults?.inboxFolder || '';"
            " return JSON.stringify({folder: inboxPath});"
            "})()"
        )
        out, _ = self._run(vault, "eval", f"code={js}")
        raw = out.lstrip("=> ").strip()
        try:
            return json.loads(raw).get("folder", "")
        except (json.JSONDecodeError, AttributeError):
            return ""

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
                    # Always pass name with .md — CLI uses a "has-dot" heuristic that
                    # treats dotted stems like "Day46.01 - Foo" as already having an extension
                    moved_path = f"{dst_folder}/{os.path.basename(path)}" if dst_folder else os.path.basename(path)
                    out, code = self._run(vault, "rename", f"path={moved_path}", f"name={dst_name}.md")
            else:
                # Same folder, filename-only rename
                out, code = self._run(vault, "rename", f"path={path}", f"name={dst_name}.md")

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

    # ─── Bases Tools ─────────────────────────────────────────────────────────────

    def list_bases(self, vault: str) -> dict:
        """List all .base files in the vault.
        CLI: obsidian bases
        """
        out, code = self._run(vault, "bases")
        if self._is_error(out, code):
            return self._err(out or "Could not list bases")
        bases = [p for p in out.strip().splitlines() if p]
        return self._ok({"bases": bases, "totalBases": len(bases)})

    def list_base_views(
        self,
        vault: str,
        file: Optional[str] = None,
        path: Optional[str] = None,
    ) -> dict:
        """List views in a base file.
        CLI: obsidian base:views file=<name>  OR  path=<path>
        For MCP use, always pass explicit file= or path= — never rely on active-file defaults.
        """
        args = ["base:views"]
        if file:
            args.append(f"file={file}")
        elif path:
            args.append(f"path={path}")
        else:
            return self._err("file or path required for list_base_views")
        out, code = self._run(vault, *args)
        if self._is_error(out, code):
            return self._err(out or "Could not list base views")
        views = [v for v in out.strip().splitlines() if v]
        return self._ok({"views": views, "totalViews": len(views)})

    def query_base(
        self,
        vault: str,
        file: Optional[str] = None,
        path: Optional[str] = None,
        view: Optional[str] = None,
        format: str = "json",
    ) -> dict:
        """Query a base and return structured results.
        CLI: obsidian base:query file=<name> view=<view> format=<format>
        When format=json, the stdout is parsed into a Python object before returning.
        Supported formats: json, csv, tsv, md, paths
        """
        args = ["base:query"]
        if file:
            args.append(f"file={file}")
        elif path:
            args.append(f"path={path}")
        else:
            return self._err("file or path required for query_base")
        if view:
            args.append(f"view={view}")
        args.append(f"format={format}")
        out, code = self._run(vault, *args)
        if self._is_error(out, code):
            return self._err(out or "Base query failed")
        if format == "json":
            try:
                parsed = json.loads(out) if out else []
                return self._ok({"results": parsed, "format": format})
            except json.JSONDecodeError:
                # Return raw string if JSON parse fails — CLI may not have returned valid JSON
                return self._ok({"results": out, "format": format, "parseError": True})
        return self._ok({"results": out, "format": format})

    def create_base_item(
        self,
        vault: str,
        file: Optional[str] = None,
        path: Optional[str] = None,
        view: Optional[str] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
    ) -> dict:
        """Create a new item (row/entry) in a base.
        CLI: obsidian base:create file=<name> view=<view> name=<name> content=<content>
        Note: creates items *in* a base, not a new .base file itself.
        open/newtab flags are omitted — MCP use is always headless.
        """
        args = ["base:create"]
        if file:
            args.append(f"file={file}")
        elif path:
            args.append(f"path={path}")
        else:
            return self._err("file or path required for create_base_item")
        if view:
            args.append(f"view={view}")
        if name:
            args.append(f"name={name}")
        if content:
            args.append(f"content={content}")
        out, code = self._run(vault, *args)
        if self._is_error(out, code):
            return self._err(out or "Base item creation failed")
        return self._ok({"message": out})

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
