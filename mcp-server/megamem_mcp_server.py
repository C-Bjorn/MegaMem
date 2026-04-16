#!/usr/bin/env python3
"""
Obsidian MegaMem MCP Server - Complete Implementation

Built from scratch using mcp + graphiti-core directly.
Provides 9 MegaMem tools + 9 Obsidian WebSocket tools = 18 total tools.
"""

import sys
import os
import logging
import json
import asyncio
import argparse
import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional
import socket
import subprocess
import psutil
import aiohttp
from datetime import datetime, timezone

# @vessel-protocol:Tyr governs:[system-init|refactor] context:Force UTF-8 stdout for Windows compatibility
# @inter-dependencies: [sys, codecs (builtin)]
# @purpose: Resolve UnicodeEncodeError on Windows during JSON output to console
# @result: Python console output will correctly display Unicode characters, resolving sync failures caused by character encoding issues.
# @signed: C.Bjørn
if sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
# @vessel-close:Tyr

# --- Path Setup ---
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except Exception as e:
    logging.basicConfig(level=logging.DEBUG)
    logging.critical(f"FATAL: Failed to set up Python sys.path: {e}")
    sys.exit(1)

# --- Core MCP Imports ---
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server.lowlevel.helper_types import ReadResourceContents
import mcp.types as types

# ---------------------------------------------------------------------------
# MCP Resource content — synced from vault on each release
# Source: 06_Resources/LLM/Skills/ClaudeDesktop/megamem/SKILL.md (body only)
# ---------------------------------------------------------------------------
MEGAMEM_INSTRUCTIONS = """\
# megamem

22 MCP tools in two categories. Shorthand: **"mm"** / **"my memory"** = graph tools. **"mv"** / **"my vault"** = Obsidian tools.

> For full parameter details on any tool, load: megamem://instructions/reference

## Ground Rules

**group_id** — Always leave blank. Blank = connected vault's name (default). Only set if user explicitly asks to target a namespace. If so, call `list_group_ids` first to confirm the exact value.

**database_id** — Always leave blank (uses default database). Only set if user explicitly names a different database. If so, call `list_databases` first to get the correct `id`.

**Destructive ops** — Always confirm before running `delete_episode`, `delete_entity_edge`, `clear_graph`, `manage_obsidian_notes delete`, `manage_obsidian_folders delete`.

## Key Behaviors

**Creating a note** → prefer `create_note_with_template` when a suitable template exists. Use `create_obsidian_note` only if no template fits.

**Remembering a fact** → `add_memory`. Remembering a conversation → `add_conversation_memory`.

**Syncing a vault note to graph** → `sync_obsidian_note` with vault-relative path (e.g. `Folder/Note.md`). Requires Obsidian running. This is NOT `add_memory` — it pushes an existing note into the graph asynchronously.

**Searching** → `search_obsidian_notes` for vault files. `search_memory_facts` or `search_memory_nodes` for graph knowledge.

**Editing a note** → always `read_obsidian_note` first. For `full_file` overwrites AND `range_based` edits use `include_line_map: true` to get exact line numbers. Avoid `frontmatter_only` for array fields — use `full_file` instead.

**Editing a `.base` file structure** → use `update_obsidian_note` with `full_file`. Use `manage_obsidian_base` for querying/listing only. `.base` files are **YAML**, not JSON. Minimal valid format: `views:\n  - type: table\n    name: My View\n    order:\n      - file.name`. The `filters` key requires `and`/`or`/`not` operator keys — do NOT use an empty array `[]`.

**group_ids in search** — `search_memory_facts` and `search_memory_nodes` take `group_ids` as an **array**: `["namespace"]`.

## On-Demand Skills

For vault-native skill discovery and loading, use the **megamem-skills** skill (trigger: `mms`, `mmskill`, `mm skills`)."""

# ---------------------------------------------------------------------------
# Source: 06_Resources/LLM/Skills/ClaudeDesktop/megamem/references/reference.md
# ---------------------------------------------------------------------------
MEGAMEM_REFERENCE = """\
# MegaMem MCP — Full Parameter Reference

Complete parameter reference for all MegaMem MCP tools. Load this file when you need exact parameter names, types, or constraints not covered in the main instructions.

---

## Graph Memory Tools (mm)

### `add_memory`
| Param | Required | Notes |
|---|---|---|
| `name` | Yes | Episode name |
| `content` | Yes | Memory content |
| `source` | No | text / json / message (default: text) |
| `source_description` | No | |
| `group_id` | No | Leave blank = default |
| `uuid` | No | |
| `database_id` | No | Leave blank = default |

### `add_conversation_memory`
| Param | Required | Notes |
|---|---|---|
| `conversation` | Yes | Array of `{ role: "user"\\|"assistant", content: string, timestamp?: ISO 8601 }` |
| `name` | No | Auto-generated if omitted |
| `group_id` | No | |
| `source_description` | No | Default: "Conversation memory from MCP" |
| `database_id` | No | |

### `search_memory_facts`
| Param | Required | Notes |
|---|---|---|
| `query` | Yes | |
| `max_facts` | No | Default 10 |
| `group_ids` | No | Array — e.g. `["namespace"]` |
| `center_node_uuid` | No | |
| `node_labels` | No | |
| `property_filters` | No | |
| `database_id` | No | |

### `search_memory_nodes`
| Param | Required | Notes |
|---|---|---|
| `query` | Yes | |
| `max_nodes` | No | Default 10 |
| `group_ids` | No | Array — e.g. `["namespace"]` |
| `center_node_uuid` | No | |
| `entity_types` | No | |
| `node_labels` | No | |
| `property_filters` | No | |
| `database_id` | No | |

### `get_episodes`
| Param | Required | Notes |
|---|---|---|
| `group_id` | No | |
| `last_n` | No | Default 10 |
| `database_id` | No | |

### `get_entity_edge`
| Param | Required | Notes |
|---|---|---|
| `entity_name` | Yes | |
| `edge_type` | No | Substring match, not strict filter |
| `group_ids` | No | Array |
| `database_id` | No | |

### `delete_episode`
⚠️ Destructive — confirm before use.
| Param | Required | Notes |
|---|---|---|
| `episode_id` | Yes | UUID |
| `database_id` | No | |

### `delete_entity_edge`
⚠️ Destructive — confirm before use.
| Param | Required | Notes |
|---|---|---|
| `uuid` | Yes | |
| `database_id` | No | |

### `list_group_ids`
No parameters.

### `list_databases`
No parameters. Returns `id`, `label`, `category`, `type` per entry. Use `id` as `database_id`.

### `clear_graph`
⚠️ Destructive — always confirm first. No parameters.

---

## Vault Tools (mv)

### `read_obsidian_note`
| Param | Required | Notes |
|---|---|---|
| `path` | Yes | Vault-relative path |
| `include_line_map` | No | Set `true` before range_based edits (~2x response size) |
| `vault_id` | No | |

### `create_obsidian_note`
| Param | Required | Notes |
|---|---|---|
| `path` | Yes | Full vault-relative path including `.md` |
| `content` | Yes | |
| `vault_id` | No | |

### `update_obsidian_note`
| Param | Required | Notes |
|---|---|---|
| `path` | Yes | |
| `editing_mode` | No | `full_file` (default), `frontmatter_only`, `append_only`, `range_based`, `editor_based` |
| `content` | full_file | Full replacement content |
| `frontmatter_changes` | frontmatter_only | Object of properties to update. ⚠️ Avoid for array fields — use `full_file` instead |
| `append_content` | append_only | |
| `replacement_content` | range_based | |
| `range_start_line` | range_based | 1-based |
| `range_start_char` | range_based | 0-based |
| `range_end_line` | range_based | Optional |
| `range_end_char` | range_based | Optional |
| `editor_method` | editor_based | |
| `vault_id` | No | |

### `create_note_with_template`
| Param | Required | Notes |
|---|---|---|
| `request_type` | Yes | Template name — fuzzy matched |
| `file_name` | Yes | Note title, no `.md` extension |
| `content` | No | Appended after template renders |
| `target_folder` | No | Omit to let template routing handle placement |
| `vault_id` | No | |

### `search_obsidian_notes`
| Param | Required | Notes |
|---|---|---|
| `query` | Yes | |
| `search_mode` | No | `filename` / `content` / `both` (default) |
| `max_results` | No | Default 100 |
| `include_context` | No | Default true |
| `path` | No | Scope to folder |
| `vault_id` | No | |

### `sync_obsidian_note`
| Param | Required | Notes |
|---|---|---|
| `path` | Yes | Vault-relative only. No absolute paths. No vault folder prefix. |
| `vault_id` | No | |

Obsidian must be running with MegaMem active. Sync is asynchronous. This is NOT `add_memory`.

### `manage_obsidian_notes`
| Param | Required | Notes |
|---|---|---|
| `operation` | Yes | `rename`, `delete`, `copy` |
| `path` | Yes | |
| `newPath` | rename / copy | Cross-folder moves auto-detected for rename. For `copy`: destination path for the new file. |
| `vault_id` | No | |

Note: `copy` does NOT update wikilinks (unlike `rename`) — this is expected behavior.

### `manage_obsidian_folders`
| Param | Required | Notes |
|---|---|---|
| `operation` | Yes | `create`, `rename`, `delete`, `clone` |
| `folderPath` | Yes | Note: `folderPath` not `path` |
| `newFolderPath` | rename / clone | Destination path for renamed or cloned folder. |
| `vault_id` | No | |

Note: `clone` deep-copies the entire folder tree using `vault.copy()`. Returns `filesCopied` count. Does NOT update wikilinks.

### `manage_obsidian_base`
| Param | Required | Notes |
|---|---|---|
| `operation` | Yes | `list`, `views`, `query`, `create` |
| `file` | views/query/create | Basename without extension (alternative to `path`) |
| `path` | views/query/create | Full vault-relative path (alternative to `file`) |
| `view` | No | View name — used by `query` and `create` |
| `format` | No | query output: `json` (default), `csv`, `tsv`, `md`, `paths` |
| `name` | No | create: item name |
| `content` | No | create: initial content |
| `vault_id` | No | |

⚠️ Use for querying/listing only. For structural YAML edits to a `.base` file, use `update_obsidian_note` with `full_file`.

Tag filter syntax: `file.tags.containsAny("tagname")`

### `explore_vault_folders`
| Param | Required | Notes |
|---|---|---|
| `query` | No | |
| `path` | No | Scope to folder |
| `format` | No | `tree` / `flat` / `paths` / `smart` (default) |
| `max_depth` | No | Default 3 |
| `include_files` | No | Default false |
| `extension_filter` | No | Filter by file type |
| `vault_id` | No | |

### `list_obsidian_vaults`
No parameters."""

# --- Graphiti Core Imports ---
try:
    import graphiti_core
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.edges import EntityEdge
    from graphiti_core.search.search_config_recipes import (
        NODE_HYBRID_SEARCH_RRF,
        NODE_HYBRID_SEARCH_NODE_DISTANCE,
        EDGE_HYBRID_SEARCH_RRF,
        EDGE_HYBRID_SEARCH_NODE_DISTANCE
    )
    from graphiti_core.search.search_filters import SearchFilters
except ImportError as e:
    logging.critical(f"FATAL: Could not import graphiti-core: {e}")
    sys.exit(1)

# --- Local Imports ---
try:
    from websocket_server import WebSocketServer
    from file_tools import FileTools
    from vault_resolver import VaultResolver
except ImportError:
    WebSocketServer, FileTools, VaultResolver = None, None, None

# CLI file tools — optional, activated via MEGAMEM_USE_CLI=true env var
try:
    from cli_file_tools import CLIFileTools
    from obsidian_cli import detect_obsidian_binary
