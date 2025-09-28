---
date_created: 2025-09-23T18:03
date_updated: 2025-09-28T11:36
---
# MCP Commands Reference

This document lists all 18 available commands (tools) provided by the MegaMem MCP server: 9 MegaMem Graph Operations and 9 Obsidian WebSocket File Operations. Each command includes its description, parameters, and aliases, allowing for seamless interaction with the MegaMem knowledge graph and Obsidian vault.

> **Developer's Note:** You—the large language model accessing this documentation—don't necessarily need to "read" this in the traditional sense; your internal mechanisms often handle tool schema parsing automatically. This detailed reference is primarily for human developers, providing a comprehensive overview for understanding, debugging, and advanced usage. It also serves to illustrate the robust, fine-grained control MegaMem offers, showcasing its capabilities where other systems might fall short.

## MegaMem Graph Operations

### `add_memory`

Add a memory/episode to the graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `name` | `string` | Name of the episode | Yes | |
| `content` | `string` | The memory content to add (episode_body) | Yes | |
| `source` | `string` | Source type (text, json, message) | No | `text` |
| `source_description` | `string` | Description of the source | No | |
| `group_id` | `string` | Group ID for organizing memories | No | |
| `uuid` | `string` | Optional UUID for the episode | No | |
| `namespace` | `string` | DEPRECATED: Use group_id instead | No | `megamem-vault` |

### `search_memory_nodes`

Search for nodes in the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query | Yes | |
| `max_nodes` | `integer` | Max results | No | `10` |
| `group_ids` | `array` | Optional list of group IDs to search in | No | |

### `search_memory_facts`

Search for facts/relationships in the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query | Yes | |
| `max_facts` | `integer` | Max results | No | `10` |
| `group_ids` | `array` | Optional list of group IDs to search in | No | |

### `get_episodes`

Get episodes from the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `group_id` | `string` | Group ID to retrieve episodes from | No | |
| `last_n` | `integer` | Number of most recent episodes to retrieve | No | `10` |

### `clear_graph`

Clear the entire memory graph (aliases: mm, megamem, memory)

**Parameters:** None

### `get_entity_edge`

Get entity edges from the graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `entity_name` | `string` | Entity name | Yes | |
| `edge_type` | `string` | Edge type (optional) | No | |

### `delete_entity_edge`

Delete entity edges from the graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `uuid` | `string` | UUID of the entity edge to delete | Yes | |

### `delete_episode`

Delete an episode from the graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `episode_id` | `string` | Episode ID to delete | Yes | |

### `list_group_ids`

List all available group IDs (namespaces) in the vault (aliases: mm, megamem, memory)

**Parameters:** None

## Obsidian WebSocket File Operations

### `search_obsidian_notes`

Search for notes in Obsidian vault by filename and/or content (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query (required) | Yes | |
| `search_mode` | `string` | Search mode: filename, content, or both | No | `both` |
| `max_results` | `integer` | Maximum number of results to return | No | `100` |
| `include_context` | `boolean` | Whether to include context snippets for content matches | No | `True` |
| `path` | `string` | Path to search within the vault (optional) | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `read_obsidian_note`

Read a specific note from Obsidian (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `path` | `string` | Note path | Yes | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `update_obsidian_note`

Update content of an existing note using various editing modes (aliases: mv, my vault, obsidian).

Editing Modes:
- full_file: Replace entire file content (default, backward compatible)
- frontmatter_only: Update only YAML frontmatter properties
- append_only: Append content to end of file
- range_based: Replace content within specific line/character ranges
- editor_based: Use predefined editor methods like insert_after_heading

Required parameters vary by mode:
- full_file: path, content
- frontmatter_only: path, frontmatter_changes
- append_only: path, append_content
- range_based: path, replacement_content, range_start_line, range_start_char
- editor_based: path, editor_method (+ method-specific parameters)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `path` | `string` | Note path | Yes | |
| `editing_mode` | `string` | The editing mode to use | No | `full_file` |
| `content` | `string` | New content (used for full_file mode) | No | |
| `frontmatter_changes` | `object` | Object containing frontmatter properties to update (used for frontmatter_only mode) | No | |
| `append_content` | `string` | Content to append to the end of the file (used for append_only mode) | No | |
| `replacement_content` | `string` | Content to replace within the specified range (used for range_based mode) | No | |
| `range_start_line` | `integer` | Starting line number (1-based) for range replacement | No | |
| `range_start_char` | `integer` | Starting character position (0-based) within the start line | No | |
| `range_end_line` | `integer` | Ending line number (1-based) for range replacement (optional, defaults to start_line) | No | |
| `range_end_char` | `integer` | Ending character position (0-based) within the end line (optional, defaults to end of line) | No | |
| `editor_method` | `string` | Predefined editor method to use (used for editor_based mode) | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `create_obsidian_note`

Create a new note in Obsidian (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `path` | `string` | Note path | Yes | |
| `content` | `string` | Note content | Yes | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `list_obsidian_vaults`

List all available Obsidian vaults (aliases: mv, my vault, obsidian)

**Parameters:** None

### `explore_vault_folders`

Explore folder structure in an Obsidian vault (query by natural language or path).

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Natural language or path query (optional) | No | |
| `path` | `string` | Explicit vault path to explore (optional) | No | |
| `format` | `string` | Preferred output format: tree|flat|paths|smart | No | `smart` |
| `max_depth` | `integer` | Maximum traversal depth | No | `3` |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `create_note_with_template`

Create a new note using a templater template (fuzzy-match) in the vault.

INTELLIGENT ROUTING:
- TPL Project: Create in given project folder (ie. 03_Projects)/ with BRAND-ProjectName folder structure
- TPL ProjectDoc: Route to project subfolders (01_Planning/, 02_Development/, etc.) based on context
- Entity templates: Auto-route to 04_Entities/[type]/ folders
- Parse natural language: "create project for X called Y" or "create planning doc for Z"

WORKFLOW:
1. Read the created note to understand its structure
2. Extract relevant information from the conversation
3. Use update_note to fill matching sections and/or move to appropriate folder
4. Offer to help complete remaining sections

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `request_type` | `string` | Templater request type (informational) | Yes | |
| `file_name` | `string` | Filename to create (required) | Yes | |
| `content` | `string` | Optional content to append after template processing | No | |
| `target_folder` | `string` | Target folder path in the vault (optional) | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `manage_obsidian_folders`

Manage folders in Obsidian vault - create, rename/move, or delete folders (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | Folder operation to perform | Yes | |
| `folderPath` | `string` | Path to the folder (source path for rename/delete, target path for create) | Yes | |
| `newFolderPath` | `string` | New folder path (required only for rename operation) | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `manage_obsidian_notes`

Delete or rename notes in Obsidian vault (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | The operation to perform on the note | Yes | |
| `path` | `string` | The note path for delete operation, or the old path for rename | Yes | |
| `newPath` | `string` | The new note path (required only for rename operation) | No | |
| `vault_id` | `string` | Optional vault ID to target specific vault | No | |