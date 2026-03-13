---
title: MegaMem Development Roadmap
description: "A clear and concise overview of MegaMem's journey: what's been achieved and what's next."
date: 2025-09-23
tags:
  - roadmap
  - development
  - milestones
  - future
sidebar: auto
date_created: 2025-09-23T11:23
date_updated: 2026-03-13T00:00
---

# 🗺️ MegaMem Development Roadmap

This document provides a concise overview of the MegaMem project's evolution, highlighting key achievements and outlining clear future directions.

## ✅ Achieved Milestones

MegaMem has successfully established a robust foundation, delivering powerful integration between Obsidian and advanced knowledge graph capabilities:

- **Ontology File Separation**: Extracted all ontology data from `data.json` into a dedicated `ontology.json` file co-located in the plugin directory. Reduces `data.json` from ~120KB to a lean runtime config file (~20KB). Existing installations auto-migrate on first plugin load — no manual action required. Ontology keys migrated: `entityDescriptions`, `edgeTypes`, `edgeTypeMap`, `propertySelections`, `propertyDescriptions`, `propertyMappings`, `baseEntityProperties`, `llmSchemaSettings`.
- **SCREAMING_SNAKE_CASE Edge Normalization**: Aligned all edge type naming with Graphiti's native convention. Graphiti's internal `extract_edges.py` hardcodes SCREAMING_SNAKE_CASE for all `relation_type` values — fighting it with PascalCase instructions caused duplicate edge entries in Neo4j. All ontology `allowedEdges` definitions and prompt examples updated. 796 historical PascalCase edges in production Neo4j migrated to SCREAMING_SNAKE_CASE.
- **Constrained Ontology Generation Pipeline**: Redesigned `Generate Complete Ontology` to prevent edge type proliferation. Key improvements: (1) processes enabled entity types only, (2) reuse-first batch prompt includes the full existing edge type list — LLM reuses before inventing, (3) `maxTotalEdgeTypes` cap (default: 25) enforced per batch with dynamic formula, (4) post-generation consolidation pass merges semantic duplicates (e.g. `IS_PART_OF` + `PART_OF`). Cap and progress exposed in the Edge Types tab UI.
- **Schema Manager Cleanup Buttons**: Added dedicated 🗑️ Cleanup modals to all four Ontology Manager tabs. Entity Types: removes orphaned property selections. Properties: three modes (orphaned entities, disabled properties, nuclear reset). Edge Types: prune by no-mappings / new-only / remove-all with optional Skip User-Defined protection. Edge Mappings: same modes. Prevents stale schema entries from accumulating across LLM generation runs.
- **Model Library & Live Provider Fetching**: Added a "Model Library" accordion in plugin settings (between API Keys and LLM Configuration). Users can fetch live model lists from 8 providers (OpenAI, Anthropic, Google, Groq, Ollama, Venice, OpenRouter, Azure), curate a personal short-list, and control which models appear in LLM Configuration dropdowns. OpenRouter models include capability metadata (`structured_outputs`, `tools`, `vision`, ZDR) extracted directly from the API. A **🟢 Graphiti Compatible** filter identifies models that work reliably with Graphiti's extraction pipeline (supports both `structured_outputs` and `temperature`). Model cache stored in its own `model-library-cache.json` file (separate from `data.json`). When 11+ models are in the short-list, LLM Model selector switches to a searchable autocomplete input.
- **Core Plugin Foundation**: Implemented an Obsidian plugin using TypeScript/Svelte, featuring automatic schema discovery by scanning vault patterns and removing manual YAML configuration.
- **Multi-Database Support** *(v1.5)*: Users can configure multiple named graph databases in plugin settings (`databases[]` array). Each entry has its own label, type (Neo4j/FalkorDB), connection params, embedding provider/model, and enabled state. Per-note sync icon opens a dropdown listing all configured DBs. SyncManager bulk sync gains DB multi-select. `sync.json` tracks per-DB state (`{ synced, graphitiUUID, lastSynced }` keyed by DB ID). Backward-compatible: existing single-DB configs auto-migrate to `databases[0]` on first load.
- **Per-DB Embedding Configuration** *(v1.5)*: Embedding provider, model, and dimensions moved from the global LLM settings into each individual DB config entry. Users with multiple databases can set different embedding models per database. Sync operations targeted to a specific DB automatically use that DB's embedding config, with fallback to `databases[0]` then legacy global settings.
- **Multi-Vault Architecture** *(v1.5)*: One vault is designated the **masterVault** — it runs the MCP server and manages a unified Databases control panel across all vaults. childVaults sync locally to their own DB with MCP disabled. A "Multi-Vault Mode" accordion lets users register child vaults (auto-discovered from `obsidian.json`). MCP tools gain an optional `database_id` param for routing queries to specific databases. New `list_databases()` MCP tool lets Claude discover available databases before querying. All 4 routing operations confirmed passing in post-implementation tests.
- **MegaMem Pro Settings Tab**: Added a dedicated **"MegaMem Pro"** tab inside plugin settings. Validates Pro API keys against the `megamem.endogon.com` edge functions, displays entitled content packages with version comparison (server vs. local), and installs/updates packages (zip extraction to vault root via JSZip). Future hosted services will surface here. All MCP tools remain free; Pro gates content delivery and future hosted features.
- **Comprehensive MCP Server**: Rebuilt the MCP (Model Context Protocol) server from scratch, now providing 10 Graphiti tools for direct graph interaction and 9 Obsidian file management tools.
- **Obsidian CLI Integration**: Migrated all 9 Obsidian file operation tools from a fragile WebSocket layer to stateless Obsidian CLI subprocess calls (v1.12+). Eliminates startup connection races, ERR_CONNECTION_RESET errors, and WebSocket contention between multiple MCP clients. Multi-vault targeting is a single `vault=` parameter — no persistent registry or heartbeat required.
- **Custom Ontology Integration**: Enabled custom ontology support with full Pydantic model generation, enhancing flexible data modeling.
- **FalkorDB Integration**: Successfully integrated FalkorDB, thoroughly resolving RediSearch compatibility challenges.
- **Advanced Sync Functionality**: Developed a sophisticated sync mechanism supporting temporal knowledge graphs and robust bidirectional synchronization with path-independent tracking (mmuids).
- **Production Readiness**: Ensured stability through Python bridge packaging fixes and refined the SchemaManager with a single-source-of-truth architecture.
- **Sequential Sync Groundwork**: Implemented sequential sync, laying groundwork for "Sync on Save" and scheduled sync.

## 🚀 Future Enhancements

Our focus remains on expanding MegaMem's capabilities while maintaining simplicity and performance:

- **Obsidian Community Plugins Submission**: Public GitHub release with versioning per Obsidian guidelines and submission to the community plugin repository.
- **Graph Visualization**: Integrate an interactive graph view (evaluating d3.js, cytoscape) directly inside Obsidian for a visual map of your knowledge.
- **Built-in LLM Chat Interface**: Native chat interface within Obsidian for direct knowledge graph interaction — ask questions, get answers, all without leaving your vault.
- **Cloud-hosted Graph Option**: Hosted graph database for users who don't want to run Neo4j or FalkorDB locally.
- **Ask Bjørn** *(Pro)*: Hosted AI assistant with deep MegaMem context — powered by your graph, accessible in-vault.
- **Additional Databases**: Kuzu and Amazon Neptune support.
- **Mobile**: Evaluate feasibility of mobile vault sync.

We ship continuously. Specific timelines are announced on [endogon.com/roadmap](https://endogon.com/roadmap) — you can also **submit and fund features** there.
