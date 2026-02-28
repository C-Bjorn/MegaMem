---
title: Sync Manager
description: Manage and monitor the synchronization of your Obsidian notes to the MegaMem knowledge graph.
type: guide
category: Advanced
difficulty: intermediate
tags:
  - Sync
  - Graph
  - Configuration
  - Data Transfer
last_updated: 2025-09-23
date_created: 2025-09-23T17:46
date_updated: 2025-09-28T11:36
---

# Sync Manager

The MegaMem Sync Manager provides a centralized interface for controlling and observing the synchronization of your Obsidian notes with your knowledge graph. It offers both quick synchronization options for various note categories and a detailed view of ongoing sync processes.

## Accessing the Sync Manager

The Sync Manager can be accessed in three ways:

1.  **Ribbon Icon**: Click the `refresh-cw` icon in the Obsidian ribbon (left sidebar).
2.  **Command Palette**: Open the Command Palette (Ctrl/Cmd + P) and search for "Open Sync UI".
3. **Settings Tab**: Navigate to the MegaMem plugin settings, and under "Sync Configuration", click the "Open Sync UI" button.

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

## Sagas

Sagas are lightweight graph nodes that group related episodes into ordered, chronological timelines. When saga grouping is enabled for a namespace, Graphiti creates `Saga` nodes in the knowledge graph and connects each episode to its saga via a `HAS_EPISODE` edge. Sequential episodes within the same saga are also linked via `NEXT_EPISODE` edges, enabling chronological traversal through your knowledge timeline.

### Configuring Sagas

Saga grouping is configured **per namespace** in the folder mapping rows under **Knowledge Namespacing → Custom Folder Mappings** in plugin settings. Each namespace can use one of four grouping strategies:

-   **By Note Type (default)**: Groups episodes by note type and namespace (e.g. `daily-note-Journal`).
-   **Single Saga for namespace**: All notes in the namespace share a single saga.
-   **No saga grouping**: Episodes are stored without saga connections.
-   **Custom frontmatter property**: The saga name is derived from a frontmatter key you specify.

See [Ontology Manager](ontology-manager.md) for full per-namespace configuration details.