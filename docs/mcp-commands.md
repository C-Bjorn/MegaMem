---
date_created: 2025-09-23T18:03
date_updated: 2026-04-01T00:00
---
# MCP Commands Reference

This document lists all 22 available commands (tools) provided by the MegaMem MCP server: 11 MegaMem Graph Operations and 11 Obsidian File Operations (via CLI). Each command includes its description, parameters, and aliases, allowing for seamless interaction with the MegaMem knowledge graph and Obsidian vault.

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
| `database_id` | `string` | Optional: target a specific named database (id or label from Databases settings) | No | |

### `add_conversation_memory`

Stores conversations in Graphiti memory using the message episode type. Client (Claude) provides pre-summarized assistant responses. Messages are stored in format: `[timestamp] role: content` (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `name` | `string` | Name for the conversation episode | No | Auto-generates `Conversation_YYYYMMDD_HHMMSS` |
| `conversation` | `array` | Array of message objects (see below) | Yes | |
| `group_id` | `string` | Group ID for organizing memories | No | |
| `source_description` | `string` | Description of conversation source | No | `Conversation memory from MCP` |

**Message Object Structure:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `role` | `string` | Message role: "user" or "assistant" | Yes | |
| `content` | `string` | Full message for user; concise summary for assistant | Yes | |
| `timestamp` | `string` | ISO 8601 timestamp | No | Current UTC time |

**Example:**

```json
{
  "name": "Product Discussion 2025-10-27",
  "conversation": [
    {
      "role": "user",
      "content": "What features should we prioritize?",
      "timestamp": "2025-10-27T14:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Recommended authentication improvements based on user feedback",
      "timestamp": "2025-10-27T14:30:15Z"
    }
  ]
}
```

### `search_memory_nodes`

Search for nodes in the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query | Yes | |
| `max_nodes` | `integer` | Max results | No | `10` |
| `group_ids` | `array` | Optional list of group IDs to search in | No | |
| `node_labels` | `array` | Filter results to nodes with specific label types (e.g. `["Person", "Organization"]`) | No | |
| `property_filters` | `object` | Filter by specific node/edge properties (e.g. `{"status": "active"}`) | No | |
| `database_id` | `string` | Optional: target a specific named database (id or label from Databases settings) | No | |

### `search_memory_facts`

Search for facts/relationships in the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query | Yes | |
| `max_facts` | `integer` | Max results | No | `10` |
| `group_ids` | `array` | Optional list of group IDs to search in | No | |
| `node_labels` | `array` | Filter by node label types (e.g. `["Person", "Organization"]`) | No | |
| `property_filters` | `object` | Filter by specific node/edge properties (e.g. `{"group_id": "Journal"}`) | No | |
| `database_id` | `string` | Optional: target a specific named database (id or label from Databases settings) | No | |

### `get_episodes`

Get episodes from the memory graph (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `group_id` | `string` | Group ID to retrieve episodes from | No | |
| `last_n` | `integer` | Number of most recent episodes to retrieve | No | `10` |

> **Episode back-references** *(v1.5.5+)*: Episodes created by syncing Obsidian notes include source attribution in the `content` field: `mm_note_path` (vault-relative path), `mm_vault_id` (vault name), `mm_obsidian_url` (deep link for one-click opening), and `mm_contributor` (who synced it). Use `get_episodes()` → parse `mm_note_path` + `mm_vault_id` → call `read_obsidian_note(path, vault_id)` to navigate from graph knowledge back to the source note.

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

### `list_databases`

List all configured database targets. Use this to discover which databases are available before querying with `database_id`. (aliases: mm, megamem, memory)

**Parameters:** None

**Returns:** Array of `{ id, label, category, type, connection_info_public }` — one entry per configured database in plugin settings.

> **Tip for AI assistants:** Call `list_databases` first when the user refers to a specific vault, project, or database by name. Use the returned `id` to route subsequent queries via the `database_id` parameter.

### `list_group_ids`

List all available group IDs (namespaces) in the vault (aliases: mm, megamem, memory)

**Parameters:** None

### `manage_sagas`

Manage sagas in the memory graph — list all sagas or summarize a specific saga. (aliases: mm, megamem, memory)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | `list` or `summarize` | Yes | |
| `saga_name` | `string` | Name of the saga to summarize (required for `summarize`) | No | |
| `group_id` | `string` | Namespace to scope the query | No | server default |
| `database_id` | `string` | Target a specific named database | No | |

**Operations:**

- **`list`** — Returns all sagas in the namespace. Each entry includes `uuid`, `name`, `group_id`, `summary`, `episode_count`, and `last_summarized_at`. No `saga_name` needed.
- **`summarize`** — Incrementally summarizes a saga using only new episodes since the last summary. Returns the updated `summary`, `episode_count`, and `last_summarized_at`.

> **Tip:** Use `list` first to discover saga names, then call `summarize` by name. Sagas are created automatically when notes are synced with `saga_name` set in frontmatter.

## Obsidian File Operations (via Obsidian CLI)

> **ℹ️ Architecture Note:** These 10 file tools are powered by stateless `obsidian <command>` subprocess calls to the **Obsidian CLI** (v1.12.4+), replacing the previous WebSocket layer. No persistent connection or heartbeat is required. Multi-vault targeting is handled via the `vault_id` parameter. Requires Obsidian 1.12.4+ installer — see [Quick Start Guide](quick-start.md) for setup.
>
> **Non-markdown files supported:** The `_auto_md` fix means `.md` auto-append is skipped when a path already has a recognized extension (`.pdf`, `.png`, `.csv`, `.base`, etc.). All file tools work with non-markdown vault files.

### `search_obsidian_notes`

Search for notes in Obsidian vault by filename and/or content (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `query` | `string` | Search query. Required for filename/content search. Optional when `property_filter` is set — acts as a case-insensitive filename/path substring filter. | No | |
| `search_mode` | `string` | Search mode: filename, content, or both. Ignored when `property_filter` is set. | No | `both` |
| `max_results` | `integer` | Maximum number of results to return | No | `100` |
| `include_context` | `boolean` | Whether to include context snippets for content matches | No | `True` |
| `path` | `string` | Scopes results to this folder path — only notes within this path are returned | No | |
| `property_filter` | `object` | Filter by frontmatter properties. All key/value pairs must match (AND logic). Array frontmatter values are checked with `includes()`. Example: `{"status": "active", "type": "task"}`. Uses Obsidian eval — requires Obsidian running. | No | |
| `mtime_after` | `string` | Return only notes modified after this date (ISO format, e.g. `2026-03-20`). Compares against `file.mtime`. Uses Obsidian eval — requires Obsidian running. | No | |
| `mtime_before` | `string` | Return only notes modified before this date (ISO format, e.g. `2026-04-01`). Compares against `file.mtime`. Uses Obsidian eval — requires Obsidian running. | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

**Filename search behavior (`search_mode=filename`):** Splits query into words; a file matches if **all words** appear anywhere in the basename or full path (order-independent, case-insensitive). Handles multi-word queries, dotted note names (e.g. `Day45.01`), and missing punctuation gracefully. Results return `matchType: "filename"`.

**Property/mtime filter behavior:** When `property_filter`, `mtime_after`, or `mtime_before` is set, dispatches to an eval-based JS search (`_search_by_property`) bypassing `search:context`. Notes without frontmatter still match when only mtime filters are used. `property_filter` and `mtime_*` params can be combined freely. Returns `matchType: "property"`.

### `read_obsidian_note`

Read a specific note from Obsidian (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `path`     | `string` | File path in the vault. `.md` is auto-appended only when the path has no extension; non-.md files (`.pdf`, `.png`, `.csv`, `.base`) are passed through as-is. | Yes | |
| `include_line_map` | `boolean` | Include line-by-line mapping and section detection for precise editing (increases response size ~2x) | No | `false` |
| `vault_id` | `string` | Vault ID (optional) | No | |

### `update_obsidian_note`

Update content of an existing note using various editing modes (aliases: mv, my vault, obsidian).

Editing Modes:
- full_file: Replace entire file content (default, backward compatible)
- frontmatter_only: Update only YAML frontmatter properties. **Empty markdown links `[text]()` are automatically skipped and never written.** The template `links:` block sequence is cleaned of placeholder entries on first write.
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
| `frontmatter_changes` | `object` | Object containing frontmatter properties to update (used for frontmatter_only mode). **WARNING:** Do NOT pass array values (e.g. `tags`) via `frontmatter_changes` — the YAML serializer will drop the closing `---` fence, corrupting the file. For any update that includes array fields, use `full_file` mode instead. | No | |
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
| `include_files` | `boolean` | Include files alongside folders in the response | No | `false` |
| `extension_filter` | `array` | Filter returned files by extension (e.g. `["md", "canvas"]`). Only used when `include_files=true` | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

**When `include_files=true`:** Response includes a `files` array with objects containing `{name, path, basename, extension, size, mtime}` and a `totalFiles` count alongside the standard folder tree.

### `create_note_with_template`

Create a new note using a templater template (fuzzy-match) in the vault.

INTELLIGENT ROUTING:
- TPL Project: Create in given project folder (ie. 03_Projects)/ with BRAND-ProjectName folder structure
- TPL ProjectDoc: Route to project subfolders (01_Planning/, 02_Development/, etc.) based on context
- Entity templates: Auto-route to 04_Entities/[type]/ folders
- Parse natural language: "create project for X called Y" or "create planning doc for Z"

SERVER-SIDE FOLDER RESOLUTION (when `target_folder` is omitted):
1. **Templater mapping** — checks `folder_templates` in Templater plugin settings; fuzzy-matches template basename
2. **Periodic Notes** — matches template name against Periodic Notes config; calculates date-expanded folder path
3. **MegaMem inboxFolder** — falls back to `mcpTools.defaults.inboxFolder` from plugin settings (e.g. `01_Inbox`)
4. **Vault root** — final fallback if no mapping and no inboxFolder configured

DUAL-FOLDER TEMPLATE DISCOVERY:
- Template list is built from both `templates_folder` (personal) and `company_templates_folder` (company) in Templater settings
- Company templates listed first; same-name templates deduped (company wins)
- If `company_templates_folder` is not configured, behaves identically to previous behavior

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

Manage folders in Obsidian vault - create, rename/move, delete, or clone folders (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | Folder operation: `create`, `rename`, `delete`, `clone` | Yes | |
| `folderPath` | `string` | Path to the folder (source path for rename/delete/clone, target path for create) | Yes | |
| `newFolderPath` | `string` | New folder path (required for rename and clone operations) | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

**Operations:**
- `create` — create a new folder
- `rename` — rename or move to a new path (updates all internal links)
- `delete` — delete folder and all contents
- `clone` — duplicate the entire folder tree to a new path using `vault.copy()`. Returns `filesCopied` count.

### `manage_obsidian_notes`

Delete, rename/move, or copy notes in Obsidian vault (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | The operation to perform: `rename`, `delete`, `copy` | Yes | |
| `path` | `string` | The note path. `.md` is auto-appended if missing | Yes | |
| `newPath` | `string` | Destination path — required for `rename` and `copy`. Cross-folder moves auto-detected for rename. | No | |
| `vault_id` | `string` | Optional vault ID to target specific vault | No | |

**Operations:**
- `rename` — rename or move note; updates internal wikilinks
- `delete` — move to trash
- `copy` — duplicate note to `newPath` using `vault.copy()`. Does NOT update wikilinks (source links unchanged).

### `sync_obsidian_note`

Sync a specific note to the MegaMem/Graphiti knowledge graph by path. Opens the note and triggers the registered sync command. Use after updating a note to queue it for graph sync. Requires Obsidian running with MegaMem plugin active. Sync completes asynchronously after this tool returns. (aliases: mv, my vault, obsidian)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `path` | `string` | Vault-relative path to the note (e.g. `'My Notes/SomeNote.md'`). Do NOT use absolute system paths or prefix with the vault folder name. | Yes | |
| `vault_id` | `string` | Vault ID (optional) | No | |

---

### `manage_obsidian_base`

Manage Obsidian Bases `.base` files — list all bases, inspect views, run queries, or create items (aliases: mv, my vault, obsidian, bases)

**Parameters:**

| Name | Type | Description | Required | Default |
|---|---|---|---|---|
| `operation` | `string` | Operation to perform: `list`, `views`, `query`, `create` | Yes | |
| `file` | `string` | Base filename (without extension). Used by: `views`, `query`, `create`. | No | |
| `path` | `string` | Full vault-relative path to the `.base` file (alternative to `file`). Used by: `views`, `query`, `create`. | No | |
| `view` | `string` | View name within the base. Used by: `query` (optional), `create` (optional). | No | |
| `format` | `string` | Output format for query results: `json` (default), `csv`, `tsv`, `md`, `paths`. Used by: `query`. | No | `json` |
| `limit` | `integer` | Max number of results to return. Applied post-fetch to the parsed JSON array. Used by: `query`. | No | |
| `name` | `string` | Name/title for the new item. Used by: `create`. | No | |
| `content` | `string` | Initial content for the new item. Used by: `create`. | No | |
| `vault_id` | `string` | Vault ID (optional) | No | |

**Operations:**
- `list` — list all `.base` files in the vault
- `views` — return the named views defined in a `.base` file
- `query` — execute a query against a `.base` file's data and return results
- `create` — create a new item/row in an existing `.base` file

---

## MCP Resources _(v1.6.5)_

MegaMem exposes three read-only MCP resources. Access them with `read_resource` in any MCP-compatible client.

### `megamem://instructions`

Concise usage guide (22 tools, shorthands, key behaviors). Loaded automatically by Claude as the server's system prompt context.

### `megamem://instructions/reference`

Full parameter reference for all 22 tools. Load on demand when you need complete parameter details for a specific tool.

### `megamem://status`

Live server status snapshot: connected vaults + database IDs, Graphiti health, embedder health, Python bridge version, MCP server version, and the last 40 lines of the consolidated log.