except ImportError:
    CLIFileTools = None  # type: ignore
    detect_obsidian_binary = None  # type: ignore

# Bridge imports
try:
    from graphiti_bridge.config import BridgeConfig, setup_environment_variables
    from graphiti_bridge.sync import initialize_graphiti as init_megamem_bridge
    from graphiti_bridge.models import get_entity_types_with_config
except ImportError as e:
    logging.critical(f"FATAL: Could not import graphiti_bridge modules: {e}")
    sys.exit(1)

# Remote RPC bridge import
try:
    from remote_rpc_bridge import RemoteRPCBridge
except ImportError:
    RemoteRPCBridge = None

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress aiohttp access logging spam
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

# --- Constants ---
OBSIDIAN_FILE_OPERATIONS = {
    "search_obsidian_notes",
    "read_obsidian_note",
    "update_obsidian_note",
    "create_obsidian_note",
    "list_obsidian_vaults",
    "explore_vault_folders",
    "create_note_with_template",
    "manage_obsidian_folders",
    "manage_obsidian_notes",
    "sync_obsidian_note",
    "manage_obsidian_base",
}

# --- Token-Scoped Access Control ---

@dataclass
class TokenProfile:
    """Per-token access policy for the Streamable HTTP transport.
    @purpose: Allowlist-based tool gating per bearer token @depends: httpTokenProfiles in data.json @results: Server-side MCP access control
    """
    id: str = ''
    label: str = ''
    token: str = ''
    # Empty lists = no restriction (admin). Non-empty = strict allowlist.
    allowed_tools: List[str] = dc_field(default_factory=list)
    allowed_group_ids: List[str] = dc_field(default_factory=list)
    allowed_databases: List[str] = dc_field(default_factory=list)
    allowed_vaults: List[str] = dc_field(default_factory=list)

# Set by BearerAuthMiddleware on each HTTP request; read by list_tools / call_tool.
# Default None = stdio mode (no profile → full access).
current_token_profile: ContextVar[Optional[TokenProfile]] = ContextVar('current_token_profile', default=None)

# Tools that accept group_ids (plural list) — override target for namespace enforcement
_TOOLS_WITH_GROUP_IDS = frozenset({
    'search_memory_nodes', 'search_memory_facts', 'get_entity_edge'
})
# Tools that accept group_id (singular) — single-value override
_TOOLS_WITH_GROUP_ID = frozenset({
    'add_memory', 'add_conversation_memory', 'get_episodes'
})

# --- Template Discovery Helper ---

def _get_available_templates(vault_path: str) -> str:
    """
    Scan vault for Templater template files and return a formatted list
    for injection into the create_note_with_template tool description.
    Reads both templates_folder (personal) and company_templates_folder from Templater data.json.
    Company templates listed first, personal appended — deduped by stem (company wins).
    Falls back gracefully if vault path or templates folder is unavailable — never throws.
    @purpose: Live template discovery at startup @depends: vault_path, Templater data.json @results: Formatted template list string for tool description
    """
    try:
        vault = Path(vault_path)
        templater_config = vault / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
        if not templater_config.exists():
            raise FileNotFoundError(f"Templater data.json not found: {templater_config}")

        with open(templater_config, 'r', encoding='utf-8') as f:
            tdata = json.load(f)

        # Mirror PluginDetectionHelper.ts: check top-level first, then settings sub-object
        personal_folder = (
            tdata.get("templates_folder") or
            (tdata.get("settings") or {}).get("templates_folder")
        )
        if not personal_folder:
            raise ValueError("Templater templates_folder not configured in data.json")

        company_folder = tdata.get("company_templates_folder") or ""

        def _scan(folder: str) -> list:
            d = vault / folder
            return sorted(p.stem for p in d.glob("*.md")) if d.is_dir() else []

        company_names = _scan(company_folder) if company_folder else []
        personal_names = _scan(personal_folder)

        # Company first; dedupe — personal name dropped if company already has it
        seen = set(company_names)
        names = company_names + [n for n in personal_names if n not in seen]

        if not names:
            raise ValueError("No template files found in configured template folders")

        return f"Available templates (use exact name or close match):\n  {', '.join(names)}"
    except Exception:
        return "Available templates: scan unavailable — use TPL + type name (e.g. TPL Person, TPL Note, TPL Meeting)"


# --- Complete MCP Server Implementation ---


