# MegaMem — Obsidian × Knowledge Graph × MCP

> **Temporal memory for AI assistants, powered by your Private vault**

MegaMem is an Obsidian plugin that syncs your notes into a **temporal knowledge graph** (powered by [Graphiti](https://github.com/getzep/graphiti)) and exposes it to AI assistants through the **Model Context Protocol (MCP)**. Claude, and any other MCP-compatible client, can read, search, and write to your vault — and remember things across conversations.

[![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)](https://github.com/C-Bjorn/megamem-mcp/releases)
[![Obsidian](https://img.shields.io/badge/Obsidian-1.12.4+-blueviolet.svg)](https://obsidian.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)

---

## 🌟 Key Features

### 🧠 Temporal Knowledge Graph

Sync your Obsidian notes to a graph database. Entities become nodes, relationships are extracted by AI, and every fact is timestamped so the graph evolves as your knowledge does — without losing history.

### 🔍 Auto Schema Discovery

The plugin scans your vault's frontmatter and automatically infers entity types, property types, and relationships. No manual schema definition required. Write your notes, the schema emerges.

### 🌐 Multi-Database & Multi-Vault _(new in v1.5.0)_

Configure multiple named graph databases simultaneously — each with its own connection, type (Neo4j/FalkorDB), and embedding model. A **masterVault** runs the MCP server and manages all databases across all registered vaults. Tell Claude which database to query, or let it discover available databases with `list_databases`.

### 🤖 20 MCP Tools for AI Assistants

A full MCP server (11 graph tools + 9 vault file tools) gives Claude — or any MCP client — direct, structured access to your knowledge. Search memories, add episodes, read and write notes, explore folders, all from your AI conversation.

### 🏗️ Custom Ontology Manager

Define your own entity types, edge types, and property descriptions. Generate Pydantic models with one click. The AI understands your custom data structures during extraction.

### ⚡ Obsidian CLI Integration

All 9 file operation tools run through the native **Obsidian CLI** (v1.12+) — stateless subprocess calls with no persistent WebSocket, no connection race conditions, no heartbeat. Multi-vault support via a single `vault_id` parameter.

### 🌐 Streamable HTTP MCP Transport _(new in v1.4.0)_

Connect **Roo Code, Cursor, and any HTTP-capable MCP client** directly to MegaMem — no Claude Desktop required. Enable the opt-in Streamable HTTP server (MCP spec 2025-03-26) in Plugin Settings → Servers. The plugin auto-starts a dedicated HTTP process on port `3838` with Bearer token auth. All 19 tools are available over HTTP. Claude Desktop stdio is completely unchanged.

### 🔄 Intelligent Sync

Auto-sync on interval, sync on demand, or trigger from MCP. Filter by folder inclusion/exclusion. Choose "new only" or "new + updated". Frontmatter-tracked `mm_uid` ensures path-independent note identity.

### ✦ MegaMem Pro _(new)_

A dedicated **Pro tab** in plugin settings for licensed Stewards. Validate your API key, check and install content packages (vault templates, ontology packs), and access upcoming hosted services — all in-plugin. Free plan users keep all MCP tools; Pro is content delivery and future hosted features.

---

## 🚀 BETA Launch

MegaMem is **stable in daily production use** and currently in public beta. We're actively seeking testers to stress-test the system across diverse environments — different vaults, databases, LLM providers, and operating systems. If you find something, open an issue. If it works great, tell someone.

- **Install now** via [BRAT](https://github.com/TfTHacker/obsidian42-brat) → `C-Bjorn/megamem-mcp`
- Python components install **automatically** on first launch — no manual downloads
- Windows (Neo4j) is most battle-tested; macOS works great; Linux support is there but less tested

---

## 🛠️ MCP Tools Reference

All 20 tools are available to Claude Desktop and any MCP-compatible client.

### Graph Operations (11)

| Tool                      | Description                                                                 |
| ------------------------- | --------------------------------------------------------------------------- |
| `add_memory`              | Add an episode/memory to the knowledge graph (`database_id` optional)       |
| `add_conversation_memory` | Store a conversation as a structured memory episode                         |
| `search_memory_nodes`     | Semantic search for entity nodes in the graph (`database_id` optional)      |
| `search_memory_facts`     | Search for relationships and facts between entities (`database_id` optional) |
| `get_episodes`            | Retrieve the most recent N episodes from a group                            |
| `get_entity_edge`         | Get relationships for a specific entity by name                             |
| `delete_entity_edge`      | Remove a specific relationship edge by UUID                                 |
| `delete_episode`          | Remove a specific episode by ID                                             |
| `list_group_ids`          | List all group IDs (namespaces) in the vault                                |
| `list_databases`          | List all configured database targets — use before routing with `database_id` |
| `clear_graph`             | Clear the entire memory graph (use with caution)                            |

### Obsidian File Operations (9) — via Obsidian CLI

| Tool                        | Description                                                            |
| --------------------------- | ---------------------------------------------------------------------- |
| `search_obsidian_notes`     | Search vault notes by filename and/or content                          |
| `read_obsidian_note`        | Read a note's full content (with optional line map for editing)        |
| `update_obsidian_note`      | Update a note — 5 modes: full file, frontmatter, append, range, editor |
| `create_obsidian_note`      | Create a new note at a specified path                                  |
| `list_obsidian_vaults`      | List all registered Obsidian vaults                                    |
| `explore_vault_folders`     | Explore vault folder structure (tree/flat/paths output)                |
| `create_note_with_template` | Create a note using a Templater template with intelligent routing      |
| `manage_obsidian_folders`   | Create, rename, or delete vault folders                                |
| `manage_obsidian_notes`     | Delete or rename/move notes (cross-folder moves supported)             |

> Full parameter reference: [docs/mcp-commands.md](https://c-bjorn.github.io/MegaMem/#/mcp-commands) — Updated for v1.5 with `database_id` routing on all graph tools.

---

## 📋 How It Works

### 1. Schema Discovery

The plugin scans your vault frontmatter and infers entity types and properties:

```yaml
---
type: Person
name: "Jane Smith"
role: "Researcher"
organization: "TechCorp"
tags: ["AI", "Knowledge Graphs"]
---
```

### 2. Pydantic Model Generation

Your frontmatter patterns become typed Graphiti extraction models:

```python
class Person(BaseNode):
    name: Optional[str] = Field(None, description="Person's full name")
    role: Optional[str] = Field(None, description="Current role or title")
    organization: Optional[str] = Field(None, description="Current employer")
```

### 3. Temporal Graph Sync

Notes are processed through Graphiti's extraction pipeline:

- Entities become graph nodes with versioned properties
- Relationships are extracted from note content via LLM
- `mm_uid` frontmatter tracks each note across renames and moves
- AI assistants query this structured graph via MCP

---

## 🚀 Getting Started

### Prerequisites

| Component | Minimum                 | Notes                                                         |
| --------- | ----------------------- | ------------------------------------------------------------- |
| Obsidian  | **1.12.4+ (installer)** | Must run the full installer — in-app updates don't enable CLI |
| Python    | 3.11+                   | Managed automatically via UV                                  |
| Database  | Neo4j 5+ or FalkorDB 1+ | Neo4j Desktop is easiest for local use                        |

> ⚠️ **Obsidian installer required**: Download and run the full installer from [obsidian.md/download](https://obsidian.md/download). In-app auto-update does **not** update the CLI binary. Then go to `Settings → General → Command line interface → Register`.

### Install via BRAT _(recommended)_

1. Install [BRAT](https://github.com/TfTHacker/obsidian42-brat) from Community Plugins
2. BRAT → **Add Beta Plugin** → paste `C-Bjorn/megamem-mcp`
3. A dialog appears after ~3 seconds: click **"Install / Update Components"**
   - Downloads and installs `graphiti_bridge` + `mcp-server` automatically
4. Plugin is ready

### 7-Step Setup

**Step 0 — Register Obsidian CLI** _(required for file tools)_
Run the Obsidian 1.12.4+ installer → `Settings → General → CLI → Register` → restart terminal → verify with `obsidian version`

**Step 1 — Set up a graph database**
[Neo4j Desktop](https://neo4j.com/download/) (recommended) or FalkorDB via Docker. See [Database Setup Guide](https://c-bjorn.github.io/MegaMem/#/guides/database-setup).

**Step 2 — Install Python dependencies**
Plugin Settings → Python Environment → **"Install Dependencies"** (uses UV by default — works on macOS/Windows/Linux).

**Step 3 — Configure LLM provider**
Plugin Settings → API Keys → enter your key. Click **"Load Defaults"** to populate recommended models.

**Step 4 — Connect the database**
Plugin Settings → Database Configuration → enter your connection details → **"Test Connection"** → **"Initialize Schema"**.

**Step 5 — Connect your MCP client**
- **Claude Desktop (stdio):** Plugin Settings → Servers → **"Generate Config"** → paste into `claude_desktop_config.json` → restart Claude Desktop.
- **Roo Code / Cursor (HTTP):** Plugin Settings → Servers → Streamable HTTP → enable toggle → **"Copy MCP Config"** → paste into your client's MCP config. No Claude Desktop needed.

**Step 6 — (Optional) Configure sync**
Set included/excluded folders, choose sync mode (new only vs. new + updated), set auto-sync interval.

**Step 7 — Start syncing**
Two ways to sync:

- **Single note:** click the **sync icon** (top-right of any note window) to sync the current note
- **Bulk sync:** click the **MegaMem icon** in the left sidebar to open the **Sync Manager**

> ⚠️ **Notes must have a `type` property in their frontmatter to use bulk Sync Manager.**

---

## 🎯 Use Cases

### Personal Knowledge Management

Build a graph of the people, projects, ideas, and relationships in your life. Ask Claude "what do I know about X?" and get answers drawn from your actual notes, with full temporal context. It works as a personal CRM, project tracker, and second brain — all from your existing vault without restructuring anything.

### AI-Assisted Note-Taking

With 9 native Obsidian file tools, Claude can create, search, and update notes directly in your vault mid-conversation. Draft a meeting note, file it in the right folder, sync it to the graph — all in one step, without leaving the chat.

_Also great for:_ research & academia (literature graphs, citation tracking), business intelligence (competitor research, knowledge bases), creative projects (world-building, character arcs), and multi-team knowledge management with namespaced vaults.

---

## 📚 Documentation

### Getting Started

- [Introduction](https://c-bjorn.github.io/MegaMem/) — Overview and core concepts
- [Quick Start Guide](https://c-bjorn.github.io/MegaMem/#/quick-start) — Up and running in minutes
- [Plugin Settings Reference](https://c-bjorn.github.io/MegaMem/#/plugin-settings) — All configuration options

### Guides

- [Database Setup](https://c-bjorn.github.io/MegaMem/#/guides/database-setup) — Neo4j and FalkorDB configuration
- [Claude Desktop Integration](https://c-bjorn.github.io/MegaMem/#/guides/claude-integration) — MCP config and connection
- [Ontology Manager](https://c-bjorn.github.io/MegaMem/#/guides/ontology-manager) — Custom entity types and schemas
- [Sync Manager](https://c-bjorn.github.io/MegaMem/#/guides/sync-manager) — Sync behavior and controls

### Reference

- [MCP Commands](https://c-bjorn.github.io/MegaMem/#/mcp-commands) — All 19 tools with full parameter reference
- [FAQ](https://c-bjorn.github.io/MegaMem/#/faq) — Common questions answered

---

## 🤝 Community & Support

- **[GitHub Issues](https://github.com/C-Bjorn/megamem-mcp/issues)** — Bug reports and feature requests
- **[GitHub Discussions](https://github.com/C-Bjorn/megamem-mcp/discussions)** — Questions, use cases, show & tell
- **[Submit & Fund Features](https://endogon.com/roadmap)** — Vote on and fund roadmap items
- **[Contributing Guide](https://c-bjorn.github.io/MegaMem/#/contributing)** — How to contribute code or docs

---

## 🔮 Roadmap

### Shipped ✅

- **Multi-database support** — multiple named Neo4j/FalkorDB targets, per-DB embedding config, sync dropdown per note _(v1.5)_
- **Multi-vault architecture** — masterVault control panel, childVault registration, MCP `database_id` routing, `list_databases` tool _(v1.5)_
- Temporal knowledge graph sync (Graphiti + Neo4j/FalkorDB)
- 20 MCP tools — 11 graph operations + 9 Obsidian file tools
- Obsidian CLI integration (stateless, multi-vault, no WebSocket)
- Auto schema discovery from vault frontmatter
- Custom ontology manager with Pydantic model generation
- Model Library — live model fetching from 8 LLM providers
- Constrained ontology generation (edge type cap + deduplication)
- Ontology file separation (`ontology.json` split from `data.json`)
- Auto-update system — Python components auto-install and self-update
- MegaMem Pro tab — license validation + content package delivery

### In Progress / Near-term 🔄

- Obsidian Community Plugins submission
- Graph visualization within Obsidian
- Advanced query builder

### Future 🌱

- Built-in LLM chat interface inside Obsidian
- Cloud-hosted graph option (no local database required)
- Mobile support
- Additional database backends (Kuzu, Amazon Neptune)

---

## 💡 Philosophy

MegaMem embraces **progressive formalization**: start with plain notes, let patterns emerge naturally, then add structure as your knowledge matures. The graph enriches your vault — it doesn't replace the way you write.

> _Gate services, not tools._ All 20 MCP tools are free. Forever.

---

## 🙏 Built With

- [Graphiti](https://github.com/getzep/graphiti) by Zep — temporal knowledge graph engine
- [Obsidian API](https://github.com/obsidianmd/obsidian-api) — plugin foundation
- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic — AI tool interface
- [JSZip](https://stuk.github.io/jszip/) — in-plugin zip extraction
- TypeScript + Svelte

## 📄 License

MIT — see [LICENSE.txt](LICENSE.txt)

---

**Transform your notes into knowledge. Give your AI a memory worth having.**

_Built by [Casey Bjørn](https://github.com/C-Bjorn) @ [ENDOGON](https://endogon.com)_
