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
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Optional

from template_matcher import TemplateCandidate, rank_candidates, resolve_across_sources
from template_renderer import render_template

logger = logging.getLogger(__name__)

# Content larger than this threshold is written via eval+tempfile instead of CLI argv.
# Windows CreateProcess caps the command line at 8191 chars; 4096 is a safe margin.
_LARGE_CONTENT_THRESHOLD = 4096

# Known non-markdown vault file extensions (lowercase, no leading dot).
# _auto_md() only skips appending ".md" when a path's trailing suffix exactly
# matches one of these — anything else (including dotted note stems like
# "Day46.01 - Some Note") is treated as a markdown note title. See Day75.03.
KNOWN_VAULT_EXTENSIONS = frozenset(
    {
        "md",
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "canvas",
        "base",
        "csv",
        "json",
        "txt",
        "html",
        "htm",
        "xml",
        "yaml",
        "yml",
        "toml",
        "mp3",
        "mp4",
        "mov",
        "webm",
        "wav",
        "ogg",
        "m4a",
        "flac",
        "zip",
        "gz",
        "tar",
    }
)

# Matches [[wikilinks]] and ![[embeds]] — used to warn callers that cross-vault
# copy/move carries link syntax verbatim, which may dangle in the target vault.
_WIKILINK_RE = re.compile(r"(!)?\[\[([^\]]+)\]\]")

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
        # Task 3b follow-up (Day77.01): per-(vault, registry_folder) cache
        # for filter-introspection registry Base discovery — see
        # _discover_registry_base(). Lives for this instance's lifetime;
        # most settings changes naturally use a different registry_folder
        # key so stale entries are simply never looked up again, but a
        # config change that revisits a previously-seen key (e.g. toggling
        # a custom registry path off then back on) must not read a stale
        # resolution — call invalidate_registry_cache() whenever
        # template-source settings are updated without a full process
        # restart (Task 3b follow-up #3).
        self._registry_base_cache: dict = {}

    def invalidate_registry_cache(self) -> None:
        """Clear the registry-Base discovery cache — call whenever
        template-source settings change at runtime (Task 3b follow-up #3,
        Day77.01), so a stale resolved (or previously-missing) Base path
        can never outlive the config that produced it. A full process
        restart already gets this for free via a fresh ObsidianCLI
        instance; this exists for any settings-reload path that updates
        template sources on a long-lived instance instead.
        """
        self._registry_base_cache.clear()

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
        """Append .md unless the path's trailing suffix is a known non-markdown
        vault file extension.

        Regression fix (Day75.03): os.path.splitext() alone can't tell a real
        extension apart from a dotted note stem like 'Day46.01 - Some Note' —
        splitext treats '.01 - Some Note' as the "extension" and skips the
        .md append, causing FILE_NOT_FOUND on valid notes. Only skip appending
        .md when the suffix exactly (case-insensitively) matches a known
        vault file extension; everything else is treated as a note title.

        Examples:
          'Day09.02 - Zep Local MCP Server' → 'Day09.02 - Zep Local MCP Server.md'  (dotted stem, not a known ext)
          'notes/my-note'                   → 'notes/my-note.md'                    (no ext)
          'file.pdf'                        → 'file.pdf'                            (known ext)
          'UPPERCASE.PDF'                   → 'UPPERCASE.PDF'                       (case-insensitive match)
          'note.md'                         → 'note.md'                             (already .md)
        """
        _, ext = os.path.splitext(path)
        if ext and ext[1:].lower() in KNOWN_VAULT_EXTENSIONS:
            return path
        return path + ".md"

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
        query: str = "",
        search_mode: str = "both",
        max_results: int = 100,
        include_context: bool = True,
        path: Optional[str] = None,
        property_filter: Optional[dict] = None,
        mtime_after: Optional[str] = None,
        mtime_before: Optional[str] = None,
    ) -> dict:
        """
        Search vault notes. search_mode=filename uses 'obsidian files' + client-side filter.
        search_mode=content|both uses search:context with full-text matching.
        property_filter: dict of frontmatter key/value pairs — uses eval to filter vault.
        mtime_after / mtime_before: ISO date strings (e.g. "2026-03-20") for mtime range filtering.
          Both use eval. If combined with a non-empty query, applies query as a filename/path filter.
        """
        if property_filter or mtime_after or mtime_before:
            return self._search_by_property(
                vault, property_filter or {}, query=query, max_results=max_results,
                mtime_after=mtime_after, mtime_before=mtime_before,
            )

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

    def _search_by_property(
        self,
        vault: str,
        property_filter: dict,
        query: str = "",
        max_results: int = 100,
        mtime_after: Optional[str] = None,
        mtime_before: Optional[str] = None,
    ) -> dict:
        """Filter vault notes by frontmatter properties and/or mtime range via eval.
        property_filter: all key/value pairs must match (AND logic); empty dict = no frontmatter filter.
        Array frontmatter values are checked with includes(); scalars use String() equality.
        mtime_after / mtime_before: ISO date strings; maps to f.stat.mtime (Unix ms).
        query: case-insensitive filename/path substring filter (not full-text).
        """
        filter_json = json.dumps(property_filter)
        query_lower = query.lower().strip()
        query_js = json.dumps(query_lower) if query_lower else '""'
        mtime_after_js = json.dumps(mtime_after) if mtime_after else "null"
        mtime_before_js = json.dumps(mtime_before) if mtime_before else "null"
        limit_n = int(max_results)
        js = (
            "(()=>{"
            f"const filter={filter_json};"
            f"const q={query_js};"
            f"const mtimeAfter={mtime_after_js}?new Date({mtime_after_js}).getTime():0;"
            f"const mtimeBefore={mtime_before_js}?new Date({mtime_before_js}).getTime():Infinity;"
            "const hasFmFilter=Object.keys(filter).length>0;"
            "const results=[];"
            "for(const f of app.vault.getMarkdownFiles()){"
            " if(q&&!f.path.toLowerCase().includes(q)&&!f.basename.toLowerCase().includes(q))continue;"
            " if(f.stat.mtime<mtimeAfter||f.stat.mtime>mtimeBefore)continue;"
            " if(hasFmFilter){"
            "  const fm=app.metadataCache.getFileCache(f)?.frontmatter;"
            "  if(!fm)continue;"
            "  let ok=true;"
            "  for(const [k,v] of Object.entries(filter)){"
            "   const fv=fm[k];"
            "   if(Array.isArray(fv)){if(!fv.map(String).includes(String(v))){ok=false;break;}}"
            "   else{if(String(fv??'')!==String(v)){ok=false;break;}}"
            "  }"
            "  if(!ok)continue;"
            " }"
            " results.push({"
            "  path:f.path,"
            "  name:f.extension?f.basename+'.'+f.extension:f.basename,"
            "  basename:f.basename,extension:f.extension,"
            "  mtime:f.stat.mtime,ctime:f.stat.ctime,matchType:'property'"
            " });"
            "}"
            f"return JSON.stringify(results.slice(0,{limit_n}));"
            "})()"
        )
        out, code = self._run(vault, "eval", f"code={js}")
        if self._is_error(out, code):
            return self._err(out or "Property search failed")
        # Obsidian CLI prefixes eval output with "=> " — strip before JSON parse
        json_str = out.strip()
        if json_str.startswith("=>"):
            json_str = json_str[2:].strip()
        try:
            parsed: list = json.loads(json_str) if json_str else []
        except json.JSONDecodeError:
            return self._err(f"Property search returned invalid JSON: {out[:200]}")
        return self._ok({
            "results": parsed,
            "totalResults": len(parsed),
            "query": query or None,
            "propertyFilter": property_filter or None,
            "mtimeAfter": mtime_after,
            "mtimeBefore": mtime_before,
            "searchMode": "property",
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
                # bool MUST come before int — bool is a subclass of int in Python
                if isinstance(value, bool):
                    prop_type = "checkbox"
                    val_str = "true" if value else "false"
                elif isinstance(value, (int, float)):
                    prop_type = "number"
                    val_str = str(value)
                elif isinstance(value, list):
                    prop_type = "list"
                    val_str = json.dumps(value)
                else:
                    prop_type = "text"
                    val_str = str(value) if value is not None else ""
                out, code = self._run(
                    vault, "property:set",
                    f"name={name}", f"value={val_str}", f"type={prop_type}", f"path={path}"
                )
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

    # ─── Day77.01: Native Template Engine — Cross-Vault Template Resolution ──
    #
    # create_note_with_template dispatches to the native multi-source engine
    # when `template_sources` is configured (Task 1 settings), else falls back
    # unmodified to the pre-existing single-vault Templater-eval path below
    # (_create_note_with_template_legacy) — guaranteeing zero regression for
    # existing single-vault CLI users who haven't opened the new settings pane.

    def create_note_with_template(
        self,
        vault: str,
        request_type: str,
        file_name: str,
        content: str = "",
        target_folder: str = "",
        template_sources: Optional[list] = None,
        template_source_override: Optional[Any] = None,
    ) -> dict:
        """
        Resolve request_type against configured template_sources (ordered
        personal/company sources with precedence) and render natively —
        works with or without Templater installed in the target vault.

        template_sources: [{vault_id, folder, label, registry}, ...] — registry
          is "auto-detect" | "<explicit folder path>" | "none". Falls back to
          the legacy single-vault Templater path when omitted/empty.
        template_source_override: label (str) or index (int) pinning resolution
          to one source for this call only.
        """
        if not template_sources:
            return self._create_note_with_template_legacy(
                vault, request_type, file_name, content, target_folder
            )

        override_index = self._resolve_source_override_index(
            template_sources, template_source_override
        )

        # Perf: match against cheap filename-only listings first (one
        # explore_vault_folders call per source) — registry enrichment is
        # deferred to the single winning candidate below. Reading every
        # registry .md file up front for every call took 60-80s across two
        # sources (confirmed live, test-vault, 2026-07-16) and doesn't scale.
        per_source_candidates: list[list[TemplateCandidate]] = [
            self._list_source_filenames(vault, source, i)
            for i, source in enumerate(template_sources)
        ]

        match_result = resolve_across_sources(request_type, per_source_candidates, override_index)

        if not match_result["confident"]:
            # Task 3b (Day77.01 Rev 4): the registry exists precisely for
            # this moment — the caller doesn't know which template to use,
            # so the candidate list must carry when_to_use/category and
            # must not let one source's listing volume crowd out the
            # others. Enrich every merged candidate (one query_base call
            # per registry-mode source, never per-candidate) and rank by
            # relevance to request_type before capping — alphabetical
            # source-listing order previously masqueraded as relevance.
            enriched = self._enrich_candidates_with_registry(
                match_result["candidates"], template_sources, vault
            )
            ranked = rank_candidates(request_type, enriched)
            top_candidates = ranked[:10]

            # Task 3b follow-up #3 (Day77.01): the batch Base-query pass
            # above only enriches candidates whose exact name appears as a
            # row in that source's Base — a template can legitimately exist
            # under the registry folder's plain-file convention without a
            # matching Base row (mismatched template_name, or the entry
            # predates the Base). The single-winner path
            # (_enrich_with_registry) already falls back to a targeted
            # single-file read for exactly this case; candidate-return must
            # use that SAME resolution step (single source of truth) for
            # any finalist still missing when_to_use — bounded to these
            # <=10 finalists, never the full merged candidate list, so this
            # cannot reintroduce the original per-registry-file perf bug.
            for i, c in enumerate(top_candidates):
                if c.when_to_use is not None:
                    continue
                if not (0 <= c.source_index < len(template_sources)):
                    continue
                src = template_sources[c.source_index]
                if (src.get("registry") or "auto-detect").strip() == "none":
                    continue
                src_vault = src.get("vault_id") or vault
                top_candidates[i] = self._enrich_via_sibling_file(c, src, src_vault)

            return self._ok({
                "requiresSelection": True,
                "candidates": [c.to_dict() for c in top_candidates],
                "message": (
                    f"No confident match for '{request_type}'. "
                    "Choose from candidates or refine request_type."
                ),
            })

        matched = match_result["matched"]
        source = template_sources[matched.source_index]
        source_vault = source.get("vault_id") or vault
        matched = self._enrich_with_registry(matched, source, source_vault)

        read_result = self.read_obsidian_note(source_vault, matched.path)
        if not read_result["success"]:
            return self._err(
                f"Could not read matched template '{matched.path}' from source vault "
                f"'{source_vault}': {read_result.get('error')}",
                "TEMPLATE_READ_FAILED",
            )
        template_body = read_result["payload"]["content"]

        file_title = file_name[:-3] if file_name.lower().endswith(".md") else file_name
        render_result = render_template(template_body, file_title=file_title, now=datetime.now())

        if render_result["unsupported"]:
            if self._templater_available(vault) and self._template_exists_locally(vault, matched.name):
                logger.warning(
                    f"[TEMPLATE] Unsupported construct(s) {render_result['unsupported']} in "
                    f"'{matched.name}' — falling back to legacy Templater in target vault "
                    "(deprecated path, template exists locally)"
                )
                return self._create_note_with_template_legacy(
                    vault, request_type, file_name, content, target_folder
                )
            return self._err(
                f"Unsupported Templater construct(s) in '{matched.name}': "
                f"{render_result['unsupported']}. Templater not available in target vault "
                "(or template not present locally) to fall back to.",
                "UNSUPPORTED_TEMPLATE_CONSTRUCT",
            )

        rendered_content = render_result["rendered_content"]

        # Folder precedence (highest first): explicit param > in-template
        # tp.file.move > registry default folder > Templater folder_templates
        # settings mapping > Periodic Notes config > MegaMem inboxFolder.
        resolved_folder = (
            target_folder
            or render_result["target_folder_from_template"]
            or matched.folder
            or self._resolve_template_folder(vault, request_type)
        )

        if resolved_folder:
            segs = resolved_folder.split("/")
            for i in range(1, len(segs) + 1):
                self.manage_obsidian_folders(vault, "create", "/".join(segs[:i]))

        dest_path = f"{resolved_folder.rstrip('/')}/{file_name}" if resolved_folder else file_name
        dest_path = self._auto_md(dest_path)

        write_result = self.create_obsidian_note(vault, dest_path, rendered_content)
        if not write_result["success"]:
            return self._err(
                f"Failed to write rendered note: {write_result.get('error')}",
                "TEMPLATE_WRITE_FAILED",
            )

        if content:
            self._content_cmd(vault, "append", dest_path, content)

        final_read = self.read_obsidian_note(vault, dest_path)
        note_content = final_read["payload"]["content"] if final_read["success"] else rendered_content

        response: dict = {
            "path": dest_path,
            "message": f"Created from template: {matched.name} (native engine, source: {matched.source_label})",
            "templateUsed": matched.name,
            "templateSource": matched.source_label,
            "content": note_content,
            "instructions": (
                "Populate ALL frontmatter fields with correct values. Replace body "
                "placeholder content matching the template structure. Do NOT add new "
                "frontmatter fields. Do NOT remove existing fields. Write back with "
                "update_obsidian_note editing_mode: full_file."
            ),
        }
        if matched.when_to_use is not None:
            response["whenToUse"] = matched.when_to_use
        if matched.category is not None:
            response["category"] = matched.category

        return self._ok(response)

    @staticmethod
    def _resolve_source_override_index(template_sources: list, override: Optional[Any]) -> Optional[int]:
        """Resolve the `template_source` per-call override param (label or index)
        to a source-list index for resolve_across_sources().
        """
        if override is None:
            return None
        if isinstance(override, int):
            return override
        if isinstance(override, str) and override.strip().lstrip("-").isdigit():
            return int(override)
        for i, s in enumerate(template_sources):
            if s.get("label") == override:
                return i
        return None

    @staticmethod
    def _parse_simple_frontmatter(content: str) -> dict:
        """Minimal scalar-only frontmatter parser for TemplateRegistry entries —
        no YAML dependency. Only extracts top-level `key: value` scalar lines
        (template_name, template_path, category, when_to_use, folder); list/nested
        values (e.g. `tags:`, `properties:`) are intentionally skipped, matching
        the doc's "no changes to how TemplateRegistry entries are structured."
        """
        m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not m:
            return {}
        result: dict = {}
        for line in m.group(1).split("\n"):
            sm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
            if not sm:
                continue
            key, val = sm.group(1), sm.group(2).strip()
            if not val:
                continue  # list/nested value (e.g. "tags:") — skip
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            result[key] = val
        return result

    def _auto_detect_registry_folder(self, vault: str, templates_folder: str) -> Optional[str]:
        """Look for a sibling 'Template-Registry' folder next to the configured
        templates folder (matches the corpus convention: 06_Resources/Templates
        + 06_Resources/Template-Registry). Returns the folder path if found and
        non-empty, else None — caller falls back to filename mode.
        """
        parent = templates_folder.rsplit("/", 1)[0] if "/" in templates_folder else ""
        candidate = f"{parent}/Template-Registry" if parent else "Template-Registry"
        result = self.explore_vault_folders(vault, candidate, include_files=True, extension_filter=["md"])
        if result.get("success") and result.get("files"):
            return candidate
        return None

    def _list_source_filenames(
        self, target_vault: str, source: dict, source_index: int
    ) -> list[TemplateCandidate]:
        """Cheap filename-only candidate listing for one configured template
        source — a single explore_vault_folders call, no registry reads.
        Matching happens against this list; registry enrichment (when
        configured) is applied only to the single winning candidate via
        _enrich_with_registry() — reading every registry file up front for
        every call took 60-80s across two sources (confirmed live,
        test-vault, 2026-07-16) and doesn't scale.
        """
        source_vault = source.get("vault_id") or target_vault
        folder = source.get("folder", "") or ""
        label = source.get("label") or source_vault

        listing = self.explore_vault_folders(source_vault, folder, include_files=True, extension_filter=["md"])
        files = listing.get("files", []) if listing.get("success") else []
        return [
            TemplateCandidate(
                name=f["name"][:-3] if f["name"].lower().endswith(".md") else f["name"],
                source_label=label,
                source_index=source_index,
                path=f["path"],
            )
            for f in files
        ]

    @staticmethod
    def _candidate_registry_folder(registry_setting: str, templates_folder: str) -> Optional[str]:
        """Best-guess registry folder path used only as a hint/cache-key for
        Base discovery (_discover_registry_base) — deliberately NOT
        existence-checked, unlike _auto_detect_registry_folder (which backs
        the sibling-file-read fallback and must confirm real files exist).
        A Base file can legitimately scope to a registry folder that lives
        anywhere in the vault, not just adjacent to the templates folder.
        """
        if registry_setting in ("none",):
            return None
        if registry_setting.lower().endswith(".base"):
            return None
        if registry_setting == "auto-detect":
            parent = templates_folder.rsplit("/", 1)[0] if "/" in templates_folder else ""
            return f"{parent}/Template-Registry" if parent else "Template-Registry"
        return registry_setting

    def _discover_registry_base(
        self, vault: str, registry_folder: str, source_label: Optional[str] = None
    ) -> Optional[str]:
        """Filter-introspection discovery of the .base file that scopes to
        `registry_folder` — replaces the old <parent-of-templates-folder>/
        Bases/TemplateRegistry.base path heuristic (Task 3b follow-up,
        Day77.01), which assumed a fixed folder-adjacency convention that
        doesn't hold for every vault layout. Enumerates the vault's .base
        files once per (vault, registry_folder) pair and caches a
        successful result for this instance's lifetime:

          1. Name narrows the field: any base file whose NAME contains
             "TemplateRegistry" (case-insensitive) is a *candidate*, not an
             automatic winner — a vault can carry more than one base named
             this way (one per source, e.g. Personal + CompanyRelay), so a
             bare name match is never decisive on its own (Task 3b
             follow-up #2, Day77.01: production repro where a top-level-
             folder-overlap tiebreak between two same-named bases was a
             zero-zero tie and handed the wrong base to a source).
          2. Filter text decides: each name-matched candidate's raw content
             is read and substring-matched against `registry_folder` — the
             filters block references the folder as a literal string (e.g.
             `file.folder == "06_Resources/Template-Registry"`); we
             deliberately do NOT parse the filter expression, just check
             the folder path string appears somewhere in the file. Exactly
             one filter-text match among the name candidates wins outright.
             More than one match falls back to top-level-folder overlap
             with `registry_folder`, then first-with-warning. Zero matches
             among the name candidates means name alone isn't decisive —
             fall through to step 3.
          3. Full filter-text scan: every remaining (non-name-matched, or
             all bases if step 1 found no name candidates at all) base is
             read and substring-matched the same way. First match wins;
             multiple matches log a warning and use the first.

        Every resolution path logs its decision (source label, winning
        base, and why) so this class of bug is diagnosable from output.

        Returns None (not cached — a miss should be retried on next call in
        case a Base is added later) if nothing is found, so callers fall
        back to the sibling-file read or filename-mode gracefully.
        """
        cache_key = (vault, registry_folder)
        cached = self._registry_base_cache.get(cache_key)
        if cached:
            return cached

        label = source_label or vault
        list_result = self.list_bases(vault)
        if not list_result.get("success"):
            logger.info(
                f"[TEMPLATE] Registry discovery for source '{label}': bases enumeration "
                f"failed in vault '{vault}'"
            )
            return None
        bases = list_result["payload"].get("bases", [])
        if not bases:
            logger.info(
                f"[TEMPLATE] Registry discovery for source '{label}': no .base files found "
                f"in vault '{vault}'"
            )
            return None

        name_matches = [b for b in bases if "templateregistry" in b.lower()]
        checked: set[str] = set()

        if name_matches:
            # Name narrows the field to candidates; filter text (the literal
            # registry-folder string in the filters block) decides which one
            # actually scopes to this source's registry — a name match alone
            # is never accepted without this check.
            passing = []
            for base_path in name_matches:
                checked.add(base_path)
                read = self.read_obsidian_note(vault, base_path)
                if read.get("success") and registry_folder in read["payload"]["content"]:
                    passing.append(base_path)

            if len(passing) == 1:
                resolved = passing[0]
                logger.info(
                    f"[TEMPLATE] Registry discovery for source '{label}': resolved "
                    f"'{resolved}' (name fast-path, confirmed by filter text referencing "
                    f"'{registry_folder}')"
                )
                self._registry_base_cache[cache_key] = resolved
                return resolved
            if len(passing) > 1:
                top_level = registry_folder.split("/", 1)[0] if registry_folder else None
                scoped = [b for b in passing if top_level and b.split("/", 1)[0] == top_level]
                if scoped:
                    resolved = scoped[0]
                    logger.info(
                        f"[TEMPLATE] Registry discovery for source '{label}': resolved "
                        f"'{resolved}' (name fast-path, {len(passing)} filter-text matches, "
                        f"disambiguated by top-level folder overlap with '{registry_folder}')"
                    )
                else:
                    resolved = passing[0]
                    logger.warning(
                        f"[TEMPLATE] Registry discovery for source '{label}': {len(passing)} "
                        f"TemplateRegistry-named bases both reference registry folder "
                        f"'{registry_folder}' in filter text, none sharing a top-level "
                        f"folder with it: {passing} — using the first ('{resolved}')"
                    )
                self._registry_base_cache[cache_key] = resolved
                return resolved
            # No name-match's filter text referenced this registry_folder —
            # name alone is not decisive. Fall through to the full
            # filter-text scan below (bases already checked here are
            # skipped, not re-read).
            logger.info(
                f"[TEMPLATE] Registry discovery for source '{label}': {len(name_matches)} "
                f"TemplateRegistry-named base(s) found but none reference registry folder "
                f"'{registry_folder}' in filter text — falling through to full filter-text scan"
            )

        filter_matches = []
        for base_path in bases:
            if base_path in checked:
                continue
            read = self.read_obsidian_note(vault, base_path)
            if read.get("success") and registry_folder in read["payload"]["content"]:
                filter_matches.append(base_path)

        if not filter_matches:
            logger.info(
                f"[TEMPLATE] Registry discovery for source '{label}': no .base file "
                f"references registry folder '{registry_folder}' in vault '{vault}'"
            )
            return None
        if len(filter_matches) > 1:
            logger.warning(
                f"[TEMPLATE] Registry discovery for source '{label}': multiple .base files "
                f"reference registry folder '{registry_folder}' in vault '{vault}': "
                f"{filter_matches} — using the first"
            )
        resolved = filter_matches[0]
        logger.info(
            f"[TEMPLATE] Registry discovery for source '{label}': resolved '{resolved}' "
            f"(filter-text scan, no decisive name match)"
        )
        self._registry_base_cache[cache_key] = resolved
        return resolved

    def _get_registry_rows(self, vault: str, source: dict) -> Optional[list]:
        """Resolve (via filter-introspection discovery, cached) and query the
        registry Base for `source`. An explicit `registry` setting ending in
        `.base` is used directly with no discovery involved (static config,
        not a discovered guess). Retries discovery once, invalidating the
        cache first, if a cached path has gone missing (e.g. the Base file
        was renamed/deleted) — satisfies "re-resolve if the cached path goes
        missing" without a proactive existence check on every call.

        Returns the parsed row list, or None if no Base applies or every
        attempt fails — callers fall back to sibling-file reads or
        filename-mode, registry enrichment is always an enhancement.
        """
        label = source.get("label") or vault
        registry_setting = (source.get("registry") or "auto-detect").strip()
        if registry_setting == "none":
            return None

        if registry_setting != "auto-detect" and registry_setting.lower().endswith(".base"):
            result = self.query_base(vault, path=registry_setting, format="json")
            if not result.get("success"):
                return None
            rows = result["payload"].get("results")
            return rows if isinstance(rows, list) else None

        # A hint string only — used as the discovery cache key and as the
        # substring searched for in Base filter text. Deliberately does NOT
        # require the folder to physically exist (unlike
        # _auto_detect_registry_folder, which is existence-checked and used
        # only for the sibling-file-read fallback below in
        # _enrich_with_registry) — a Base can legitimately scope to a
        # registry folder that lives anywhere in the vault, adjacent or not.
        templates_folder = source.get("folder", "") or ""
        registry_folder = self._candidate_registry_folder(registry_setting, templates_folder)
        if not registry_folder:
            # Diagnoses the "hint itself is empty/wrong" failure mode
            # (Task 3b follow-up #2, Day77.01) instead of silently
            # returning a bare, unenriched candidate with no trace of why.
            logger.warning(
                f"[TEMPLATE] Registry hint for source '{label}' resolved empty "
                f"(registry_setting='{registry_setting}', templates_folder="
                f"'{templates_folder}') — registry enrichment skipped for this source"
            )
            return None
        logger.debug(
            f"[TEMPLATE] Registry hint for source '{label}': '{registry_folder}' "
            f"(registry_setting='{registry_setting}')"
        )

        cache_key = (vault, registry_folder)
        base_path = self._discover_registry_base(vault, registry_folder, source_label=label)
        if not base_path:
            return None

        result = self.query_base(vault, path=base_path, format="json")
        if not result.get("success"):
            self._registry_base_cache.pop(cache_key, None)
            base_path = self._discover_registry_base(vault, registry_folder, source_label=label)
            if not base_path:
                return None
            result = self.query_base(vault, path=base_path, format="json")
            if not result.get("success"):
                return None

        rows = result["payload"].get("results")
        return rows if isinstance(rows, list) else None

    def _enrich_via_sibling_file(
        self, candidate: TemplateCandidate, source: dict, source_vault: str
    ) -> TemplateCandidate:
        """Single-file registry-entry fallback — the *sole* implementation
        of this resolution step, shared by both the single-winner path
        (_enrich_with_registry) and the candidate-return path's bounded
        top-N pass (Task 3b follow-up #3, Day77.01: candidate-return was
        previously missing this fallback entirely, so a source whose Base
        rows didn't cover every filename enriched fine on the winner path
        but came back bare on candidate-return for the exact same source —
        one function, one behavior, called from both places).

        Used when the Base-query path (_get_registry_rows) has no row for
        this specific candidate name — legitimately possible even when the
        Base itself was discovered correctly (a template registered under
        the registry folder's plain-file convention but not yet added as a
        Base row, or a template_name mismatch). Reads exactly one targeted
        <registry_folder>/<candidate.name>.md file. Returns `candidate`
        unchanged if no registry folder applies or the read/parse misses —
        registry enrichment is always an enhancement, never a requirement.
        """
        registry_setting = (source.get("registry") or "auto-detect").strip()
        folder = source.get("folder", "") or ""
        if registry_setting == "auto-detect":
            registry_folder = self._auto_detect_registry_folder(source_vault, folder)
        elif registry_setting.lower().endswith(".base"):
            registry_folder = None  # explicit .base has no folder-fallback concept
        else:
            registry_folder = registry_setting
        if not registry_folder:
            return candidate

        guess_path = f"{registry_folder.rstrip('/')}/{candidate.name}.md"
        read = self.read_obsidian_note(source_vault, guess_path)
        if not read.get("success"):
            return candidate

        fm = self._parse_simple_frontmatter(read["payload"]["content"])
        if not fm:
            return candidate

        return TemplateCandidate(
            name=fm.get("template_name") or candidate.name,
            source_label=candidate.source_label,
            source_index=candidate.source_index,
            path=candidate.path,
            when_to_use=fm.get("when_to_use"),
            category=fm.get("category"),
            folder=fm.get("folder") or candidate.folder,
        )

    def _enrich_with_registry(
        self, candidate: TemplateCandidate, source: dict, source_vault: str
    ) -> TemplateCandidate:
        """Enrich the already-matched candidate with registry metadata
        (when_to_use, category) for the single winning template only —
        never scans the whole registry for every call. Registry Base
        lookup goes through _get_registry_rows() (filter-introspection
        discovery, cached); falls back to _enrich_via_sibling_file() (a
        single targeted registry-file read) when no Base row matches.
        Returns `candidate` unchanged if registry is disabled or both
        lookups miss — registry is an enhancement, never a requirement.
        """
        registry_setting = (source.get("registry") or "auto-detect").strip()
        if registry_setting == "none":
            return candidate

        rows = self._get_registry_rows(source_vault, source)
        if rows:
            row = next(
                (r for r in rows if isinstance(r, dict) and r.get("template_name") == candidate.name),
                None,
            )
            if row:
                return TemplateCandidate(
                    name=row.get("template_name") or candidate.name,
                    source_label=candidate.source_label,
                    source_index=candidate.source_index,
                    path=candidate.path,
                    when_to_use=row.get("when_to_use"),
                    category=row.get("category"),
                    folder=row.get("folder") or candidate.folder,
                )

        return self._enrich_via_sibling_file(candidate, source, source_vault)

    def _enrich_candidates_with_registry(
        self, candidates: list, template_sources: list, target_vault: str
    ) -> list:
        """Task 3b (Day77.01): batch registry enrichment for the
        candidate-return (no-confident-match) path — one Base query per
        registry-mode source represented in `candidates` (via
        _get_registry_rows(), same filter-introspection discovery + cache
        as the single-winner path), covering every one of that source's
        candidates in a single round-trip. Never a per-candidate file read
        (that would reintroduce the original perf bug, just at
        candidate-count scale instead of registry-file-count scale).
        Sources with registry: "none", or whose Base lookup fails/misses,
        are left as name-only candidates — this is a pure enhancement,
        never required for the candidate-return response to be useful.

        Mutates and returns `candidates` in place (TemplateCandidate is a
        plain, non-frozen dataclass) — matches the mutate-in-place style
        already used for the single-winner path this mirrors.
        """
        by_source: dict = {}
        for c in candidates:
            by_source.setdefault(c.source_index, []).append(c)

        for source_index, group in by_source.items():
            if not (0 <= source_index < len(template_sources)):
                continue
            source = template_sources[source_index]
            source_vault = source.get("vault_id") or target_vault

            rows = self._get_registry_rows(source_vault, source)
            if not rows:
                continue
            rows_by_name = {
                r.get("template_name"): r for r in rows if isinstance(r, dict) and r.get("template_name")
            }
            for c in group:
                row = rows_by_name.get(c.name)
                if row:
                    c.when_to_use = row.get("when_to_use")
                    c.category = row.get("category")
                    c.folder = row.get("folder") or c.folder

        return candidates

    def _templater_available(self, vault: str) -> bool:
        """Check if Templater is installed in `vault` — used only to decide
        whether the legacy-fallback branch is reachable for unsupported constructs.
        """
        js = "(() => !!app.plugins.getPlugin('templater-obsidian'))()"
        out, code = self._run(vault, "eval", f"code={js}")
        return not self._is_error(out, code) and out.lstrip("=> ").strip() == "true"

    def _template_exists_locally(self, vault: str, template_name: str) -> bool:
        """Check if a template with this basename physically exists in `vault` —
        required before the legacy Templater fallback can run (Templater can
        only resolve templates present in the vault being written to).
        """
        safe_name = template_name.replace("'", "\\'")
        js = (
            f"(()=>{{ const rt='{safe_name}'.toLowerCase();"
            " const all=app.vault.getMarkdownFiles();"
            " return all.some(f=>f.basename.toLowerCase()===rt); })()"
        )
        out, code = self._run(vault, "eval", f"code={js}")
        return not self._is_error(out, code) and out.lstrip("=> ").strip() == "true"

    # ─── Day77.01 Task 4: Templater Interop Guard ────────────────────────────
    #
    # Templater's trigger-on-file-creation processes ANY new file and strips
    # `<% %>` syntax unless the file lands in its template folder or its
    # "ignore folders on file creation" list. Confirmed settings keys (read
    # from a live Templater data.json, 2026-07-16): trigger_on_file_creation
    # (bool) and ignore_folders_on_creation (list[str]). The settings READ
    # below reuses the proven eval pattern used throughout this file; the
    # WRITE + save_settings() persist is a net-new technique — unverified
    # against a live Obsidian instance. Spike this manually (create a raw
    # template file in a guarded folder with Templater's trigger active;
    # confirm syntax survives AND the setting persists across a plugin
    # reload) before relying on it in production. If the write doesn't
    # persist, fall back to surfacing manual instructions in settings (Task 1)
    # instead of auto-writing.

    def get_templater_interop_status(self, vault: str) -> dict:
        """Read Templater's trigger-on-creation setting + ignore-folders list.
        ignoreFolders is normalized to a flat list of folder-path strings for
        callers — Templater's own settings UI stores entries as {folder: string}
        objects (confirmed live, test-vault data.json, 2026-07-16), so the raw
        eval result is mapped here rather than returned as-is.
        """
        js = (
            "(()=>{ const p=app.plugins.getPlugin('templater-obsidian');"
            " if(!p) return JSON.stringify({installed:false});"
            " const s=p.settings||{};"
            " const raw=s.ignore_folders_on_creation||[];"
            " const norm=raw.map(e=>typeof e==='string'?e:(e&&e.folder)||'').filter(Boolean);"
            " return JSON.stringify({installed:true,"
            " triggerOnCreation: !!s.trigger_on_file_creation,"
            " ignoreFolders: norm}); })()"
        )
        out, code = self._run(vault, "eval", f"code={js}")
        if self._is_error(out, code):
            return {"installed": False, "triggerOnCreation": False, "ignoreFolders": []}
        raw = out.lstrip("=> ").strip()
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"installed": False, "triggerOnCreation": False, "ignoreFolders": []}

    def ensure_templater_ignore_folder(self, vault: str, folder: str) -> dict:
        """Add `folder` to Templater's ignore_folders_on_creation list and
        persist via save_settings(), if not already present. No-op
        (guarded=False) when Templater isn't installed or
        trigger_on_file_creation is off — the corruption hazard doesn't exist
        in that case, so nothing needs guarding.

        Writes the {folder: string} object shape Templater's own settings UI
        uses (confirmed live, test-vault data.json, 2026-07-16) — a plain
        string entry persists to disk fine but is invisible to Templater's
        own ignore-check logic, which reads entry.folder.

        Returns {"guarded": bool, "reason": str, "alreadyPresent": bool}.
        Called at template-source configuration time (Task 1 settings UI),
        deliberately before the folder's first file write.
        """
        status = self.get_templater_interop_status(vault)
        if not status.get("installed"):
            return {"guarded": False, "reason": "templater_not_installed", "alreadyPresent": False}
        if not status.get("triggerOnCreation"):
            return {"guarded": False, "reason": "trigger_on_creation_disabled", "alreadyPresent": False}
        if folder in (status.get("ignoreFolders") or []):
            return {"guarded": True, "reason": "already_present", "alreadyPresent": True}

        safe_folder = folder.replace("'", "\\'")
        js = (
            "(async()=>{ const p=app.plugins.getPlugin('templater-obsidian');"
            " if(!p) return JSON.stringify({success:false,error:'not_installed'});"
            " const s=p.settings; const list=s.ignore_folders_on_creation||[];"
            f" const already=list.some(e=>typeof e==='string'?e==='{safe_folder}':e&&e.folder==='{safe_folder}');"
            f" if(!already) list.push({{folder:'{safe_folder}'}});"
            " s.ignore_folders_on_creation=list;"
            " if(typeof p.saveSettings==='function') await p.saveSettings();"
            " else if(typeof p.save_settings==='function') await p.save_settings();"
            " return JSON.stringify({success:true}); })()"
        )
        out, code = self._run(vault, "eval", f"code={js}")
        if self._is_error(out, code):
            return {"guarded": False, "reason": f"eval_failed: {out}", "alreadyPresent": False}
        raw = out.lstrip("=> ").strip()
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"guarded": False, "reason": "unparseable_eval_response", "alreadyPresent": False}
        if not result.get("success"):
            return {"guarded": False, "reason": result.get("error", "unknown_write_failure"), "alreadyPresent": False}
        logger.info(f"[TEMPLATE-GUARD] Added '{folder}' to Templater ignore_folders_on_creation in vault '{vault}'")
        return {"guarded": True, "reason": "added", "alreadyPresent": False}

    def _create_note_with_template_legacy(
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

        Frozen legacy path (Day77.01): this is the pre-native-engine behavior,
        preserved unmodified as the fallback for (a) callers with no
        template_sources configured and (b) unsupported-construct delegation
        when Templater is available and the template exists locally.
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
            " const _ts = app.plugins.getPlugin('templater-obsidian')?.settings;"
            " const _tf = [_ts?.templates_folder, _ts?.company_templates_folder].filter(Boolean);"
            " const _all = app.vault.getFiles();"
            " const _f = _tf.length ? _all.filter(f => _tf.some(d => f.path.startsWith(d + '/'))) : _all;"
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

        # Read scaffold back so caller can update in one step (no extra read call needed)
        note_content = ""
        if created_path:
            read_out, read_code = self._run(vault, "read", f"path={created_path}")
            note_content = read_out if read_code == 0 else ""

        return self._ok({
            "path": created_path,
            "message": f"Created from template: {template_used}",
            "templateUsed": template_used,
            "content": note_content,
            "instructions": "Populate ALL frontmatter fields with correct values. Replace body placeholder content matching the template structure. Do NOT add new frontmatter fields. Do NOT remove existing fields. Write back with update_obsidian_note editing_mode: full_file.",
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
            " const tplSettings = app.plugins.getPlugin('templater-obsidian')?.settings;"
            " const _tf = [tplSettings?.templates_folder, tplSettings?.company_templates_folder].filter(Boolean);"
            " const _all = app.vault.getFiles();"
            " const _af = _tf.length ? _all.filter(f => _tf.some(d => f.path.startsWith(d + '/'))) : _all;"
            " const tplFile = _af.find(f => f.basename.toLowerCase() === rt)"
            "   || _af.find(f => f.basename.toLowerCase().startsWith(rt))"
            "   || _af.find(f => f.basename.toLowerCase().includes(rt) || rt.includes(f.basename.toLowerCase()));"
            " if (!tplFile) return JSON.stringify({folder:''});"
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
            # Compare full basenames (including extension) so that renaming
            # across extensions (e.g. .base → .md) is detected as a name change.
            folder_changed = src_folder != dst_folder
            name_changed = os.path.basename(path) != os.path.basename(new_path)

            if not folder_changed and not name_changed:
                return self._err(f"Source and destination are identical: {path}")

            if folder_changed:
                # Cross-folder move: obsidian move path=<src> to=<dst_folder>
                out, code = self._run(vault, "move", f"path={path}", f"to={dst_folder}")
                if self._is_error(out, code):
                    return self._err(out or f"Move failed: {path} -> {dst_folder}")
                if name_changed:
                    # Name also changed — rename at new location
                    # Use os.path.basename(new_path) which already has the correct extension
                    # from _auto_md() preprocessing (preserves .base, .canvas, etc.)
                    moved_path = f"{dst_folder}/{os.path.basename(path)}" if dst_folder else os.path.basename(path)
                    out, code = self._run(vault, "rename", f"path={moved_path}", f"name={os.path.basename(new_path)}")
            else:
                # Same folder, filename-only rename
                out, code = self._run(vault, "rename", f"path={path}", f"name={os.path.basename(new_path)}")

        elif operation == "copy":
            if not new_path:
                return self._err("new_path required for copy operation")
            safe_src = path.replace("'", "\\'")
            safe_dst = new_path.replace("'", "\\'")
            js = (
                f"(async()=>{{"
                f" const f=app.vault.getFileByPath('{safe_src}');"
                f" if(!f) return 'Error: source not found: {safe_src}';"
                f" const copied=await app.vault.copy(f,'{safe_dst}');"
                f" return copied ? copied.path : 'Error: copy returned null';"
                f"}})()"
            )
            out, code = self._run(vault, "eval", f"code={js}")
            result_val = out.lstrip("=> ").strip()
            if self._is_error(out, code) or result_val.startswith("Error:"):
                return self._err(result_val or f"Copy failed: {path} -> {new_path}")
            return self._ok({"path": path, "newPath": result_val, "operation": "copy"})

        elif operation == "delete":
            out, code = self._run(vault, "delete", f"path={path}")

        else:
            return self._err(f"Unsupported operation: {operation}. Use 'rename', 'copy', or 'delete'.")

        if self._is_error(out, code):
            return self._err(out or f"Operation '{operation}' failed on: {path}")

        return self._ok({"path": path, "newPath": new_path, "operation": operation, "message": out})

    # ─── Cross-Vault Copy/Move (Day75.05) ────────────────────────────────────
    #
    # No native Obsidian Vault API for cross-vault handles — this orchestrates
    # per-vault CLI calls (read src -> write dst -> verify -> [delete src]) in
    # sequence, from within this MCP server process, so the operation appears
    # as a single atomic-looking call from the caller's side.

    def _vault_reachable(self, vault: str) -> bool:
        """Cheap reachability probe used as a preflight check before any
        cross-vault transfer step runs.
        """
        out, code = self._run(vault, "files", timeout=10)
        return code == 0 and not out.startswith("Error:")

    def _scan_cross_vault_links(self, content: str) -> list[str]:
        """Return distinct wikilink/embed targets found in content.
        Link syntax transfers verbatim across vaults and may dangle in the
        target — callers get this list to decide whether to resolve them.
        """
        seen: list[str] = []
        for is_embed, target in _WIKILINK_RE.findall(content):
            label = f"embed: [[{target}]]" if is_embed else f"wikilink: [[{target}]]"
            if label not in seen:
                seen.append(label)
        return seen

    def copy_note_cross_vault(
        self,
        src_vault: str,
        src_path: str,
        dst_vault: str,
        dst_path: str,
        overwrite: bool = False,
    ) -> dict:
        """Copy a note from src_vault to dst_vault via CLI orchestration.
        Source is left untouched. See _cross_vault_transfer for the sequence.
        """
        return self._cross_vault_transfer(
            src_vault, src_path, dst_vault, dst_path, overwrite, delete_source=False
        )

    def move_note_cross_vault(
        self,
        src_vault: str,
        src_path: str,
        dst_vault: str,
        dst_path: str,
        overwrite: bool = False,
    ) -> dict:
        """Move a note from src_vault to dst_vault via CLI orchestration.
        Source is deleted ONLY after the target write is verified. A failed
        delete after a successful write returns MOVE_PARTIAL — never silently
        duplicates or loses data. See _cross_vault_transfer for the sequence.
        """
        return self._cross_vault_transfer(
            src_vault, src_path, dst_vault, dst_path, overwrite, delete_source=True
        )

    def _cross_vault_transfer(
        self,
        src_vault: str,
        src_path: str,
        dst_vault: str,
        dst_path: str,
        overwrite: bool,
        delete_source: bool,
    ) -> dict:
        src_path = self._auto_md(src_path)
        dst_path = self._auto_md(dst_path)
        operation = "move_to_vault" if delete_source else "copy_to_vault"

        # Preflight: both vaults must be CLI-reachable before starting.
        if not self._vault_reachable(src_vault):
            return self._err(f"Source vault unreachable: {src_vault}", "SOURCE_VAULT_UNREACHABLE")
        if not self._vault_reachable(dst_vault):
            return self._err(f"Target vault unreachable: {dst_vault}", "TARGET_VAULT_UNREACHABLE")

        # Source must exist and be readable.
        read_result = self.read_obsidian_note(src_vault, src_path)
        if not read_result["success"]:
            return self._err(f"Source note not found: {src_vault}/{src_path}", "SOURCE_NOT_FOUND")
        content = read_result["payload"]["content"]

        # Target-existence guard — no silent overwrite unless explicitly requested.
        if not overwrite:
            existing = self.read_obsidian_note(dst_vault, dst_path)
            if existing["success"]:
                return self._err(
                    f"Target note already exists: {dst_vault}/{dst_path} "
                    "(pass overwrite=true to replace it)",
                    "TARGET_EXISTS",
                )

        # Write to target via the existing note-creation path.
        write_result = self.create_obsidian_note(dst_vault, dst_path, content)
        if not write_result["success"]:
            return self._err(
                f"Write to target vault failed: {write_result.get('error')}",
                "TARGET_WRITE_FAILED",
            )

        # Verify: read back target and compare against source content.
        verify_result = self.read_obsidian_note(dst_vault, dst_path)
        if not verify_result["success"] or verify_result["payload"]["content"] != content:
            return self._err(
                f"Write verification failed: {dst_vault}/{dst_path} does not match source content",
                "WRITE_VERIFICATION_FAILED",
            )

        warnings = self._scan_cross_vault_links(content)

        if not delete_source:
            return self._ok({
                "path": src_path,
                "newPath": dst_path,
                "sourceVault": src_vault,
                "targetVault": dst_vault,
                "operation": operation,
                "warnings": warnings,
            })

        # Move only: delete source AFTER the verified write. A failed delete
        # never loses data (the copy already succeeded) — report MOVE_PARTIAL,
        # not a hard error, and never retry silently.
        delete_result = self.manage_obsidian_notes(src_vault, "delete", src_path)
        if not delete_result["success"]:
            return {
                "success": False,
                "error": (
                    f"Copy to target succeeded but source cleanup failed: "
                    f"{delete_result.get('error')}"
                ),
                "error_code": "MOVE_PARTIAL",
                "payload": {
                    "path": src_path,
                    "newPath": dst_path,
                    "sourceVault": src_vault,
                    "targetVault": dst_vault,
                    "operation": operation,
                    "warnings": warnings,
                    "targetWriteSucceeded": True,
                    "sourceDeleteFailed": True,
                },
            }

        return self._ok({
            "path": src_path,
            "newPath": dst_path,
            "sourceVault": src_vault,
            "targetVault": dst_vault,
            "operation": operation,
            "warnings": warnings,
        })

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

        elif operation == "clone":
            if not new_folder_path:
                return self._err("new_folder_path required for clone operation")
            safe_src = folder_path.rstrip("/").replace("'", "\\'")
            safe_dst = new_folder_path.rstrip("/").replace("'", "\\'")
            js = (
                f"(async()=>{{"
                f" const folder=app.vault.getFolderByPath('{safe_src}');"
                f" if(!folder) return 'Error: source folder not found: {safe_src}';"
                f" try {{"
                f"   const result=await app.vault.copy(folder,'{safe_dst}');"
                f"   const files=app.vault.getFiles().filter(f=>f.path.startsWith('{safe_dst}/'));"
                f"   return JSON.stringify({{cloned:'{safe_dst}',files:files.length}});"
                f" }} catch(e) {{ return 'Error: ' + e.message; }}"
                f"}})()"
            )
            out, code = self._run(vault, "eval", f"code={js}")
            result_val = out.lstrip("=> ").strip()
            if self._is_error(out, code) or result_val.startswith("Error:"):
                return self._err(result_val or f"Clone failed: {folder_path} -> {new_folder_path}")
            try:
                data = json.loads(result_val)
                return self._ok({"folderPath": folder_path, "newFolderPath": data.get("cloned", new_folder_path), "operation": "clone", "filesCopied": data.get("files", 0)})
            except Exception:
                return self._ok({"folderPath": folder_path, "newFolderPath": new_folder_path, "operation": "clone"})

        else:
            return self._err(f"Unsupported folder operation: {operation}. Use 'create', 'rename', 'delete', or 'clone'.")

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
        """List views in Obsidian's active Base file.

        The current Obsidian CLI does not support selecting a Base for
        ``base:views``. CLIFileTools reads explicitly selected Base YAML files
        itself instead; this method remains for active-file callers only.
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
        limit: Optional[int] = None,
    ) -> dict:
        """Query a base and return structured results.
        CLI: obsidian base:query file=<name> view=<view> format=<format>
        When format=json, the stdout is parsed into a Python object before returning.
        Supported formats: json, csv, tsv, md, paths
        limit: if set, slices the result list to the first N items (json format only).
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
                if limit:
                    parsed = parsed[:limit]
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
