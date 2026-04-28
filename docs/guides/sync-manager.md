---
title: MegaMem Panel — Sync & Analytics
description: Manage sync operations and explore analytics from the unified MegaMem panel.
type: guide
category: Advanced
difficulty: intermediate
tags:
  - Sync
  - Analytics
  - Graph
  - Configuration
  - Data Transfer
last_updated: 2026-03-23
date_created: 2025-09-23T17:46
date_updated: 2026-03-23T00:00
---

# MegaMem Panel — Sync & Analytics

The unified **MegaMem panel** provides a single tabbed side-panel for all core operations: **Ontology** (custom entity/edge type management), **Sync** (bulk sync operations and status), and **Analytics** (comprehensive sync metrics and cost visibility). It replaces the prior separate Schema Manager and Sync Manager side-panels.

## Opening the MegaMem Panel

The panel can be opened four ways:

1. **Ribbon Icon**: Click the 🧠 **brain icon** (copper/orange) in the Obsidian ribbon.
2. **Command Palette**: `MegaMem: Open Panel` (or `Open Sync` / `Open Analytics` / `Open Ontology` to jump directly to a specific tab).
3. **Settings Tab**: Navigate to the MegaMem plugin settings → Sync Configuration → "Open Sync UI".
4. **Tab persistence**: The panel remembers the last active tab and restores it on re-open.

## Overview

The Sync Manager presents two main tabs: "Quick Sync" and "Advanced".

## 1. Quick Sync

The "Quick Sync" tab is designed for easy, category-based synchronization of your notes. It provides an at-a-glance overview of your note types and their synchronization status.

#### Sync in Progress Display

When a synchronization task is active, a progress bar and status message will appear, indicating:

-   **Current Sync Phase**: e.g., "preparation", "analysis", "sync", "cleanup".
-   **Progress Bar**: Visual representation of completion percentage.
-   **Current / Total Notes**: Shows how many notes have been processed out of the total.
-   **Estimated Time Remaining**: Provides an estimate of how much time is left for the current sync operation.
-   **Cancel Button**: Allows you to halt an ongoing sync process.

#### Sync by Category Table

This table breaks down your syncable notes by type, offering specific actions for each category:

-   **Note Type**: The classification of your notes (e.g., "Person", "Project", "Book").
-   **Total**: The total number of notes discovered for that type.
-   **Synced**: The count of notes that are currently synchronized with the graph.
-   **Private**: The number of notes marked as private (and thus excluded from sync).
-   **SyncUpdated Button**:
    -   Displays the number of notes of this type that have been previously synced but contain modifications.
    -   Clicking this button initiates a sync operation specifically for these updated notes.
-   **SyncNew Button**:
    -   Displays the number of notes of this type that are new or have not yet been synced.
    -   Clicking this button initiates a sync operation for all new/unsynced notes of that category.

## 2. Advanced

The "Advanced" tab provides granular control over note selection, filtering, and customization for synchronization tasks.

### Filter Controls

The Advanced tab offers several filtering options to refine your note selection:

-   **Source Filters**: Filter by entity type to sync specific categories of notes.
-   **Status Filters**: Select notes based on their sync status (new, updated, synced, or private).
-   **Path Filters**: Filter notes by folder location within your vault.

### Selection Helpers

Quick selection tools to streamline your workflow:

-   **Select All**: Select all notes matching current filters.
-   **Deselect All**: Clear all selections.
-   **Invert Selection**: Flip the current selection state.

### Results Table

The results table displays all notes matching your filter criteria:

-   **Checkbox**: Select/deselect individual notes for sync.
-   **Status Icon**: Visual indicator of the note's sync status.
-   **Note Title**: The name of the note.
-   **Type**: The entity type classification.
-   **Path**: Location within your vault.
-   **Modified**: Last modification timestamp.

## Sync Notifications

Upon completion of a sync operation, a notification will appear in Obsidian:

-   **Success**: `✅ [Sync Type] completed: [X] notes processed`
-   **Failure**: `❌ [Sync Type] failed: [Error Message]`

