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

The Sync Manager can be accessed in two primary ways:

1.  **Command Palette**: Open the Command Palette (Ctrl/Cmd + P) and search for "Open Sync UI".
2. **Settings Tab**: Navigate to the MegaMem plugin settings, and under "Sync Configuration", click the "Open Sync UI" button.

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

The "Advanced" tab is currently under development. It is intended to provide more granular control over note selection, filtering, and customization for synchronization tasks.

<i data-lucide="alert-triangle"></i> Advanced Sync Under Development
The "Advanced" sync features are not yet fully implemented. This tab currently serves as a placeholder for forthcoming comprehensive controls for note selection and customized sync operations.

## Sync Notifications

Upon completion of a sync operation, a notification will appear in Obsidian:

-   **Success**: `✅ [Sync Type] completed: [X] notes processed`
-   **Failure**: `❌ [Sync Type] failed: [Error Message]`