class ObsidianMegaMemMCPServer:
    """
    Complete MCP server providing 18 tools:
    - 9 Graphiti graph operations (including conversation memory)
    - 9 Obsidian file operations via WebSocket
    """

    def __init__(self):
        self.server = Server("megamem")
        self.megamem_client = None
        self.websocket_server = None
        self.file_tools = None
        self.websocket_startup_error = None
        self.bridge_config = None
        self.vault_resolver = VaultResolver()
        self.ws_port = None  # Store port for error messages
        # Per-DB Graphiti client cache (database_id → Graphiti instance)
        self._db_clients: Dict[str, Any] = {}
        
        # @purpose: Async initialization state tracking @depends: asyncio.Event @results: Fast MCP startup with background loading
        self.initialization_complete = False
        self.resource_loading_task = None
        self.ready_event = asyncio.Event()
        self.embedder_healthy = True  # Set False if embedder health check fails at startup
        self._template_list_description = "Available templates: scan unavailable — use TPL + type name (e.g. TPL Person, TPL Note, TPL Meeting)"

        # @purpose: Episode queuing to prevent race conditions @depends: asyncio.Queue @results: Sequential episode processing per group_id
        self.episode_queues: Dict[str, asyncio.Queue] = {}
        self.queue_workers: Dict[str, bool] = {}

        # @purpose: Token profiles for HTTP transport gating @depends: httpTokenProfiles in data.json @results: Per-token access control
        self.http_token_profiles: List[Dict] = []

        # Register all tool handlers
        self._register_tool_handlers()

    def _register_tool_handlers(self):
        """Register all MCP tool handlers"""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """Return tools — filtered by token profile for HTTP clients, full list for stdio."""
            tools = []
            tools.extend(self._get_megamem_tool_definitions())
            tools.extend(self._get_obsidian_tool_definitions())

            profile = current_token_profile.get()
            if profile and profile.allowed_tools:
                tools = [t for t in tools if t.name in profile.allowed_tools]

            logger.info(f"Returning {len(tools)} tools")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
            """Route tool calls to appropriate handlers"""
            logger.info(f"Calling tool: {name}")
            arguments = arguments or {}

            # --- Token-scoped gating ---
            profile = current_token_profile.get()
            if profile and profile.allowed_tools:
                if name not in profile.allowed_tools:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Tool '{name}' is not permitted for this token",
                        "code": "TOOL_NOT_PERMITTED"
                    }))]

            # group_ids override — prevents namespace exfiltration via crafted params
            if profile and profile.allowed_group_ids:
                arguments = dict(arguments)
                if name in _TOOLS_WITH_GROUP_IDS:
                    arguments['group_ids'] = list(profile.allowed_group_ids)
                if name in _TOOLS_WITH_GROUP_ID:
                    arguments['group_id'] = profile.allowed_group_ids[0]

            # database_id enforcement (graphiti tools only — obsidian tools don't accept database_id)
            if profile and profile.allowed_databases and name not in OBSIDIAN_FILE_OPERATIONS:
                db_id = arguments.get('database_id')
                if not db_id:
                    # No database_id specified — auto-inject first allowed DB
                    arguments = dict(arguments)
                    arguments['database_id'] = profile.allowed_databases[0]
                elif db_id not in profile.allowed_databases:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Database '{db_id}' is not permitted for this token",
                        "code": "DATABASE_NOT_PERMITTED"
                    }))]

            # vault_id enforcement for Obsidian tools
            if profile and profile.allowed_vaults and name in OBSIDIAN_FILE_OPERATIONS:
                vault_id = arguments.get('vault_id')
                if not vault_id:
                    arguments = dict(arguments)
                    arguments['vault_id'] = profile.allowed_vaults[0]
                elif vault_id not in profile.allowed_vaults:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Vault '{vault_id}' is not permitted for this token",
                        "code": "VAULT_NOT_PERMITTED"
                    }))]
            # --- End gating ---

            try:
                if name in OBSIDIAN_FILE_OPERATIONS:
                    return await self._handle_obsidian_tool(name, arguments)
                else:
                    return await self._handle_graphiti_tool(name, arguments)
            except Exception as e:
                logger.error(f"Error in tool '{name}': {e}", exc_info=True)
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": str(e)})
                )]

        @self.server.list_resources()
        async def list_resources() -> List[types.Resource]:
            return [
                types.Resource(
                    uri="megamem://status",
                    name="MegaMem Server Status",
                    description="Health check for Graphiti and Obsidian connections"
                ),
                types.Resource(
                    uri="megamem://instructions",
                    name="MegaMem Instructions",
                    description="Behavioral rules and shorthands for all MegaMem MCP tools. Read at session start.",
                    mimeType="text/markdown"
                ),
                types.Resource(
                    uri="megamem://instructions/reference",
                    name="MegaMem Reference",
                    description="Full parameter reference for all MegaMem tools. Load on demand when exact params needed.",
                    mimeType="text/markdown"
                ),
            ]

        @self.server.read_resource()
        async def read_resource(uri) -> list[ReadResourceContents]:
            # str(uri) handles both plain str and Pydantic AnyUrl; rstrip('/') handles trailing-slash normalization
            uri_str = str(uri).rstrip('/')
            if uri_str == "megamem://status":
                status = {
                    "graphiti": "ok" if self.megamem_client and self.megamem_client != "RPC_MODE" else "disconnected",
                    "obsidian": "ok" if self.file_tools else "disconnected",
                    "database": self.bridge_config.database_type if self.bridge_config else "unknown"
                }
                config_path = os.environ.get("OBSIDIAN_CONFIG_PATH", "")
                if config_path:
                    log_path = Path(config_path).parent / "logs" / "consolidated.log"
                    try:
                        if log_path.exists():
                            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                            status["recent_log"] = lines[-100:]
                    except Exception:
                        pass
                return [ReadResourceContents(content=json.dumps(status, indent=2), mime_type="application/json")]

            if uri_str == "megamem://instructions":
                return [ReadResourceContents(content=MEGAMEM_INSTRUCTIONS, mime_type="text/markdown")]

            if uri_str == "megamem://instructions/reference":
                return [ReadResourceContents(content=MEGAMEM_REFERENCE, mime_type="text/markdown")]

            raise ValueError(f"Unknown resource URI: {uri_str}")

    def _get_megamem_tool_definitions(self) -> List[Tool]:
        """Define all 9 Graphiti tools"""
        return [
            Tool(
                name="add_memory",
                description="Add a memory/episode to the graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the episode"},
                        "content": {"type": "string", "description": "The memory content to add (episode_body)"},
                        "source": {"type": "string", "description": "Source type (text, json, message)", "default": "text"},
                        "source_description": {"type": "string", "description": "Description of the source"},
                        "group_id": {"type": "string", "description": "Group ID for organizing memories"},
                        "uuid": {"type": "string", "description": "Optional UUID for the episode"},
                        "namespace": {"type": "string", "description": "DEPRECATED: Use group_id instead", "default": "megamem-vault"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                    },
                    "required": ["name", "content"]
                }
            ),
            Tool(
                name="search_memory_nodes",
                description="Search for nodes in the memory graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_nodes": {"type": "integer", "description": "Max results", "default": 10},
                        "group_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of group IDs to search in"},
                        "center_node_uuid": {"type": "string", "description": "UUID of node to center search around (proximity search)"},
                        "entity_types": {"type": "array", "items": {"type": "string"}, "description": "Filter by entity types (e.g., ['Person', 'Company'])"},
                        "node_labels": {"type": "array", "items": {"type": "string"}, "description": "Filter by node label types (e.g. ['Person', 'Organization'])"},
                        "property_filters": {"type": "object", "description": "Filter by specific node/edge properties (e.g. {\"status\": \"active\"})"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label). e.g. 'notes-vault', 'CompanyName Graph'"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="search_memory_facts",
                description="Search for facts/relationships in the memory graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_facts": {"type": "integer", "description": "Max results", "default": 10},
                        "group_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of group IDs to search in"},
                        "center_node_uuid": {"type": "string", "description": "UUID of node to center search around (proximity search)"},
                        "node_labels": {"type": "array", "items": {"type": "string"}, "description": "Filter by node label types (e.g. ['Person', 'Organization'])"},
                        "property_filters": {"type": "object", "description": "Filter by specific node/edge properties (e.g. {\"status\": \"active\"})"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label)"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="list_databases",
                description="List all configured database targets. Use this to discover which databases are available before querying with database_id. (aliases: mm, megamem, memory)",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="get_episodes",
                description="Get episodes from the memory graph (aliases: mm, megamem, memory)",
                inputSchema={
                     "type": "object",
                     "properties": {
                         "group_id": {"type": "string", "description": "Group ID to retrieve episodes from"},
                         "last_n": {"type": "integer", "description": "Number of most recent episodes to retrieve", "default": 10},
                         "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                     }
                }
            ),
            Tool(
                name="clear_graph",
                description="Clear the entire memory graph (aliases: mm, megamem, memory)",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="get_entity_edge",
                description="Get entity edges from the graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "Entity name"},
                        "edge_type": {"type": "string", "description": "Edge type (optional)"},
                        "group_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of group IDs to scope the search (prevents cross-group data leakage)"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                    },
                    "required": ["entity_name"]
                }
            ),
            Tool(
                name="delete_entity_edge",
                description="Delete entity edges from the graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "uuid": {"type": "string", "description": "UUID of the entity edge to delete"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                    },
                    "required": ["uuid"]
                }
            ),
            Tool(
                name="delete_episode",
                description="Delete an episode from the graph (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string", "description": "Episode ID to delete"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                    },
                    "required": ["episode_id"]
                }
            ),
            Tool(
                name="list_group_ids",
                description="List all available group IDs (namespaces) in the vault (aliases: mm, megamem, memory)",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="add_conversation_memory",
                description="Add a conversation to the graph using Graphiti's message format. CLIENT provides summaries for assistant messages - server formats and stores. (aliases: mm, megamem, memory)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name for conversation episode"},
                        "conversation": {
                            "type": "array",
                            "description": "Array of message objects",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string", "enum": ["user", "assistant"], "description": "Message role"},
                                    "content": {"type": "string", "description": "Message content"},
                                    "timestamp": {"type": "string", "description": "Optional ISO 8601 timestamp"}
                                },
                                "required": ["role", "content"]
                            }
                        },
                        "group_id": {"type": "string", "description": "Group ID for organizing memories"},
                        "source_description": {"type": "string", "description": "Source description", "default": "Conversation memory from MCP"},
                        "database_id": {"type": "string", "description": "Optional: target a specific named database (id or label from Databases settings)"}
                    },
                    "required": ["conversation"]
                }
            )
        ]

    def _get_obsidian_tool_definitions(self) -> List[Tool]:
        """Define all Obsidian WebSocket tools"""
        return [
            Tool(
                name="search_obsidian_notes",
                description="Search for notes in Obsidian vault by filename and/or content (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (required)"},
                        "search_mode": {
                            "type": "string",
                            "enum": ["filename", "content", "both"],
                            "default": "both",
                            "description": "Search mode: filename, content, or both"
                        },
                        "max_results": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "default": 100,
                            "description": "Maximum number of results to return"
                        },
                        "include_context": {
                            "anyOf": [{"type": "boolean"}, {"type": "string"}],
                            "default": True,
                            "description": "Include context snippets for content matches"
                        },
                        "path": {"type": "string", "description": "Path to search within the vault (optional)"},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="read_obsidian_note",
                description="Read a specific note from Obsidian (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Note path"},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"},
                        "include_line_map": {
                            "anyOf": [{"type": "boolean"}, {"type": "string"}],
                            "default": False,
                            "description": "Include line-by-line mapping and section detection for precise editing (increases response size ~2x)"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="update_obsidian_note",
                description="Update content of an existing note using various editing modes: full_file, frontmatter_only, append_only, range_based, editor_based (aliases: mv, my vault, obsidian, update note, edit note). For range_based mode, always call read_obsidian_note with include_line_map=true first to get exact line numbers.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Note path"},
                        "editing_mode": {
                            "type": "string",
                            "enum": ["full_file", "frontmatter_only", "append_only", "range_based", "editor_based"],
                            "description": "The editing mode to use",
                            "default": "full_file"
                        },
                        "content": {"type": "string", "description": "New content (used for full_file mode)"},
                        "frontmatter_changes": {
                            "description": "Object containing frontmatter properties to update (used for frontmatter_only mode). Pass as an object or JSON string. WARNING: Do NOT pass array values (e.g. tags) via frontmatter_changes — the YAML serializer will drop the closing --- fence, corrupting the file. For any update that includes array fields, use full_file mode instead."
                        },
                        "append_content": {
                            "type": "string",
                            "description": "Content to append to the end of the file (used for append_only mode)"
                        },
                        "replacement_content": {
                            "type": "string",
                            "description": "Content to replace within the specified range (used for range_based mode)"
                        },
                        "range_start_line": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "description": "Starting line number (1-based) for range replacement"
                        },
                        "range_start_char": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "description": "Starting character position (0-based) within the start line"
                        },
                        "range_end_line": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "description": "Ending line number (1-based) for range replacement (optional, defaults to start_line)"
                        },
                        "range_end_char": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "description": "Ending character position (0-based) within the end line (optional, defaults to end of line)"
                        },
                        "editor_method": {
                            "type": "string",
                            "description": "Predefined editor method to use (used for editor_based mode)"
                        },
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="create_obsidian_note",
                description="Create a new note in Obsidian (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Note path"},
                        "content": {"type": "string", "description": "Note content"},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["path", "content"]
                }
            ),
            Tool(
                name="list_obsidian_vaults",
                description="List all available Obsidian vaults (aliases: mv, my vault, obsidian)",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="explore_vault_folders",
                description="Explore folder structure in an Obsidian vault (query by natural language or path).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language or path query (optional)"
                        },
                        "path": {
                            "type": "string",
                            "description": "Explicit vault path to explore (optional)"
                        },
                        "format": {
                            "type": "string",
                            "description": "Preferred output format: tree|flat|paths|smart",
                            "default": "smart"
                        },
                        "max_depth": {
                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                            "description": "Maximum traversal depth",
                            "default": 3
                        },
                        "vault_id": {
                            "type": "string",
                            "description": "Vault ID (optional)"
                        },
                        "include_files": {
                            "anyOf": [{"type": "boolean"}, {"type": "string"}],
                            "description": "Include files in the folder listing alongside folders. Default false.",
                            "default": False
                        },
                        "extension_filter": {
                            "type": "array",
                            "description": "Optional list of file extensions to filter results (e.g. ['md', 'canvas']). Only used when include_files is true.",
                            "items": {"type": "string"}
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="create_note_with_template",
                description=f"""Create Obsidian note from Templater template. Template list in request_type.

ROUTING: Templater folder_templates → MegaMem inbox → vault root. TPL Project→03_Projects/{{Name}}/; TPL ProjectDoc→project subfolders; entity templates→04_Entities/.

WORKFLOW: 1) create (response includes `content` scaffold + `instructions`) 2) update_obsidian_note to fill sections 3) offer remaining""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "request_type": {"type": "string", "description": f"Template name to use (fuzzy-matched). {self._template_list_description}"},
                        "file_name": {"type": "string", "description": "Filename to create (required)"},
                        "content": {"type": "string", "description": "Optional content to append after template processing"},
                        "target_folder": {"type": "string", "description": "Override folder. Most templates self-route via Templater mappings; omit unless forcing a specific location."},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["request_type", "file_name"]
                }
            ),
            Tool(
                name="manage_obsidian_folders",
                description="Manage folders in Obsidian vault - create, rename/move, delete, or clone folders (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "rename", "delete", "clone"],
                            "description": "Folder operation to perform. 'clone' duplicates the entire folder tree to a new path."
                        },
                        "folderPath": {
                            "type": "string",
                            "description": "Path to the folder (source path for rename/delete/clone, target path for create)"
                        },
                        "newFolderPath": {
                            "type": "string",
                            "description": "New folder path (required for rename and clone operations)"
                        },
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["operation", "folderPath"]
                }
            ),
            Tool(
                name="manage_obsidian_notes",
                description="Delete, rename, or copy notes in Obsidian vault (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["delete", "rename", "copy"],
                            "description": "The operation to perform. 'copy' duplicates the note to newPath (can include a new filename to rename on copy)."
                        },
                        "path": {
                            "type": "string",
                            "description": "The note path for delete/copy, or the old path for rename"
                        },
                        "newPath": {
                            "type": "string",
                            "description": "The destination path (required for rename and copy operations)"
                        },
                        "vault_id": {
                            "type": "string",
                            "description": "Optional vault ID to target specific vault"
                        }
                    },
                    "required": ["operation", "path"]
                }
            ),
            Tool(
                name="sync_obsidian_note",
                description="Sync a specific note to the graph by path. Opens the note and triggers the registered sync command. Use only on-demand when user requests sync after updating a note. Sync completes asynchronously after this tool returns.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Vault-relative path to the note (e.g. 'My Notes/SomeNote.md'). Do NOT use absolute system paths or prefix with the vault folder name."},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="manage_obsidian_base",
                description="Manage Obsidian Bases files — list bases, list views, query data, or create items (aliases: mv, my vault, obsidian, bases)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["list", "views", "query", "create"],
                            "description": "Operation to perform. 'list': list all .base files (no other params needed). 'views': list views in a base (requires file or path). 'query': query base data and return results (requires file or path; use format param to control output). 'create': create a new item/row in a base (requires file or path)."
                        },
                        "file": {
                            "type": "string",
                            "description": "Base filename (without extension). Used by: views, query, create."
                        },
                        "path": {
                            "type": "string",
                            "description": "Full vault-relative path to the .base file (alternative to file). Used by: views, query, create."
                        },
                        "view": {
                            "type": "string",
                            "description": "View name within the base. Used by: query (optional), create (optional)."
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "csv", "tsv", "md", "paths"],
                            "default": "json",
                            "description": "Output format for query results. json (default) returns parsed structured data. Used by: query."
                        },
                        "name": {
                            "type": "string",
                            "description": "Name/title for the new item. Used by: create."
                        },
                        "content": {
                            "type": "string",
                            "description": "Initial content for the new item. Used by: create."
                        },
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["operation"]
                }
            ),
        ]

    async def process_episode_queue(self, group_id: str):
        """Process episodes for a group_id sequentially"""
        self.queue_workers[group_id] = True
        try:
            while True:
                process_func = await self.episode_queues[group_id].get()
                try:
                    await process_func()
                except Exception as e:
                    logger.error(f"Episode processing error for {group_id}: {e}")
                finally:
                    self.episode_queues[group_id].task_done()
        except asyncio.CancelledError:
            logger.info(f"Queue worker for {group_id} cancelled")
        finally:
            self.queue_workers[group_id] = False

    def _format_fact_result(self, edge: Any) -> Dict[str, Any]:
        """Formats an EntityEdge into a serializable dictionary."""
        if not hasattr(edge, 'model_dump'):
            # Fallback for unexpected types
            return {"uuid": str(getattr(edge, 'uuid', '')), "fact": str(edge)}

        result = edge.model_dump(
            mode='json',
            exclude={'fact_embedding'},
        )
        if 'attributes' in result and result['attributes']:
            result['attributes'].pop('fact_embedding', None)
        return result

    async def _handle_graphiti_tool(self, name: str, arguments: Dict) -> List[types.TextContent]:
        """Handle Graphiti tool calls"""
        if not self.megamem_client:
            return [types.TextContent(
                type="text",
                text=json.dumps(
                    {"success": False, "error": "Graphiti client not initialized"})
            )]

        # If we're in RPC mode, return helpful error directing to Process 1
        if self.megamem_client == "RPC_MODE":
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "MegaMem tools are handled by Process 1 (WebSocket server). This is Process 2 (RPC client) - MegaMem tools automatically available in the main Claude session.",
                    "note": "No action needed - MegaMem tools work transparently across both processes."
                })
            )]

        # @purpose: Wait for background resource loading to complete @depends: ready_event @results: Tools work only when fully initialized
        if not self.initialization_complete:
            try:
                await asyncio.wait_for(self.ready_event.wait(), timeout=20.0)
            except asyncio.TimeoutError:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "MegaMem initialization still in progress - please try again in a few moments"
                    })
                )]

        # @purpose: Gate search/edge tools when embedder is unreachable @depends: embedder_healthy @results: Clear error instead of raw APIConnectionError
        _EMBEDDER_REQUIRED = {"search_memory_nodes", "search_memory_facts", "get_entity_edge"}
        if name in _EMBEDDER_REQUIRED and not self.embedder_healthy:
            provider = self.bridge_config.embedder_provider if self.bridge_config else 'ollama'
            if provider == 'ollama':
                msg = "Embedder unreachable: Ollama is not running (start with: ollama serve)"
            else:
                msg = f"Embedder unreachable ({provider}): start the embedder service before using search tools"
            return [types.TextContent(type="text", text=json.dumps({"success": False, "error": msg}))]

        try:
            if name == "add_memory":
                group_id_str = arguments.get("group_id") or self.bridge_config.default_namespace
                
                async def process_episode():
                    # Map content parameter to episode_body for backward compatibility
                    episode_body = arguments["content"]

                    # Generate default name if not provided
                    name_param = arguments.get("name")
                    if not name_param:
                        name_param = f"Episode_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                    # Map source string to EpisodeType enum
                    source_str = arguments.get("source", "text")
                    source_type = EpisodeType.text
                    if source_str.lower() == "message":
                        source_type = EpisodeType.message
                    elif source_str.lower() == "json":
                        source_type = EpisodeType.json

                    # Read config to check for custom ontology usage
                    config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
                    if not config_path:
                        raise ValueError("OBSIDIAN_CONFIG_PATH not set")
                    logger.info(f"Loading config from: {config_path}")
                    with open(config_path, 'r') as f:
                        obsidian_config = json.load(f)

                    # Prepend mm_contributor if episodeContributor is configured
                    contributor = obsidian_config.get('episodeContributor', '') or ''
                    if contributor:
                        episode_body = f"mm_contributor: {contributor}\n\n{episode_body}"

                    entity_types = {}
                    use_custom = obsidian_config.get('useCustomOntology')
                    if use_custom:
                        logger.info("[INFO] Custom ontology enabled. Loading custom entity types.")
                        entity_types = get_entity_types_with_config(obsidian_config)
                    else:
                        logger.info("[INFO] Custom ontology disabled.")

                    logger.info(f"Entity types loaded: {list(entity_types.keys())}")
                    logger.info(f"Number of entity types: {len(entity_types)}")

                    episode_kwargs = {
                        'name': name_param,
                        'episode_body': episode_body,
                        'source': source_type,
                        'source_description': arguments.get('source_description', "MCP server memory addition"),
                        'group_id': group_id_str,
                        'uuid': arguments.get('uuid'),
                        'reference_time': datetime.now(timezone.utc),
                        'entity_types': entity_types
                    }
                    db_id = arguments.get('database_id')
                    client = await self._get_graphiti_client(db_id)
                    await client.add_episode(**episode_kwargs)
                
                # Queue management
                if group_id_str not in self.episode_queues:
                    self.episode_queues[group_id_str] = asyncio.Queue()
                
                position = self.episode_queues[group_id_str].qsize() + 1
                await self.episode_queues[group_id_str].put(process_episode)
                
                if not self.queue_workers.get(group_id_str, False):
                    asyncio.create_task(self.process_episode_queue(group_id_str))
                
                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "message": f"Episode queued (position: {position})"
                }))]

            elif name == "list_databases":
                try:
                    obsidian_config = self._load_obsidian_config()
                    databases = obsidian_config.get('databases', [])
                    result = []
                    for db in databases:
                        result.append({
                            'id': db.get('id'),
                            'label': db.get('label'),
                            'type': db.get('type'),
                            'category': db.get('category'),
                            'enabled': db.get('enabled', True),
                            'vault_id': db.get('vaultId'),
                            'connection': (db.get('uri') or f"{db.get('host', 'localhost')}:{db.get('port', 6379)}")
                        })
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": True,
                        "databases": result,
                        "count": len(result)
                    }))]
                except Exception as e:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False, "error": str(e)
                    }))]

            elif name == "search_memory_nodes":
                database_id = arguments.get('database_id')
                client = await self._get_graphiti_client(database_id)
                group_ids = arguments.get('group_ids') or [
                    self.bridge_config.default_namespace]
                max_nodes = arguments.get("max_nodes", 10)
                center_node_uuid = arguments.get("center_node_uuid")
                entity_types = arguments.get("entity_types", [])

                if center_node_uuid:
                    search_config = NODE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
                else:
                    search_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                search_config.limit = max_nodes

                filters = SearchFilters()
                if entity_types:
                    filters.node_labels = entity_types
                node_labels = arguments.get("node_labels")
                if node_labels:
                    filters.node_labels = node_labels
                property_filters = arguments.get("property_filters")
                if property_filters:
                    filters.property_filters = property_filters

                results = await client._search(
                    query=arguments["query"],
                    config=search_config,
                    group_ids=group_ids,
                    center_node_uuid=center_node_uuid,
                    search_filter=filters
                )

                formatted_nodes = [{
                    'uuid': node.uuid,
                    'name': node.name,
                    'summary': node.summary if hasattr(node, 'summary') else '',
                    'labels': node.labels if hasattr(node, 'labels') else [],
                    'group_id': node.group_id,
                    'created_at': node.created_at.isoformat(),
                    'attributes': node.attributes if hasattr(node, 'attributes') else {},
                } for node in results.nodes]

                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "results": formatted_nodes,
                    **({"database": database_id} if database_id else {})
                }))]

            elif name == "search_memory_facts":
                database_id = arguments.get('database_id')
                client = await self._get_graphiti_client(database_id)
                group_ids = arguments.get('group_ids') or [
                    self.bridge_config.default_namespace]
                max_facts = arguments.get("max_facts", 10)
                center_node_uuid = arguments.get("center_node_uuid")

                if center_node_uuid:
                    search_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
                else:
                    search_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                search_config.limit = max_facts

                fact_filters = SearchFilters()
                fact_node_labels = arguments.get("node_labels")
                if fact_node_labels:
                    fact_filters.node_labels = fact_node_labels
                fact_property_filters = arguments.get("property_filters")
                if fact_property_filters:
                    fact_filters.property_filters = fact_property_filters

                results = await client._search(
                    query=arguments["query"],
                    config=search_config,
                    group_ids=group_ids,
                    center_node_uuid=center_node_uuid,
                    search_filter=fact_filters
                )

                formatted_facts = [self._format_fact_result(
                    edge) for edge in results.edges]
                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "facts": formatted_facts,
                    **({"database": database_id} if database_id else {})
                }))]

            elif name == "get_episodes":
                # Get group_id and last_n from arguments

                last_n = arguments.get("last_n", 10)
                database_id = arguments.get('database_id')
                client = await self._get_graphiti_client(database_id)

                # Call retrieve_episodes
                episodes = await client.retrieve_episodes(
                    group_ids=[arguments.get(
                        'group_id') or self.bridge_config.default_namespace],
                    last_n=last_n,
                    reference_time=datetime.now(timezone.utc)
                )

                # Format results using episode.model_dump(mode='json')
                formatted_episodes = [
                    episode.model_dump(mode='json') for episode in episodes
                ]

                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "episodes": formatted_episodes,
                    "count": len(formatted_episodes)
                }))]

            elif name == "clear_graph":
                await self.megamem_client.close()
                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "message": "Graph cleared successfully"
                }))]

            elif name == "get_entity_edge":
                try:
                    entity_name = arguments.get("entity_name")
                    if not entity_name:
                        return [types.TextContent(type="text", text=json.dumps({
                            "success": False,
                            "error": "entity_name is required"
                        }))]
                    edge_type = arguments.get("edge_type")
                    group_ids = arguments.get("group_ids")
                    database_id = arguments.get('database_id')
                    client = await self._get_graphiti_client(database_id)
                    edges = []

                    if group_ids:
                        # Scoped search — use _search with group_ids to prevent cross-group leakage
                        search_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        search_config.limit = 25
                        results = await client._search(
                            query=entity_name,
                            config=search_config,
                            group_ids=group_ids
                        )
                        for result in results.edges:
                            edge_info = self._format_fact_result(result)
                            if edge_type and edge_type.lower() not in edge_info.get("fact", "").lower():
                                continue
                            edges.append(edge_info)
                    else:
                        # Unscoped — backward-compatible, searches all groups
                        search_results = await client.search(entity_name)
                        for result in (search_results or []):
                            valid_at_val = getattr(result, 'valid_at', '')
                            invalid_at_val = getattr(result, 'invalid_at', '')
                            edge_info = {
                                "uuid": str(result.uuid),
                                "fact": getattr(result, 'fact', ''),
                                "source_node_uuid": str(getattr(result, 'source_node_uuid', '')),
                                "target_node_uuid": str(getattr(result, 'target_node_uuid', '')),
                                "valid_at": valid_at_val.isoformat() if isinstance(valid_at_val, datetime) else valid_at_val,
                                "invalid_at": invalid_at_val.isoformat() if isinstance(invalid_at_val, datetime) else invalid_at_val
                            }
                            if edge_type and edge_type.lower() not in edge_info["fact"].lower():
                                continue
                            edges.append(edge_info)

                    return [types.TextContent(type="text", text=json.dumps({
                        "success": True,
                        "entity": entity_name,
                        "edge_type": edge_type,
                        "edges": edges,
                        "count": len(edges)
                    }))]

                except Exception as e:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Failed to get entity edges: {str(e)}",
                        "entity": arguments.get("entity_name")
                    }))]

            elif name == "delete_entity_edge":
                try:
                    uuid = arguments.get("uuid")
                    if not uuid:
                        return [types.TextContent(type="text", text=json.dumps({"success": False, "error": "uuid is required"}))]

                    database_id = arguments.get('database_id')
                    client = await self._get_graphiti_client(database_id)
                    entity_edge = await EntityEdge.get_by_uuid(client.driver, uuid)
                    await entity_edge.delete(client.driver)

                    return [types.TextContent(type="text", text=json.dumps({
                        "success": True,
                        "message": f"Entity edge with UUID {uuid} deleted successfully"
                    }))]
                except Exception as e:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Error deleting entity edge: {str(e)}"
                    }))]

            elif name == "delete_episode":
                # Use the remove_episode method from graphiti-core
                try:
                    episode_id = arguments.get("episode_id")
                    if not episode_id:
                        return [types.TextContent(type="text", text=json.dumps({
                            "success": False,
                            "error": "episode_id is required"
                        }))]

                    # Call the remove_episode method
                    database_id = arguments.get('database_id')
                    client = await self._get_graphiti_client(database_id)
                    await client.remove_episode(episode_id)

                    return [types.TextContent(type="text", text=json.dumps({
                        "success": True,
                        "episode_id": episode_id,
                        "message": "Episode deleted successfully"
                    }))]

                except Exception as e:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Failed to delete episode: {str(e)}",
                        "episode_id": arguments.get("episode_id")
                    }))]

            elif name == "list_group_ids":
                try:
                    config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
                    if not config_path:
                        raise ValueError("OBSIDIAN_CONFIG_PATH not set")
                    with open(config_path, 'r') as f:
                        obsidian_config = json.load(f)

                    # Get available namespaces
                    available_namespaces = obsidian_config.get('availableNamespaces', [])

                    # Get group_ids from folder namespace mappings
                    folder_mappings = obsidian_config.get('folderNamespaceMappings', [])
                    folder_group_ids = [mapping.get('groupId') for mapping in folder_mappings if mapping.get('groupId')]

                    # Combine both lists and remove duplicates
                    all_group_ids = list(set(available_namespaces + folder_group_ids))

                    # Ensure default namespace is included
                    default_ns = self.bridge_config.default_namespace
                    if default_ns not in all_group_ids:
                        all_group_ids.append(default_ns)

                    return [types.TextContent(type="text", text=json.dumps({
                        "success": True,
                        "group_ids": sorted(all_group_ids),
                        "count": len(all_group_ids),
                        "current_default": default_ns
                    }))]
                except Exception as e:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Failed to list group IDs: {str(e)}"
                    }))]

            elif name == "add_conversation_memory":
                # @purpose: Store conversation using Graphiti message format @depends: conversation array @results: Formatted episode queued for background processing
                conversation = arguments.get("conversation")
                if not conversation or not isinstance(conversation, list):
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "conversation parameter required and must be an array"
                    }))]

                # Format each message as "[timestamp] role: content"
                formatted_lines = []
                for msg in conversation:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    timestamp = msg.get("timestamp")

                    if not timestamp:
                        timestamp = datetime.now(timezone.utc).isoformat()

                    formatted_lines.append(f"[{timestamp}] {role}: {content}")

                episode_body = "\n".join(formatted_lines)

                # Generate name if not provided
                name_param = arguments.get("name")
                if not name_param:
                    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                    name_param = f"Conversation_{timestamp}"

                # Get group_id or use default
                group_id = arguments.get("group_id") or self.bridge_config.default_namespace

                # Get source_description
                source_description = arguments.get("source_description", "Conversation memory from MCP")

                async def process_episode():
                    config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
                    if not config_path:
                        raise ValueError("OBSIDIAN_CONFIG_PATH not set")

                    with open(config_path, 'r') as f:
                        obsidian_config = json.load(f)

                    # Prepend mm_contributor if episodeContributor is configured
                    contributor = obsidian_config.get('episodeContributor', '') or ''
                    body = f"mm_contributor: {contributor}\n\n{episode_body}" if contributor else episode_body

                    entity_types = {}
                    if obsidian_config.get('useCustomOntology'):
                        entity_types = get_entity_types_with_config(obsidian_config)

                    episode_kwargs = {
                        'name': name_param,
                        'episode_body': body,
                        'source': EpisodeType.text,
                        'source_description': source_description,
                        'group_id': group_id,
                        'reference_time': datetime.now(timezone.utc),
                        'entity_types': entity_types
                    }
                    db_id = arguments.get('database_id')
                    client = await self._get_graphiti_client(db_id)
                    await client.add_episode(**episode_kwargs)

                # Queue management
                if group_id not in self.episode_queues:
                    self.episode_queues[group_id] = asyncio.Queue()

                position = self.episode_queues[group_id].qsize() + 1
                await self.episode_queues[group_id].put(process_episode)

                if not self.queue_workers.get(group_id, False):
                    asyncio.create_task(self.process_episode_queue(group_id))

                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "message": f"Episode queued (position: {position})"
                }))]

            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Unknown MegaMem tool: {name}"
                }))]

        except Exception as e:
            embedder_provider = self.bridge_config.embedder_provider if self.bridge_config else ''
            if 'APIConnectionError' in type(e).__name__ and embedder_provider == 'ollama':
                friendly_msg = "Embedder unreachable: Ollama is not running (start with: ollama serve)"
                logger.error(f"[EMBEDDER ERROR] {friendly_msg}")
                self.embedder_healthy = False
                return [types.TextContent(type="text", text=json.dumps({"success": False, "error": friendly_msg}))]
            logger.error(f"MegaMem tool error: {e}", exc_info=True)
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"MegaMem operation failed: {str(e)}"
            }))]

    async def _handle_obsidian_tool(self, name: str, arguments: Dict) -> List[types.TextContent]:
        """Handle Obsidian WebSocket tool calls"""
        if not self.file_tools:
            port_info = self.ws_port or "unknown"
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"WebSocket server not running. Expected on port {port_info}",
                "details": self.websocket_startup_error or "Server not initialized"
            }))]

        try:
            # @@vessel-protocol:Bifrost governs:integration context:Unified folder management routing via operation parameter
            if name == "manage_obsidian_folders":
                return await self._handle_manage_obsidian_folders(arguments)

            # Handle note management operations
            if name == "manage_obsidian_notes":
                return await self._handle_manage_obsidian_notes(arguments)

            # Provide explicit wrapper for create_note_with_template to ensure argument names match and
            # to give a clear routing point for future adjustments.
            if name == "create_note_with_template":
                return await self._handle_create_note_with_template(arguments)

            # Defensive: ensure method exists on FileTools before calling
            if not hasattr(self.file_tools, name):
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"FileTools has no operation named '{name}'"
                }))]

            method = getattr(self.file_tools, name)
            # Normalize arguments to match Python method signatures (snake_case expected)
            normalized_args = {}
            for k, v in (arguments or {}).items():
                normalized_key = k
                # map common camelCase to snake_case used in FileTools
                if k == "vaultId":
                    normalized_key = "vault_id"
                if k == "targetFolder":
                    normalized_key = "target_folder"
                if k == "fileName":
                    normalized_key = "file_name"
                # Pass through new search parameters explicitly so they reach FileTools unchanged
                if k in ("search_mode", "searchMode"):
                    normalized_key = "search_mode"
                if k in ("max_results", "maxResults"):
                    normalized_key = "max_results"
                if k in ("include_context", "includeContext"):
                    normalized_key = "include_context"
                if k in ("include_line_map", "includeLineMap"):
                    normalized_key = "include_line_map"
                # Pass through editing mode parameters for update_obsidian_note
                if k in ("editing_mode", "frontmatter_changes", "append_content", "replacement_content",
                         "range_start_line", "range_start_char", "range_end_line", "range_end_char", "editor_method"):
                    normalized_key = k
                # Map 'operation' parameter to 'editing_mode' for update_obsidian_note backward compatibility
                # Do NOT remap for manage_obsidian_base or other tools that use 'operation' natively
                if k == "operation" and name == "update_obsidian_note":
                    normalized_key = "editing_mode"
                    if v == "frontmatter":
                        v = "frontmatter_only"
                    elif v == "append":
                        v = "append_only"
                    elif v == "range":
                        v = "range_based"
                    elif v == "editor":
                        v = "editor_based"
                    elif v == "full":
                        v = "full_file"
                # Map ALL editor operation parameter names to bypass editor_params routing
                if k in ("line_number", "lineNumber"):
                    normalized_key = "line"
                if k in ("character_position", "characterPosition"):
                    normalized_key = "char"
                if k in ("from_line", "fromLine"):
                    normalized_key = "fromLine"
                if k in ("from_char", "fromChar"):
                    normalized_key = "fromChar"
                if k in ("to_line", "toLine"):
                    normalized_key = "toLine"
                if k in ("to_char", "toChar"):
                    normalized_key = "toChar"
                if k in ("heading"):
                    normalized_key = "heading"
                # Map range_based operation parameter names
                if k == "range_start_line":
                    normalized_key = "range_start_line"
                if k == "range_start_char":
                    normalized_key = "range_start_char"
                if k == "range_end_line":
                    normalized_key = "range_end_line"
                if k == "range_end_char":
                    normalized_key = "range_end_char"
                # Map content parameter variations for editor operations (but preserve replacement_content for range_based)
                if k in ("content", "insert_content", "line_content", "new_content"):
                    normalized_key = "content"
                # Only map replacement_content to content for editor_based, not range_based
                if k == "replacement_content" and normalized_args.get("editing_mode") == "editor_based":
                    normalized_key = "content"

                normalized_args[normalized_key] = v

            # Coerce string-serialized args to correct native types.
            # Some Agent SDK frameworks stringify all non-string params before sending.
            _COERCE_INT  = {"range_start_line", "range_start_char", "range_end_line",
                            "range_end_char", "max_results", "max_depth"}
            _COERCE_BOOL = {"include_line_map", "include_context", "include_files"}
            _COERCE_JSON = {"frontmatter_changes"}
            for _k in list(normalized_args.keys()):
                _v = normalized_args[_k]
                if not isinstance(_v, str):
                    continue
                if _k in _COERCE_INT:
                    try:
                        normalized_args[_k] = int(_v)
                    except (ValueError, TypeError):
                        pass
                elif _k in _COERCE_BOOL:
                    normalized_args[_k] = _v.lower() in ("true", "1", "yes")
                elif _k in _COERCE_JSON:
                    try:
                        normalized_args[_k] = json.loads(_v)
                    except (ValueError, TypeError):
                        pass

            result = await method(**normalized_args)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error(f"Obsidian tool error: {e}", exc_info=True)
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": str(e)
            }))]

    async def initialize(self):
        """Initialize both Graphiti client and WebSocket server with discovery and fallback"""
        logger.info(
            "[START] Initializing Obsidian MegaMem MCP Server with 18 tools...")

        try:
            config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
            if not config_path:
                raise ValueError(
                    "OBSIDIAN_CONFIG_PATH environment variable not set.")

            with open(config_path, 'r') as f:
                obsidian_config = json.load(f)

            # @purpose: Cache token profiles for HTTP transport gating @depends: httpTokenProfiles in data.json @results: Available to _run_http_server()
            self.http_token_profiles = obsidian_config.get('httpTokenProfiles', [])

            # Derive vault path from config_path (e.g. .../vault/.obsidian/plugins/.../data.json → vault root)
            _config_path_obj = Path(config_path)
            _obsidian_idx = next((i for i, p in enumerate(_config_path_obj.parts) if p == ".obsidian"), -1)
            if _obsidian_idx > 0:
                _vault_path = str(Path(*_config_path_obj.parts[:_obsidian_idx]))
                self._template_list_description = _get_available_templates(_vault_path)
                logger.info(f"[TEMPLATES] Discovered templates from: {_vault_path}")

            # Initialize WebSocket configuration
            self.ws_port = obsidian_config.get("wsPort", 41484)
            ws_config = {
                "port": self.ws_port,
                "auth_token": obsidian_config.get("wsAuthToken", ""),
            }
            logger.info(
                f"[CONFIG] WebSocket port: {ws_config['port']} (from OBSIDIAN_CONFIG_PATH)")

            # CLI file tools — activated via useCliFileTools: true in plugin settings (data.json)
            # Falls back to env var MEGAMEM_USE_CLI=true for headless/dev use
            _use_cli = bool(obsidian_config.get("useCliFileTools", False)) or \
                       os.environ.get("MEGAMEM_USE_CLI", "false").lower() in ("true", "1", "yes")

            if _use_cli and CLIFileTools and detect_obsidian_binary:
                cli_binary = detect_obsidian_binary()
                if cli_binary:
                    logger.info(f"[CLI] useCliFileTools=true — activating CLI backend: {cli_binary}")
                    from obsidian_cli import ObsidianCLI
                    cli_instance = CLIFileTools(cli=ObsidianCLI(cli_binary))

                    # Derive default vault name from OBSIDIAN_CONFIG_PATH
                    # e.g. ".../my-vault/.obsidian/plugins/..." → "my-vault"
                    config_path_str = os.environ.get("OBSIDIAN_CONFIG_PATH", "")
                    if config_path_str:
                        parts = config_path_str.replace("\\", "/").split("/")
                        obs_idx = next((i for i, p in enumerate(parts) if p == ".obsidian"), -1)
                        if obs_idx > 0:
                            cli_instance._default_vault = parts[obs_idx - 1]
                            logger.info(f"[CLI] Default vault: {cli_instance._default_vault}")

                    self.file_tools = cli_instance
                    websocket_success = True  # Treat CLI as successful "connection"
                else:
                    logger.warning("[CLI] useCliFileTools=true but Obsidian CLI binary not found. Falling back to WebSocket.")
                    _use_cli = False

            if not _use_cli:
                # Always start with WebSocket discovery to determine process role quickly
                websocket_success = await self._discover_or_start_websocket_server_with_autolaunch(ws_config, obsidian_config)

            # Check if we're in RPC mode (Process 2) - if so, skip expensive initialization
            if self.megamem_client == "RPC_MODE":
                logger.info(
                    "[PROCESS 2] Optimized startup complete - MegaMem tools routed to Process 1")
                self.bridge_config = self._create_bridge_config(
                    obsidian_config, config_path)
                self.initialization_complete = True
                self.ready_event.set()

            # Otherwise we're Process 1 (WebSocket server) - start background loading
            elif websocket_success and self.file_tools:
                logger.info(
                    "[PROCESS 1] WebSocket server role - starting background Graphiti initialization")

                bridge_config = self._create_bridge_config(
                    obsidian_config, config_path)
                self.bridge_config = bridge_config
                
                # @purpose: Start background resource loading task @depends: bridge_config @results: Non-blocking initialization
                self.resource_loading_task = asyncio.create_task(
                    self._background_resource_loading(bridge_config)
                )
            else:
                logger.warning(
                    "[WARNING] WebSocket/RPC connection failed. Tools will show errors.")
                self.initialization_complete = True
                self.ready_event.set()

            # Log final status
            websocket_status = "[SUCCESS]" if self.file_tools else "[ERROR]"
            logger.info(
                f"[COMPLETE] MCP Server ready! WebSocket: {websocket_status} | MegaMem: Loading in background")
            logger.info(
                "[INFO] All 19 tools available: 9 Graphiti + 10 Obsidian")

        except Exception as e:
            logger.critical(
                f"[FATAL] MCP initialization failed: {e}", exc_info=True)
            self.initialization_complete = True
            self.ready_event.set()
            raise

    async def _background_resource_loading(self, bridge_config: BridgeConfig):
        """Background task for heavy resource loading"""
        try:
            logger.info("[BACKGROUND] Starting MegaMem client initialization...")
            setup_environment_variables(bridge_config)

            # @purpose: Yield the event loop before any blocking work
            # @depends: asyncio.sleep
            # @results: server.run() processes and sends the MCP initialize response
            #           before BGE/Graphiti loading blocks the event loop (~36s)
            await asyncio.sleep(1.0)

            megamem_client = await init_megamem_bridge(bridge_config, debug=True)
            if not megamem_client:
                raise ValueError("MegaMem client initialization failed (returned None).")
            self.megamem_client = megamem_client

            # @purpose: Embedder health check @depends: megamem_client @results: Clear startup log if Ollama/embedder unreachable
            try:
                hc_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                hc_config.limit = 1
                # Suppress graphiti-core's internal "Error executing" stderr spam during this probe —
                # we handle the exception ourselves below
                import logging as _logging
                _gcore_logger = _logging.getLogger("graphiti_core")
                _prev_level = _gcore_logger.level
                _gcore_logger.setLevel(_logging.CRITICAL)
                try:
                    await self.megamem_client._search(
                        query="health",
                        config=hc_config,
                        group_ids=[bridge_config.default_namespace]
                    )
                finally:
                    _gcore_logger.setLevel(_prev_level)
                logger.info("[BACKGROUND] Embedder health check passed")
            except Exception as embed_err:
                err_str = str(embed_err)
                err_type = type(embed_err).__name__
                # Only mark embedder unhealthy for actual connectivity failures, not Neo4j data errors
                # e.g. dimension mismatch in stored embeddings is a data issue, not an embedder issue
                _EMBEDDER_CONN_ERRORS = ('APIConnectionError', 'ConnectionRefusedError', 'ConnectError',
                                         'ConnectionError', 'OllamaError', 'HTTPStatusError')
                is_embedder_conn_err = (
                    any(x in err_type for x in _EMBEDDER_CONN_ERRORS) or
                    any(x in err_str for x in ('Connection refused', 'connect ECONNREFUSED',
                                               'Failed to establish', 'ollama serve'))
                )
                if is_embedder_conn_err:
                    self.embedder_healthy = False
                    provider = bridge_config.embedder_provider
                    base_url = bridge_config.ollama_base_url or 'http://localhost:11434'
                    if provider == 'ollama':
                        logger.error(
                            f"[EMBEDDER ERROR] Ollama is not running or unreachable at {base_url}. "
                            f"Run: ollama serve. (actual error: {embed_err})"
                        )
                    else:
                        logger.error(f"[EMBEDDER ERROR] Embedder unreachable ({provider}): {embed_err}")
                else:
                    # Neo4j/data error (e.g. dimension mismatch) — embedder is healthy, log as warning
                    logger.warning(
                        f"[EMBEDDER HEALTH] Health check query failed with non-embedder error "
                        f"(embedder marked healthy): {err_type}: {embed_err}"
                    )

            # Initialize DB constraints after graphiti client is ready
            logger.info("[BACKGROUND] Building database indices...")
            try:
                await self.megamem_client.build_indices_and_constraints()
                logger.info("[BACKGROUND] Database indices built successfully")
            except Exception as e:
                if "EquivalentSchemaRuleAlreadyExists" in str(e) or "already exists" in str(e):
                    logger.info("[BACKGROUND] Database indices already exist")
                else:
                    logger.error(f"[BACKGROUND] Failed to build database indices: {e}")
                    raise
            
            self.initialization_complete = True
            self.ready_event.set()
            logger.info("[BACKGROUND] MegaMem initialization complete - tools ready")
            
        except Exception as e:
            logger.error(f"[BACKGROUND] Resource loading failed: {e}", exc_info=True)
            self.initialization_complete = True
            self.ready_event.set()
            # Do NOT re-raise — this is a fire-and-forget asyncio task; raising propagates
            # into anyio's TaskGroup inside stdio_server() and crashes the entire MCP server.

    # @vessel-protocol:Heimdall governs:discovery context:Server discovery with integrated auto-launch for seamless user experience
    # @inter-dependencies: [RemoteRPCBridge, WebSocketServer, FileTools, aiohttp, obsidian auto-launch]
    # @purpose: Combine health probing, server discovery, RPC client fallback, and Obsidian auto-launch in optimal order
    # @result: MCP processes launch Obsidian if needed, then establish WebSocket connections without user intervention
    # @signed: C.Bjørn
    async def _discover_or_start_websocket_server_with_autolaunch(self, ws_config: Dict, obsidian_config: Dict) -> bool:
        """Discover existing server via health check or start new server with integrated Obsidian auto-launch"""
        port = ws_config.get("port", 41484)  # Default port
        auth_token = ws_config.get("auth_token", "")

        # Step 1: Check for existing server (fast)
        logger.info(
            f"[INFO] Probing for existing WebSocket server on port {port}")
        health_result = await self._probe_health_endpoint(port, auth_token)

        if health_result["success"]:
            logger.info(
                "[PROCESS 2] Using existing WebSocket server as RPC client")
            if RemoteRPCBridge:
                try:
                    rpc_bridge = RemoteRPCBridge(
                        f"http://127.0.0.1:{port}", auth_token)
                    self.file_tools = FileTools(rpc_bridge)
                    self.websocket_startup_error = None
                    return True
                except Exception as e:
                    logger.error(f"[ERROR] Failed to create RPC bridge: {e}")
                    return False
            else:
                logger.error(
                    "[ERROR] RemoteRPCBridge not available - cannot use RPC mode")
                return False

        # Step 2: No existing server found - ensure Obsidian is running BEFORE starting our own server
        logger.info(
            "[INFO] No existing server found - ensuring Obsidian is running before starting WebSocket server")
        await self._ensure_obsidian_running(obsidian_config)

        # Step 3: Start our own WebSocket server
        logger.info("[INFO] Starting WebSocket server after Obsidian launch")
        try:
            # Import the global server starter
            from websocket_server import start_websocket_server

            # This will raise OSError if port is in use
            self.websocket_server = await start_websocket_server(
                port=int(port),
                auth_token=auth_token
            )

            # Success! We're the server
            logger.info(f"[PROCESS 1] WebSocket server started on port {port}")
            logger.info(
                "[PROCESS 1] WebSocket server ready for MegaMem plugin connections")

            # Use local WebSocket server directly
            self.file_tools = FileTools(self.websocket_server)
            self.websocket_startup_error = None
            return True

        except OSError as e:
            # Windows/Mac/Linux "Address in use"
            if hasattr(e, 'errno') and e.errno in [10048, 48, 98]:
                # This is EXPECTED for the second process Claude starts
                logger.info(
                    f"[PROCESS 2] Port {port} in use - becoming RPC client")
                if RemoteRPCBridge:
                    try:
                        rpc_bridge = RemoteRPCBridge(
                            f"http://127.0.0.1:{port}", auth_token)
                        self.file_tools = FileTools(rpc_bridge)
                        logger.info(
                            "[PROCESS 2] Successfully connected as RPC client - optimized mode enabled")
                        self.websocket_startup_error = None

                        # Mark this as RPC client to skip expensive operations
                        self.megamem_client = "RPC_MODE"
                        return True
                    except Exception as rpc_e:
                        logger.error(
                            f"[ERROR] RPC bridge connection failed: {rpc_e}")
                        return False
                else:
                    logger.error("[ERROR] RemoteRPCBridge not available")
                    return False
            else:
                logger.error(f"[ERROR] WebSocket server startup failed: {e}")
                return False

    async def _verify_obsidian_connection_via_rpc(self, obsidian_config: Dict):
        """Verify Obsidian connection when using RPC bridge to existing server"""
        try:
            # Check if plugin is connected via existing server
            plugin_connected = await self._is_megamem_plugin_connected()
            if not plugin_connected:
                logger.info(
                    "[INFO] Plugin not connected to existing server - ensuring Obsidian is running")
                await self._ensure_obsidian_running(obsidian_config)
        except Exception as e:
            logger.warning(
                f"[WARNING] Could not verify Obsidian connection via RPC: {e}")

    # @vessel-protocol:Heimdall governs:discovery context:Legacy server discovery method for fallback compatibility
    # @inter-dependencies: [RemoteRPCBridge, WebSocketServer, FileTools, aiohttp]
    # @purpose: Maintain original server discovery logic for backward compatibility
    # @result: MCP processes can share a single WebSocket server or fall back to RPC communication without port conflicts
    # @signed: C.Bjørn
    async def _discover_or_start_websocket_server(self, ws_config: Dict) -> bool:
        """Discover existing server via health check or start new server with RPC fallback"""
        port = ws_config.get("port", 41484)  # Default port
        auth_token = ws_config.get("auth_token", "")

        # Step 1: Try to discover existing server via health check
        logger.info(
            f"[INFO] Probing for existing WebSocket server on port {port}")
        health_result = await self._probe_health_endpoint(port, auth_token)

        if health_result["success"]:
            logger.info(
                "[SUCCESS] Discovered existing WebSocket server - using RPC bridge")
            if RemoteRPCBridge:
                try:
                    # Use remote RPC bridge for inter-process communication
                    rpc_bridge = RemoteRPCBridge(
                        f"http://127.0.0.1:{port}", auth_token)
                    self.file_tools = FileTools(rpc_bridge)
                    self.websocket_startup_error = None
                    return True
                except Exception as e:
                    logger.error(f"[ERROR] Failed to create RPC bridge: {e}")
                    self.websocket_startup_error = f"RPC bridge creation failed: {e}"
                    return False
            else:
                logger.error(
                    "[ERROR] RemoteRPCBridge not available - cannot use RPC mode")
                self.websocket_startup_error = "RemoteRPCBridge not available"
                return False
        elif health_result["status_code"] == 401:
            # Authentication failed - clear error message and fall back to RPC mode
            logger.error(
                "[ERROR] Authentication failed - token mismatch with existing server")
            logger.error(
                "[ERROR] Check OBSIDIAN_CONFIG_PATH wsAuthToken matches across all MCP clients")
            self.websocket_startup_error = "Authentication failed - token mismatch"
            # Still try RPC bridge as it will handle auth consistently
            if RemoteRPCBridge:
                try:
                    rpc_bridge = RemoteRPCBridge(
                        f"http://127.0.0.1:{port}", auth_token)
                    self.file_tools = FileTools(rpc_bridge)
                    return True
                except Exception as e:
                    logger.error(f"[ERROR] RPC bridge with auth failed: {e}")
                    return False
            return False

        # Step 2: No existing server found - try to start our own WebSocket server
        logger.info(
            "[INFO] No existing server found - attempting to start WebSocket server")
        try:
            # Import the global server starter
            from websocket_server import start_websocket_server

            # Start server using global function
            self.websocket_server = await start_websocket_server(
                port=int(port),
                auth_token=auth_token
            )

            # Use local WebSocket server directly
            self.file_tools = FileTools(self.websocket_server)
            logger.info(f"[SUCCESS] WebSocket server started on port {port}")
            self.websocket_startup_error = None
            return True

        except OSError as e:
            error_str = str(e).lower()
            if "already in use" in error_str or "address already in use" in error_str or "10048" in error_str:
                # Port conflict during startup - retry health probe and fall back to RPC client mode
                logger.info(
                    f"[INFO] Port {port} in use during startup - retrying server discovery")

                # Re-attempt health probe in case another process started server
                retry_health = await self._probe_health_endpoint(int(port), auth_token)
                if retry_health["success"] and RemoteRPCBridge:
                    try:
                        rpc_bridge = RemoteRPCBridge(
                            f"http://127.0.0.1:{port}", auth_token)
                        self.file_tools = FileTools(rpc_bridge)
                        logger.info(
                            "[SUCCESS] Server discovered on retry - using RPC bridge")
                        self.websocket_startup_error = None
                        return True
                    except Exception as rpc_e:
                        logger.error(
                            f"[ERROR] RPC bridge retry failed: {rpc_e}")

                # Final fallback - no server available
                logger.error(
                    f"[ERROR] Port {port} in use and no server responding to health checks")
                self.websocket_startup_error = f"Port conflict on {port} - no accessible server found"
                return False
            else:
                logger.error(f"[ERROR] WebSocket server startup failed: {e}")
                self.websocket_startup_error = f"Server startup failed: {e}"
                return False
        except Exception as e:
            logger.error(f"[ERROR] Unexpected server startup failure: {e}")
            self.websocket_startup_error = f"Unexpected startup failure: {e}"
            return False

    async def _probe_health_endpoint(self, port: int, auth_token: str) -> Dict:
        """Probe /health endpoint to discover existing WebSocket server"""
        try:
            # Short timeout for discovery
            timeout = aiohttp.ClientTimeout(total=0.2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "Authorization": f"Bearer {auth_token}"} if auth_token else {}
                url = f"http://127.0.0.1:{port}/health"

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(
                            f"[INFO] Health check successful - server status: {data.get('status', 'unknown')}")
                        return {"success": True, "data": data, "status_code": 200}
                    elif response.status == 401:
                        logger.warning(
                            "[WARNING] Health check failed - authentication required")
                        return {"success": False, "status_code": 401, "error": "Authentication failed"}
                    else:
                        logger.warning(
                            f"[WARNING] Health check failed - HTTP {response.status}")
                        return {"success": False, "status_code": response.status, "error": f"HTTP {response.status}"}

        except aiohttp.ClientConnectorError:
            # No server listening on port
            logger.info("[INFO] No server found on health probe")
            return {"success": False, "status_code": 0, "error": "Connection refused"}
        except asyncio.TimeoutError:
            logger.warning("[WARNING] Health check timeout")
            return {"success": False, "status_code": 0, "error": "Timeout"}
        except Exception as e:
            logger.warning(f"[WARNING] Health check failed: {e}")
            return {"success": False, "status_code": 0, "error": str(e)}
    # @vessel-close:Heimdall

    # @vessel-protocol:Bifrost governs:integration context:Unified folder management handler routing operations to FileTools
    # @inter-dependencies: [FileTools.create_obsidian_folder, FileTools.rename_obsidian_folder, FileTools.delete_obsidian_folder]
    # @purpose: Route folder operations based on operation parameter to appropriate FileTools methods
    # @result: Unified folder management through single MCP tool interface
    # @signed: C.Bjørn
    async def _handle_manage_obsidian_folders(self, arguments: Dict[str, Any]) -> List[types.TextContent]:
        """Handle unified folder management operations with operation parameter routing."""
        try:
            operation = arguments.get("operation")
            folder_path = arguments.get("folderPath")
            new_folder_path = arguments.get(
                "newFolderPath")  # Only for rename operation
            vault_id = arguments.get("vault_id")

            # Validate required parameters
            if not operation:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "Missing required parameter 'operation'"
                }))]

            if not folder_path:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "Missing required parameter 'folderPath'"
                }))]

            # Route to appropriate FileTools method based on operation
            if operation == "create":
                result = await self.file_tools.create_obsidian_folder(folder_path, vault_id)
            elif operation == "rename":
                if not new_folder_path:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "Missing required parameter 'newFolderPath' for rename operation"
                    }))]
                result = await self.file_tools.rename_obsidian_folder(folder_path, new_folder_path, vault_id)
            elif operation == "delete":
                result = await self.file_tools.delete_obsidian_folder(folder_path, vault_id)
            elif operation == "clone":
                if not new_folder_path:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "Missing required parameter 'newFolderPath' for clone operation"
                    }))]
                result = await self.file_tools.manage_obsidian_folders("clone", folder_path, vault_id, new_folder_path)
            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Invalid operation '{operation}'. Must be one of: create, rename, delete, clone"
                }))]

            return [types.TextContent(type="text", text=json.dumps(result))]

        except Exception as e:
            logger.error(f"Error in _handle_manage_obsidian_folders: {str(e)}")
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Failed to manage folder: {str(e)}"
            }))]
    # @vessel-close:Bifrost

    async def _handle_manage_obsidian_notes(self, arguments: Dict[str, Any]) -> List[types.TextContent]:
        """Handle manage_obsidian_notes tool call"""
        try:
            operation = arguments.get("operation")
            path = arguments.get("path")
            new_path = arguments.get("newPath")
            vault_id = arguments.get("vault_id")

            if not operation:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "Missing required parameter 'operation'"
                }))]

            if not path:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "Missing required parameter 'path'"
                }))]

            if operation == "delete":
                result = await self.file_tools.delete_obsidian_note(path, vault_id)
            elif operation == "rename":
                if not new_path:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "Missing required parameter 'newPath' for rename operation"
                    }))]
                result = await self.file_tools.rename_obsidian_note(path, new_path, vault_id)
            elif operation == "copy":
                if not new_path:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "Missing required parameter 'newPath' for copy operation"
                    }))]
                result = await self.file_tools.manage_obsidian_notes("copy", path, vault_id, new_path)
            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Invalid operation '{operation}'. Must be one of: delete, rename, copy"
                }))]

            return [types.TextContent(type="text", text=json.dumps(result))]

        except Exception as e:
            logger.error(f"Error in _handle_manage_obsidian_notes: {str(e)}")
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Failed to manage note: {str(e)}"
            }))]

    async def _handle_create_note_with_template(self, arguments: Dict[str, Any]) -> List[types.TextContent]:
        """
        Wrapper to call FileTools.create_note_with_template ensuring argument names match
        and returning the standardized MCP TextContent response.
        Expected args: request_type, file_name, content (optional), target_folder (optional), vault_id (optional)
        """
        try:
            # Normalize arguments and provide defaults
            request_type = arguments.get("request_type", "")
            file_name = arguments.get("file_name")
            if not file_name:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "file_name is required"
                }))]

            content = arguments.get("content", "")
            target_folder = arguments.get("target_folder", "")
            vault_id = arguments.get("vault_id", None)

            # Call the FileTools method
            result = await self.file_tools.create_note_with_template(
                request_type=request_type,
                file_name=file_name,
                content=content,
                target_folder=target_folder,
                vault_id=vault_id
            )

            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error(
                f"_handle_create_note_with_template error: {e}", exc_info=True)
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": str(e)
            }))]

    async def _check_port_in_use(self, port: int) -> bool:
        """Check if a port is already in use"""
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                result = sock.connect_ex(('localhost', port))
                # 0 means connection successful (port in use)
                return result == 0
        except Exception:
            return False

    def _load_obsidian_config(self) -> Dict:
        """Load the current data.json from OBSIDIAN_CONFIG_PATH"""
        config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
        if not config_path:
            raise ValueError("OBSIDIAN_CONFIG_PATH not set")
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _resolve_database_config(self, database_id: str, obsidian_config: Dict) -> Optional[Dict]:
        """Find a named DbConfig from databases[] by id or label (case-insensitive label match)
        @purpose: Multi-DB routing — maps user-friendly database_id to connection config"""
        databases = obsidian_config.get('databases', [])
        # Exact id match first
        for db in databases:
            if db.get('id') == database_id:
                return db
        # Fuzzy label match
        database_id_lower = database_id.lower()
        for db in databases:
            if db.get('label', '').lower() == database_id_lower:
                return db
        return None

    def _create_bridge_config_for_db(self, db_config: Dict, obsidian_config: Dict) -> 'BridgeConfig':
        """Build a BridgeConfig from a named DbConfig entry (for per-DB client creation)"""
        config_path = os.environ.get('OBSIDIAN_CONFIG_PATH', '')
        db_type = db_config.get('type', 'neo4j')

        if db_type == 'neo4j':
            database_url = db_config.get('uri', 'bolt://localhost:7687')
        else:
            host = db_config.get('host', 'localhost')
            port = db_config.get('port', 6379)
            database_url = f'bolt://{host}:{port}'

        # Embedding: per-DB override → global fallback
        embed_provider = db_config.get('embedderProvider') or obsidian_config.get('embedderProvider', 'openai')
        embed_model = db_config.get('embeddingModel') or obsidian_config.get('embeddingModel', 'text-embedding-3-small')

        return BridgeConfig(
            llm_provider=obsidian_config.get('llmProvider', 'openai'),
            llm_model=obsidian_config.get('llmModel', 'gpt-4o'),
            embedder_provider=embed_provider,
            embedding_model=embed_model,
            database_type=db_type,
            database_url=database_url,
            database_username=db_config.get('username'),
            database_password=db_config.get('password'),
            database_name=db_config.get('database', 'neo4j'),
            default_namespace=obsidian_config.get('defaultNamespace', 'default'),
            use_custom_ontology=obsidian_config.get('useCustomOntology', False),
            api_keys=obsidian_config.get('apiKeys', {}),
            models_path=str(Path(config_path).parent) if config_path else '',
            notes=[],
            debug=False
        )

    async def _get_graphiti_client(self, database_id: Optional[str] = None) -> Any:
        """Return the Graphiti client for a specific database; falls back to default client
        @purpose: Per-DB routing for search/add operations @results: Cached or newly created Graphiti instance"""
        if not database_id:
            return self.megamem_client

        # Return cached instance if available
        if database_id in self._db_clients:
            return self._db_clients[database_id]

        obsidian_config = self._load_obsidian_config()
        db_config = self._resolve_database_config(database_id, obsidian_config)
        if not db_config:
            raise ValueError(f"Database '{database_id}' not found in configured databases. Use list_databases() to see available options.")

        bridge_cfg = self._create_bridge_config_for_db(db_config, obsidian_config)
        setup_environment_variables(bridge_cfg)
        client = await init_megamem_bridge(bridge_cfg, debug=False)
        self._db_clients[database_id] = client
        logger.info(f"[DB-ROUTING] Initialized Graphiti client for database '{database_id}' ({db_config.get('label')})")
        return client

    def _create_bridge_config(self, obsidian_config: Dict, config_path: str) -> BridgeConfig:
        """Create BridgeConfig from Obsidian config"""
        database_type = obsidian_config.get("databaseType", "neo4j")
        database_configs = obsidian_config.get("databaseConfigs", {})
        current_db_config = database_configs.get(database_type, {})

        # Fallback: find the primary database entry from the new `databases` array
        # (UI writes credentials here; databaseConfigs may be stale/empty)
        _primary_db = next(
            (db for db in obsidian_config.get("databases", [])
             if db.get("type") == database_type
             and db.get("category") != "child-vault"
             and db.get("enabled", True)),
            {}
        )

        # Resolve database URL from plugin settings
        database_url = self._get_database_url_from_obsidian_config(
            obsidian_config, database_type, current_db_config)

        resolved_namespace = self.vault_resolver.get_active_namespace(
            obsidian_config)

        return BridgeConfig(
            llm_provider=obsidian_config.get("llmProvider", "openai"),
            llm_model=obsidian_config.get("llmModel", "gpt-4o"),
            embedder_provider=obsidian_config.get(
                "embedderProvider", "openai"),
            embedding_model=obsidian_config.get(
                "embeddingModel", "text-embedding-3-small"),
            database_type=database_type,
            database_url=database_url,
            database_username=current_db_config.get("username") or _primary_db.get("username") or obsidian_config.get("databaseUsername"),
            database_password=current_db_config.get("password") or _primary_db.get("password") or obsidian_config.get("databasePassword"),
            database_name=current_db_config.get("database") or _primary_db.get("database") or obsidian_config.get("databaseName", "neo4j"),
            default_namespace=resolved_namespace,
            use_custom_ontology=obsidian_config.get(
                "useCustomOntology", False),
            api_keys=obsidian_config.get("apiKeys", {}),
            models_path=str(Path(config_path).parent),
            graph_view_id=obsidian_config.get("graphViewId", "default"),
            notes=[],
            debug=False
        )

    def _get_database_url_from_obsidian_config(self, obsidian_config: Dict, database_type: str, current_db_config: Dict) -> str:
        """Get database URL from Obsidian plugin configuration with proper priority"""
        # 1. Check for direct databaseUrl in plugin settings
        if "databaseUrl" in obsidian_config:
            url = obsidian_config["databaseUrl"]
            logger.info(
                f"[DB-CONFIG] Using direct databaseUrl from plugin: {url}")
            return url

        # 2. Check database-specific configuration (Neo4j uses 'uri', FalkorDB builds from host/port)
        if database_type == "neo4j" and "uri" in current_db_config:
            url = current_db_config["uri"]
            logger.info(
                f"[DB-CONFIG] Using Neo4j URI from databaseConfigs: {url}")
            return url
        elif database_type == "falkordb":
            host = current_db_config.get("host", "localhost")
            port = current_db_config.get("port", 6379)
            url = f"bolt://{host}:{port}"
            logger.info(
                f"[DB-CONFIG] Built FalkorDB URL from databaseConfigs: {url}")
            return url

        # 3. Final fallback
        fallback_url = "bolt://localhost:7687"
        logger.warning(
            f"[DB-CONFIG] No database URL found in config, using fallback: {fallback_url}")
        return fallback_url

    # @vessel-protocol:Baldr governs:launch context:Obsidian auto-launch and process detection for seamless user experience
    # @inter-dependencies: [psutil, subprocess, obsidian config]
    # @purpose: Ensure Obsidian is running before proceeding with MCP operations
    # @result: Users can start MCP processes without manually launching Obsidian first
    # @signed: C.Bjørn
    async def _ensure_obsidian_running(self, obsidian_config: Dict):
        """Ensure Obsidian is running with our vault"""
        # Always try to open the vault - harmless if already open
        vault_name = obsidian_config.get("defaultNamespace", "test-vault")
        if vault_name:
            import webbrowser
            obsidian_url = f"obsidian://open?vault={vault_name}"
            logger.info(f"[INFO] Opening Obsidian vault: {obsidian_url}")
            webbrowser.open(obsidian_url)

        logger.info(
            "[INFO] Obsidian vault opening initiated - MegaMem plugin will connect when ready")

    async def _is_megamem_plugin_connected(self) -> bool:
        """Check if MegaMem plugin is connected via WebSocket"""
        try:
            if not self.file_tools:
                return False

            # Test connection by trying to list vaults
            result = await self.file_tools.list_obsidian_vaults()
            return result.get("success", False) and len(result.get("vaults", [])) > 0
        except Exception as e:
            logger.debug(f"[DEBUG] Plugin connection check failed: {e}")
            return False

    async def _wait_for_plugin_connection(self, timeout: float = 2.0) -> bool:
        """Wait for MegaMem plugin to connect with progress logging"""
        try:
            # Use get_running_loop() for Python 3.13 compatibility
            loop = asyncio.get_running_loop()
            start_time = loop.time()
            check_interval = 5.0  # Log progress every 5 seconds
            last_log_time = start_time

            while (loop.time() - start_time) < timeout:
                if await self._is_megamem_plugin_connected():
                    return True

                # Log progress every 5 seconds
                current_time = loop.time()
                if (current_time - last_log_time) >= check_interval:
                    remaining = timeout - (current_time - start_time)
                    logger.info(
                        f"[INFO] Still waiting for plugin connection (remaining: {remaining:.1f}s)")
                    last_log_time = current_time

                await asyncio.sleep(1.0)  # Check every second

            return False
        except Exception as e:
            logger.warning(
                f"[WARNING] Error waiting for plugin connection: {e}")
            return False
    # @vessel-close:Baldr

# --- Main Entry Point ---


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments. All args are optional — no args = stdio mode (original behavior)."""
    parser = argparse.ArgumentParser(description='MegaMem MCP Server')
    parser.add_argument(
        '--streamable-http', action='store_true',
        help='Run as Streamable HTTP server (MCP spec 2025-03-26). Plugin-spawned process only.'
    )
    parser.add_argument('--port', type=int, default=3838, help='HTTP server port (default: 3838)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='HTTP server host (default: 127.0.0.1)')
    parser.add_argument('--auth-token', type=str, default='', dest='auth_token',
                        help='Bearer auth token (required with --streamable-http)')
    return parser.parse_args()


async def _run_http_server(mcp_server: 'ObsidianMegaMemMCPServer', host: str, port: int, auth_token: str) -> None:
    """Run MCP as Streamable HTTP with Bearer auth. Plugin-spawned process only."""
    try:
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from starlette.routing import Mount
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        import uvicorn
    except ImportError as e:
        logger.critical(f"[HTTP] Missing dependency: {e}. Run: pip install starlette uvicorn mcp>=1.6.0")
        sys.exit(1)

    # stateless=True + json_response=True: each POST is self-contained, returns JSON immediately
    # No persistent SSE stream — compatible with Roo Code and all standard HTTP MCP clients
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server.server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    # @purpose: Build token → profile lookup (admin = full access, scoped = allowlisted)
    # @depends: auth_token (admin), mcp_server.http_token_profiles (from data.json)
    # @results: Single dict used by BearerAuthMiddleware for all auth + profile resolution
    _admin_profile = TokenProfile(id='admin', label='Admin — Full Access', token=auth_token)
    _token_map: Dict[str, TokenProfile] = {auth_token: _admin_profile}
    for _p in mcp_server.http_token_profiles:
        _tp = TokenProfile(
            id=_p.get('id', ''),
            label=_p.get('label', ''),
            token=_p.get('token', ''),
            allowed_tools=_p.get('allowedTools', []),
            allowed_group_ids=_p.get('allowedGroupIds', []),
            allowed_databases=_p.get('allowedDatabases', []),
            allowed_vaults=_p.get('allowedVaults', []),
        )
        if _tp.token:
            _token_map[_tp.token] = _tp
    logger.info(f"[HTTP] Token profiles: 1 admin + {len(mcp_server.http_token_profiles)} scoped")

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        # @purpose: Resolve bearer token → profile; 401 if unknown; set ContextVar for downstream gating
        # @depends: _token_map, current_token_profile ContextVar @results: Profile available to list_tools/call_tool
        async def dispatch(self, request, call_next):
            auth = request.headers.get('Authorization', '')
            if not auth.startswith('Bearer '):
                return Response('Unauthorized', status_code=401)
            bearer_token = auth[7:]
            profile = _token_map.get(bearer_token)
            if profile is None:
                return Response('Unauthorized', status_code=401)
            ctx_token = current_token_profile.set(profile)
            try:
                return await call_next(request)
            finally:
                current_token_profile.reset(ctx_token)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            logger.info(f"[HTTP] MegaMem MCP server ready — http://{host}:{port}/mcp")
            yield

    starlette_app = Starlette(
        lifespan=lifespan,
        routes=[Mount('/mcp', app=session_manager.handle_request)],
        middleware=[Middleware(BearerAuthMiddleware)],
    )

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level='info')
    server = uvicorn.Server(config)
    await server.serve()


async def _main_stdio() -> None:
    """Run MCP server over stdio — Claude Desktop / original behavior.
    Transport opens FIRST so tools/list responds immediately.
    initialize() runs as a background task after the transport is ready.
    """
    try:
        mcp_server = ObsidianMegaMemMCPServer()
        async with stdio_server() as (read_stream, write_stream):
            # Start initialize() in the background AFTER transport is open.
            # Claude Desktop can now handle tools/list instantly while Neo4j/CLI
            # init proceeds asynchronously. ready_event + initialization_complete
            # gate any tool calls that need Graphiti.
            asyncio.create_task(mcp_server.initialize())
            await mcp_server.server.run(
                read_stream,
                write_stream,
                mcp_server.server.create_initialization_options()
            )
    except Exception as e:
        logger.critical(f"Failed to start MCP server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    args = parse_args()

    if args.streamable_http:
        if not args.auth_token:
            print('[ERROR] --auth-token is required when using --streamable-http', file=sys.stderr)
            sys.exit(1)

        async def _run_http():
            mcp_server = ObsidianMegaMemMCPServer()
            await mcp_server.initialize()
            await _run_http_server(mcp_server, args.host, args.port, args.auth_token)

        asyncio.run(_run_http())
    else:
        asyncio.run(_main_stdio())