## 3. Analytics Tab

The **Analytics** tab provides a comprehensive dashboard for understanding your sync history, token usage, and costs. It reads from the local SQLite `sync.db` file and updates in real time.

### Controls Bar

- **All Databases / specific DB** dropdown — filter all metrics to a single database
- **Date range presets** — Today, 7d, 30d, All Time
- **Refresh** button — re-query SQLite on demand
- **Auto (30s)** toggle — automatic refresh every 30 seconds when the tab is visible

### Summary Cards

Four animated cards show totals for the current filter:

| Card | Source |
|---|---|
| **Synced Notes** | `sync_records` COUNT (always populated, even for pre-analytics syncs) |
| **Entities Extracted** | `SUM(entity_count)` from `sync_analytics` |
| **Edges Created** | `SUM(edge_count)` from `sync_analytics` |
| **Estimated Cost** | `SUM(estimated_cost)` from `sync_analytics` × `model_pricing` rates |

> **Cost accuracy:** Pricing data is seeded from your Model Library (Settings → Model Library → Fetch). Fetching populates `model_pricing` with real provider prices. Bundled defaults cover common OpenAI, Anthropic, and Google models.
> **OpenRouter users:** Cost display requires the `provider` field in `model_pricing` to match the vendor prefix (e.g. `google`, not `openrouter`). As of v1.6.13, this is normalized automatically on every plugin load — no manual SQL update needed.

### Sync Timeline

A line/area chart showing sync count over time (day granularity for 30d/All Time, hour granularity for Today/7d). Toggle the **Entities** overlay series on/off via the chart legend.

### Token Usage by Model

Stacked bar chart with a 3-mode toggle:

- **Big Model** — tokens grouped by primary LLM (`llm_model`) used for extraction
- **Small Model** — tokens grouped by the secondary/fast LLM (`llm_small_model`)
- **Both Models** — union of big + small rows, labeled with `(big)`/`(small)` suffixes

> Note: The Python bridge token tracker accumulates all tokens for a sync session. Token counts reflect total session usage, not per-model splits inside a single session.

### Model Performance Table

Sortable table: Model, Provider, Syncs, Avg Duration, Avg In Tokens, Avg Out Tokens, Avg Entities, Avg Edges, Total Cost. Click any column header to sort. Provider is inferred from the `model_pricing` table or stripped from the model ID prefix (e.g. `openai/gpt-4o` → `openai`).

### Synced Notes

Full list of sync sessions in the current date/DB filter (up to 500). Each row shows:
- Note filename (clickable → opens note in Obsidian), ✓/✗ status icon, Model · Provider, Cost, Synced At

Click any row to **expand** an inline detail panel:
- DB, Duration, In Tokens, Out Tokens, Total Tokens, Entities, Edges, Small Model, Error message (if failed)

Use the filter input to narrow by note path.

### Sync Health

- Failed sync count with error summaries (last 10)
- Stale notes count (notes not synced in the past 7 days)
- Duration trend (7-day rolling averages)

---

## Sagas

Sagas are lightweight graph nodes that group related episodes into ordered, chronological timelines. When saga grouping is enabled for a namespace, Graphiti creates `Saga` nodes in the knowledge graph and connects each episode to its saga via a `HAS_EPISODE` edge. Sequential episodes within the same saga are also linked via `NEXT_EPISODE` edges, enabling chronological traversal through your knowledge timeline.

### Configuring Sagas

Saga grouping is configured **per namespace** in the folder mapping rows under **Knowledge Namespacing → Custom Folder Mappings** in plugin settings. Each namespace can use one of four grouping strategies:

-   **By Note Type (default)**: Groups episodes by note type and namespace (e.g. `daily-note-Journal`).
-   **Single Saga for namespace**: All notes in the namespace share a single saga.
-   **No saga grouping**: Episodes are stored without saga connections.
-   **Custom frontmatter property**: The saga name is derived from a frontmatter key you specify.

See [Ontology Manager](ontology-manager.md) for full per-namespace configuration details.