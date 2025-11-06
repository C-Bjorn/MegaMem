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
from pathlib import Path
from typing import Any, Dict, List, Optional
import socket
import subprocess
import psutil
import aiohttp
from datetime import datetime, timezone

if sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

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
import mcp.types as types

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
    "manage_obsidian_notes"
}

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
        
        self.initialization_complete = False
        self.resource_loading_task = None
        self.ready_event = asyncio.Event()
        
        self.episode_queues: Dict[str, asyncio.Queue] = {}
        self.queue_workers: Dict[str, bool] = {}

        # Register all tool handlers
        self._register_tool_handlers()

    def _register_tool_handlers(self):
        """Register all MCP tool handlers"""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """Return all 18 tools - 9 Graphiti + 9 Obsidian"""
            tools = []

            # Add 9 Graphiti tools
            tools.extend(self._get_megamem_tool_definitions())

            # Add 9 Obsidian tools
            tools.extend(self._get_obsidian_tool_definitions())

            logger.info(
                f"Returning {len(tools)} total tools ({len(self._get_megamem_tool_definitions())} MegaMem + {len(self._get_obsidian_tool_definitions())} Obsidian)")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
            """Route tool calls to appropriate handlers"""
            logger.info(f"Calling tool: {name}")
            arguments = arguments or {}

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
            """Return health check resource"""
            return [types.Resource(
                uri="megamem://status",
                name="MegaMem Server Status",
                description="Health check for Graphiti and Obsidian connections"
            )]

        @self.server.read_resource()
        async def read_resource(uri: str) -> str:
            """Read health check resource"""
            if uri == "megamem://status":
                status = {
                    "graphiti": "ok" if self.megamem_client and self.megamem_client != "RPC_MODE" else "disconnected",
                    "obsidian": "ok" if self.file_tools else "disconnected",
                    "database": self.bridge_config.database_type if self.bridge_config else "unknown"
                }
                
                return json.dumps(status, indent=2)
            
            raise ValueError(f"Unknown resource URI: {uri}")

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
                        "namespace": {"type": "string", "description": "DEPRECATED: Use group_id instead", "default": "megamem-vault"}
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
                        "entity_types": {"type": "array", "items": {"type": "string"}, "description": "Filter by entity types (e.g., ['Person', 'Company'])"}
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
                        "center_node_uuid": {"type": "string", "description": "UUID of node to center search around (proximity search)"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="get_episodes",
                description="Get episodes from the memory graph (aliases: mm, megamem, memory)",
                inputSchema={
                     "type": "object",
                     "properties": {
                         "group_id": {"type": "string", "description": "Group ID to retrieve episodes from"},
                         "last_n": {"type": "integer", "description": "Number of most recent episodes to retrieve", "default": 10}
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
                        "edge_type": {"type": "string", "description": "Edge type (optional)"}
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
                        "uuid": {"type": "string", "description": "UUID of the entity edge to delete"}
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
                        "episode_id": {"type": "string", "description": "Episode ID to delete"}
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
                        "source_description": {"type": "string", "description": "Source description", "default": "Conversation memory from MCP"}
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
                            "type": "integer",
                            "default": 100,
                            "description": "Maximum number of results to return"
                        },
                        "include_context": {
                            "type": "boolean",
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
                            "type": "boolean",
                            "default": False,
                            "description": "Include line-by-line mapping and section detection for precise editing (increases response size ~2x)"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="update_obsidian_note",
                description="""Update content of an existing note using various editing modes (aliases: mv, my vault, obsidian).

Editing Modes:
- full_file: Replace entire file content (default)
- frontmatter_only: Update only YAML frontmatter properties
- append_only: Append content to end of file
- range_based: Replace content within specific line ranges
- editor_based: Use predefined editor methods

Required parameters vary by mode:
- full_file: path, content
- frontmatter_only: path, frontmatter_changes
- append_only: path, append_content
- range_based: path, replacement_content, range_start_line, range_start_char
- editor_based: path, editor_method (plus method-specific parameters)

MANDATORY WORKFLOW FOR range_based MODE:
Before using range_based editing, you MUST follow this exact sequence:

1. Call read_obsidian_note WITH include_line_map=true to get line numbers
2. Use the returned metadata.lineMap to identify exact line positions
3. Verify the target content matches your intent
4. Execute the range_based edit with verified line numbers

The include_line_map parameter returns:
- metadata.lineMap: {"1": "line content", "2": "line content", ...}
- metadata.sections: [{name: "frontmatter", startLine: 1, endLine: 5}, {name: "body", startLine: 6, endLine: 100}]
- metadata.totalLines: total line count

Critical reminders:
- NEVER attempt range_based editing without first reading with include_line_map=true
- Use lineMap to verify exact content at each line number
- Blank lines and frontmatter are included in line numbers
- The lineMap eliminates manual counting errors

Example: To edit line 38, first call read_obsidian_note with include_line_map=true, then check metadata.lineMap["38"] to verify content, then specify range_start_line=38.""",
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
                            "type": "object",
                            "description": "Object containing frontmatter properties to update (used for frontmatter_only mode)"
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
                            "type": "integer",
                            "description": "Starting line number (1-based) for range replacement"
                        },
                        "range_start_char": {
                            "type": "integer",
                            "description": "Starting character position (0-based) within the start line"
                        },
                        "range_end_line": {
                            "type": "integer",
                            "description": "Ending line number (1-based) for range replacement (optional, defaults to start_line)"
                        },
                        "range_end_char": {
                            "type": "integer",
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
                            "type": "integer",
                            "description": "Maximum traversal depth",
                            "default": 3
                        },
                        "vault_id": {
                            "type": "string",
                            "description": "Vault ID (optional)"
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="create_note_with_template",
                description="""Create a new note using a templater template (fuzzy-match) in the vault.

INTELLIGENT ROUTING:
- TPL Project: Create in given project folder (ie. 03_Projects)/ with BRAND-ProjectName folder structure
- TPL ProjectDoc: Route to project subfolders (01_Planning/, 02_Development/, etc.) based on context
- Entity templates: Auto-route to 04_Entities/[type]/ folders
- Parse natural language: "create project for X called Y" or "create planning doc for Z"

WORKFLOW:
1. Read the created note to understand its structure
2. Extract relevant information from the conversation
3. Use update_note to fill matching sections and/or move to appropriate folder
4. Offer to help complete remaining sections""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "request_type": {"type": "string", "description": "Templater request type (informational)"},
                        "file_name": {"type": "string", "description": "Filename to create (required)"},
                        "content": {"type": "string", "description": "Optional content to append after template processing"},
                        "target_folder": {"type": "string", "description": "Target folder path in the vault (optional)"},
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["request_type", "file_name"]
                }
            ),
            Tool(
                name="manage_obsidian_folders",
                description="Manage folders in Obsidian vault - create, rename/move, or delete folders (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "rename", "delete"],
                            "description": "Folder operation to perform"
                        },
                        "folderPath": {
                            "type": "string",
                            "description": "Path to the folder (source path for rename/delete, target path for create)"
                        },
                        "newFolderPath": {
                            "type": "string",
                            "description": "New folder path (required only for rename operation)"
                        },
                        "vault_id": {"type": "string", "description": "Vault ID (optional)"}
                    },
                    "required": ["operation", "folderPath"]
                }
            ),
            Tool(
                name="manage_obsidian_notes",
                description="Delete or rename notes in Obsidian vault (aliases: mv, my vault, obsidian)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["delete", "rename"],
                            "description": "The operation to perform on the note"
                        },
                        "path": {
                            "type": "string",
                            "description": "The note path for delete operation, or the old path for rename"
                        },
                        "newPath": {
                            "type": "string",
                            "description": "The new note path (required only for rename operation)"
                        },
                        "vault_id": {
                            "type": "string",
                            "description": "Optional vault ID to target specific vault"
                        }
                    },
                    "required": ["operation", "path"]
                }
            )
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
                    await self.megamem_client.add_episode(**episode_kwargs)
                
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

            elif name == "search_memory_nodes":
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

                results = await self.megamem_client._search(
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
                    "results": formatted_nodes
                }))]

            elif name == "search_memory_facts":
                group_ids = arguments.get('group_ids') or [
                    self.bridge_config.default_namespace]
                max_facts = arguments.get("max_facts", 10)
                center_node_uuid = arguments.get("center_node_uuid")

                if center_node_uuid:
                    search_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
                else:
                    search_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                search_config.limit = max_facts

                results = await self.megamem_client._search(
                    query=arguments["query"],
                    config=search_config,
                    group_ids=group_ids,
                    center_node_uuid=center_node_uuid
                )

                formatted_facts = [self._format_fact_result(
                    edge) for edge in results.edges]
                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "facts": formatted_facts
                }))]

            elif name == "get_episodes":
                # Get group_id and last_n from arguments

                last_n = arguments.get("last_n", 10)

                # Call retrieve_episodes
                episodes = await self.megamem_client.retrieve_episodes(
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
                # Search for episodes/nodes that mention the entity and return their edges
                try:
                    entity_name = arguments.get("entity_name")
                    if not entity_name:
                        return [types.TextContent(type="text", text=json.dumps({
                            "success": False,
                            "error": "entity_name is required"
                        }))]
                    edge_type = arguments.get("edge_type")

                    # Search for nodes related to the entity
                    search_results = await self.megamem_client.search(entity_name)

                    if not search_results:
                        return [types.TextContent(type="text", text=json.dumps({
                            "success": True,
                            "entity": entity_name,
                            "edges": [],
                            "message": f"No edges found for entity: {entity_name}"
                        }))]

                    # Extract edge information from search results
                    edges = []
                    for result in search_results:
                        # Get the values
                        valid_at_val = getattr(result, 'valid_at', '')
                        invalid_at_val = getattr(result, 'invalid_at', '')

                        # Create the dictionary, converting datetimes to strings
                        edge_info = {
                            "uuid": str(result.uuid),
                            "fact": getattr(result, 'fact', ''),
                            "source_node_uuid": getattr(result, 'source_node_uuid', ''),
                            "target_node_uuid": getattr(result, 'target_node_uuid', ''),
                            "valid_at": valid_at_val.isoformat() if isinstance(valid_at_val, datetime) else valid_at_val,
                            "invalid_at": invalid_at_val.isoformat() if isinstance(invalid_at_val, datetime) else invalid_at_val
                        }

                        # Filter by edge type if specified
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

                    entity_edge = await EntityEdge.get_by_uuid(self.megamem_client.driver, uuid)
                    await entity_edge.delete(self.megamem_client.driver)

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
                    await self.megamem_client.remove_episode(episode_id)

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
                
                # Read config for custom ontology
                config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
                if not config_path:
                    return [types.TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": "OBSIDIAN_CONFIG_PATH not set"
                    }))]
                
                with open(config_path, 'r') as f:
                    obsidian_config = json.load(f)
                
                entity_types = {}
                if obsidian_config.get('useCustomOntology'):
                    entity_types = get_entity_types_with_config(obsidian_config)
                
                # Add episode with message source type
                episode_kwargs = {
                    'name': name_param,
                    'episode_body': episode_body,
                    'source': EpisodeType.message,
                    'source_description': source_description,
                    'group_id': group_id,
                    'reference_time': datetime.now(timezone.utc),
                    'entity_types': entity_types
                }
                
                result = await self.megamem_client.add_episode(**episode_kwargs)
                
                return [types.TextContent(type="text", text=json.dumps({
                    "success": True,
                    "episode_id": str(result.episode.uuid),
                    "message": "Conversation memory added successfully",
                    "message_count": len(conversation)
                }))]

            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Unknown MegaMem tool: {name}"
                }))]

        except Exception as e:
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
                # Map 'operation' parameter to 'editing_mode' with value mapping for backward compatibility
                if k == "operation":
                    normalized_key = "editing_mode"
                    # Map Claude's operation values to valid editing_mode values
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

            # Initialize WebSocket configuration
            self.ws_port = obsidian_config.get("wsPort", 41484)
            ws_config = {
                "port": self.ws_port,
                "auth_token": obsidian_config.get("wsAuthToken", ""),
            }
            logger.info(
                f"[CONFIG] WebSocket port: {ws_config['port']} (from OBSIDIAN_CONFIG_PATH)")

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
                "[INFO] All 18 tools available: 9 Graphiti + 9 Obsidian")

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
            
            megamem_client = await init_megamem_bridge(bridge_config, debug=True)
            if not megamem_client:
                raise ValueError("MegaMem client initialization failed (returned None).")
            self.megamem_client = megamem_client

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
            raise

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
            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Invalid operation '{operation}'. Must be one of: create, rename, delete"
                }))]

            return [types.TextContent(type="text", text=json.dumps(result))]

        except Exception as e:
            logger.error(f"Error in _handle_manage_obsidian_folders: {str(e)}")
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Failed to manage folder: {str(e)}"
            }))]

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
            else:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Invalid operation '{operation}'. Must be one of: delete, rename"
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

    def _create_bridge_config(self, obsidian_config: Dict, config_path: str) -> BridgeConfig:
        """Create BridgeConfig from Obsidian config"""
        database_type = obsidian_config.get("databaseType", "neo4j")
        database_configs = obsidian_config.get("databaseConfigs", {})
        current_db_config = database_configs.get(database_type, {})

        # Resolve database URL from plugin settings
        database_url = self._get_database_url_from_obsidian_config(
            obsidian_config, database_type, current_db_config)

        # Inside _create_bridge_config, before the return statement:
        resolved_namespace = self.vault_resolver.get_active_namespace(
            obsidian_config)

        return BridgeConfig(
            llm_provider=obsidian_config.get("llmProvider", "openai"),
            llm_model=obsidian_config.get("llmModel", "gpt-4o"),
            embedder_provider=obsidian_config.get(
                "embedderProvider", "openai"),
            embedding_model=obsidian_config.get(
                "embeddingModel", "text-embedding-3-small"),
            # Cross-Encoder configuration (ensure Graphiti gets an instantiated cross-encoder instead of defaulting)
            cross_encoder_client=obsidian_config.get(
                "crossEncoderClient", "none"),
            cross_encoder_model=obsidian_config.get("crossEncoderModel"),
            database_type=database_type,
            database_url=database_url,
            database_username=current_db_config.get(
                "username") or obsidian_config.get("databaseUsername"),
            database_password=current_db_config.get(
                "password") or obsidian_config.get("databasePassword"),
            database_name=obsidian_config.get("databaseName", "neo4j"),
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

# --- Main Entry Point ---


async def main():
    """Main entry point for the complete MCP server with 18 tools"""
    try:
        # Create and initialize the server
        mcp_server = ObsidianMegaMemMCPServer()
        await mcp_server.initialize()

        # Run the MCP server using stdio transport
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.server.run(
                read_stream,
                write_stream,
                mcp_server.server.create_initialization_options()
            )
    except Exception as e:
        logger.critical(f"Failed to start MCP server: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
