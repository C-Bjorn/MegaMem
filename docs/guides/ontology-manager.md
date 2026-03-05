---
title: Ontology Manager
description: Configure and manage your knowledge graph's schema, including entity types, properties, and relationships.
type: guide
category: Advanced
difficulty: intermediate
tags:
  - Schema
  - Ontology
  - Graph
  - Configuration
last_updated: 2026-03-05
date_created: 2025-09-23T17:40
date_updated: 2026-03-05T00:00
---

# Ontology Manager

The MegaMem Ontology Manager provides a comprehensive interface for defining and fine-tuning the structure of your knowledge graph. It allows you to discover entity types from your vault, manage their properties, define custom relationship (edge) types, and configure how these relationships can exist between different entities (edge mappings). This ensures a consistent and structured representation of your knowledge, enabling powerful querying and analysis.

## Accessing the Ontology Manager

The Ontology Manager can be accessed in two ways:

1.  **Ribbon Icon**: Click the `database` icon in the Obsidian ribbon (left sidebar).
2.  **Command Palette**: Open the Command Palette (Ctrl/Cmd + P) and search for "Open Schema Manager".

## Ontology Storage

MegaMem stores ontology data in a dedicated **`ontology.json`** file co-located with the plugin:

```
.obsidian/plugins/megamem-mcp/ontology.json
```

This file contains all schema-related data: entity descriptions, edge types, edge type mappings, property selections, and property descriptions. Runtime settings (API keys, LLM configuration, database connection) remain in `data.json`.

**Why two files?** `data.json` was growing to ~120KB due to ontology data. Keeping ontology separate makes it human-readable, easier to back up, and allows future multi-ontology scenarios. Existing installations auto-migrate on first load — no manual action required.

## Overview

The Ontology Manager is divided into four main tabs:

-   **Entity Types**: Manage the different types of entities (e.g., Person, Project, Concept) discovered in your vault.
-   **Properties**: Configure the attributes associated with each entity type.
-   **Edge Types**: Define the types of relationships that can exist between entities (e.g., `WORKS_FOR`, `USES`).
-   **Edge Mappings**: Specify which entity types can be connected by which edge types.

Each section offers tools for defining schema elements, editing descriptions, and interacting with default or LLM-suggested configurations.

## Edge Type Naming Convention

All edge type names use **SCREAMING_SNAKE_CASE** (e.g., `WORKS_FOR`, `USES`, `CREATES`, `MEMBER_OF`). This aligns with Graphiti's native edge extraction behavior — Graphiti's internal prompt hardcodes SCREAMING_SNAKE_CASE for all `relation_type` values, so using PascalCase in ontology definitions creates silent mismatches in the graph.

> **Why not PascalCase?** Graphiti's `extract_edges.py` always generates edge names in SCREAMING_SNAKE_CASE regardless of what names are defined in the ontology. Aligning our ontology to this convention ensures consistent graph queries and avoids duplicate relationship entries like `USES` vs `Uses` in Neo4j.

## 1. Entity Types

This tab allows you to manage the primary building blocks of your knowledge graph.

### LLM Automatic Ontologies

This section provides tools for leveraging Language Models to automatically generate and suggest entity descriptions based on your vault content.

-   **Generate Entity Descriptions**: Use AI to draft descriptions for your entity types with three filter modes:
    -   **Regenerate All**: Regenerate descriptions for all entity types, overwriting existing descriptions.
    -   **Skip User Defined**: Only generate descriptions for entities without user-defined descriptions.
    -   **New Only**: Generate descriptions only for newly discovered entity types.
-   **Suggest Property Descriptions**: Enables AI to suggest property definitions using the same filter modes.
-   **🤖 Generate Complete Ontology**: Batched LLM generation for **enabled entity types only** — generates entity descriptions, edge types (SCREAMING_SNAKE_CASE), and edge mappings. Processes 4 entities per batch. Respects the `Max Edge Types` cap to prevent proliferation. Runs a consolidation pass after all batches to merge semantic duplicates. See [Constrained Generation](#constrained-ontology-generation) for details.
-   **Load All Default Entity Descriptions**: Populates descriptions for all discovered entity types using predefined defaults, if available.

#### Graphiti Compliance Dashboard

This dashboard offers a quick overview of how well your defined entity properties adhere to Graphiti's naming conventions and best practices.

-   **Compliance Score**: A percentage indicating the validity of your property names.
-   **Valid**: Number of properties following naming conventions.
-   **Warnings**: Number of properties with minor naming issues.
-   **Protected**: Number of system-reserved properties (cannot be changed).
-   **Apply All Naming Suggestions**: Automatically renames properties with warnings to their suggested, compliant forms.

#### Base Entity Type

Defines the fundamental properties (`type`, `tags`, `created`) that all other entity types inherit. These are system-managed and always enabled to ensure consistency across your graph.

-   **View Properties**: Navigates to the "Properties" tab, filtered to show BaseEntity properties.

#### Custom Entity Types List

Displays a list of all entity types discovered in your vault (e.g., based on `type` frontmatter fields).

-   **Toggle Entity Enabled/Disabled**: Activates or deactivates an entity type for Pydantic model generation. Enabled entities will be included in your generated knowledge graph schema. **Only enabled entities are processed by Generate Complete Ontology.**
-   **Edit Description**: Allows you to manually edit the description for an entity type. You can also "Load Default" if a predefined description exists.
-   **LLM Suggest**: Provides AI-generated description suggestions. A confirmation modal allows you to review and accept/reject the suggested description before applying.
-   **Details**: Shows the number of files associated with the entity type, the count of its properties, and its individual compliance score.

#### Cleanup — Entity Types

-   **🗑️ Cleanup Selections**: Removes `propertySelections` entries for entity types that no longer exist in the schema (orphan cleanup).

## 2. Properties

This tab lists all properties associated with your entity types, allowing for detailed configuration.

### LLM Automatic Property Descriptions

This section provides AI-driven assistance for property management.

-   **Generate All Property Descriptions**: Auto-generate descriptions for all entity properties with filter modes:
    -   **Regenerate All**: Regenerate descriptions for all properties, overwriting existing ones.
    -   **Skip User Defined**: Only generate descriptions for properties without user-defined descriptions.
    -   **New Only**: Generate descriptions only for newly discovered properties.
-   **Load Default Descriptions**: Applies predefined descriptions to properties.
-   **Enable Default Properties**: Activates all properties that have default descriptions, excluding protected or globally ignored fields.

#### Cleanup — Properties

-   **🗑️ Cleanup Properties**: Three cleanup modes:
    -   **Orphaned Entities** *(default)*: Removes `propertyDescriptions` entries for entity types that no longer exist in the schema.
    -   **Disabled Properties**: Removes descriptions for properties that are currently disabled (`propertySelections[entity][prop] === false`).
    -   **⚠️ Remove All**: Nuclear reset — wipes the entire `propertyDescriptions` store.

#### All Entity Properties

An expandable list of all discovered entity types, each showing its properties.

-   **Accordion Toggle**: Expands/collapses the list of properties for each entity type.
-   **Bulk Actions**:
    -   **Select All**: Enables all non-protected and non-globally-ignored properties for the specific entity type.
    -   **Deselect All**: Disables all properties (except protected) for the specific entity type.
-   **Property Details**: For each property:
    -   **Enable/Disable Checkbox**: Includes or excludes the property from Pydantic model generation. Protected or globally ignored properties cannot be changed.
    -   **Property Mapping Indicator**: Shows if a property name has been mapped (e.g., from `MyProperty` to `my_property`).
    -   **Property Defined**: Toggles whether the property's description is stored in `ontology.json`.
    -   **Status Indicator**: Shows if a property is `PROTECTED` (system-reserved), `IGNORED` (globally), has `NAMING` issues, is `ENABLED`, or `DISABLED`.
    -   **Description Input**: Edit the property's description. Can "Load Default" or use "LLM Suggest" with confirmation modal.
    -   **Validation Warnings**: Alerts for protected attributes, globally ignored fields, and naming suggestions, with options to apply suggestions.

## 3. Edge Types

Manage the different kinds of relationships between entities. All edge type names use SCREAMING_SNAKE_CASE.

### Edge Type Management (LLM Banner)

-   **Generate Edge Type Suggestions**: AI-generated suggestions for edge types based on your vault content.
-   **Generate Edge Property Descriptions**: LLM descriptions for all edge-type properties.
-   **Load Default Properties**: Fills missing properties on existing edge types from built-in defaults. Only affects edge types that have no properties defined yet (does not overwrite user customizations).
-   **🗑️ Cleanup Edge Types**: Opens the cleanup modal with options:
    -   **Skip User-Defined** *(toggle)*: When enabled, skips edge types with `isUserDefined: true` or `source: 'user'`.
    -   **New Only**: Removes edge types added in the current session (today).
    -   **No Mappings**: Removes edge types that have no `allowedEdges` references in any mapping.
    -   **Remove All**: Removes all edge types (respects Skip User-Defined toggle).

### Edge Types Management

-   **Current Edge Types**: Lists all currently defined edge types, along with their property counts.
-   **Edit Description**: Modify the description of a custom edge type.
-   **Delete Edge Type**: Remove a custom edge type.
-   **Add Property**: Add custom properties (name, type, description, required status) to an edge type.
-   **Quick Add Common Types**: Pre-fills common relationship types: `WORKS_FOR`, `USES`, `CREATES`, `MEMBER_OF`, `MANAGES`, `CONTAINS`.
-   **Add New Edge Type**: Manually add a new custom edge type with a name and description. Names must be SCREAMING_SNAKE_CASE.
-   **LLM Suggest Edge Types**: AI-generated suggestions for edge type descriptions based on your vault content.

### Available Default Edge Types

A list of predefined relationship types with descriptions (SCREAMING_SNAKE_CASE). You can add these to your custom edge types with a single click or "Add All" unused defaults.

### Max Edge Types Cap

The **Max Edge Types** numeric input (in the Edge Types tab LLM banner) controls the maximum number of edge types allowed in `ontology.json`. Default: **25**.

When `Generate Complete Ontology` runs:
- New edge types per batch are limited to `min(batchSize × 2, 8, remaining_cap)`.
- When the cap is reached, subsequent batches generate mappings only using existing types.
- A consolidation pass runs after all batches to merge semantic duplicates (e.g., `IS_PART_OF` + `PART_OF` → canonical type).

## 4. Edge Mappings

Define the rules for how entities can be connected.

### Edge Mappings (LLM Banner)

-   **Generate Edge Mapping Suggestions**: LLM suggests entity-to-entity mappings based on your vault.
-   **🗑️ Cleanup Mappings**: Opens the cleanup modal with options:
    -   **Skip User-Defined** *(toggle)*: Skips mappings with `isUserDefined: true` or `source: 'user'`.
    -   **New Only**: Removes mappings added in the current session (today).
    -   **Remove All**: Removes all mappings (respects Skip User-Defined toggle).

### Edge Type Mappings

This section allows you to rigorously define permissible relationships between different entity types, controlling the structural integrity of your knowledge graph.

-   **Mapping List**: Displays existing mappings (e.g., `Person` → `Project` via `WORKS_ON` or `MANAGES`).
-   **Edit Mapping**: Modify the source entity, target entity, and allowed edge types for an existing mapping.
-   **Delete Mapping**: Remove a custom edge mapping.
-   **Quick Add Common Mappings**: Pre-fills common mappings like `Person` → `Technology` (`USES`, `CREATES`) or `Entity` → `Entity` (`RELATED_TO`). All `allowedEdges` values are SCREAMING_SNAKE_CASE.
-   **Add New Edge Mapping**: Manually create a new mapping by selecting a source entity, target entity, and allowed edge types.

### Suggested Edge Mappings

Based on your discovered entity types, the system will suggest common and logical mappings to help you quickly build out your graph's relational structure. You can add these individually or "Add All" suggestions.

## AI-Enhanced Features

The Ontology Manager integrates AI capabilities throughout the interface to assist with schema generation and maintenance.

### Individual LLM Suggest Buttons

Throughout the interface, "LLM Suggest" buttons provide context-aware AI assistance:

-   **Entity Descriptions**: Generate descriptions for individual entity types based on your vault content and usage patterns.
-   **Property Descriptions**: Suggest descriptions for individual properties based on their name, type, and context.
-   **Edge Type Descriptions**: Generate descriptions for relationship types based on how entities connect in your vault.

Each suggestion includes a confirmation modal where you can review, edit, and approve before applying.

### Bulk Generation Operations

Efficient batch operations for large-scale schema management:

-   **Generate All Entity Descriptions**: Process all entity types at once with customizable filter modes.
-   **Generate All Property Descriptions**: Batch generate property descriptions across all entity types.
-   **Generate Complete Ontology**: Constrained schema generation for **enabled entity types only**. Batches 4 entities per LLM call. Enforces `maxTotalEdgeTypes` cap and reuse-first prompting. See [Constrained Ontology Generation](#constrained-ontology-generation).

### Filter Modes

All bulk generation operations support three filter modes to control scope:

1.  **Regenerate All**: Process all items, overwriting existing descriptions (use for schema refresh).
2.  **Skip User Defined**: Only generate for items without user-defined descriptions (preserves manual work).
3.  **New Only**: Generate only for newly discovered items (incremental schema growth).

### Supported LLM Providers

The Ontology Manager supports five LLM providers for AI-enhanced features:

-   **OpenAI**: GPT-4 and GPT-3.5 models
-   **Anthropic Claude**: Claude 3 series models
-   **Google Gemini**: Gemini Pro and Ultra models
-   **Ollama**: Fully private local models (requires local installation)
-   **OpenRouter**: Access to multiple model providers through a single API

Configure your preferred provider in the plugin settings under "LLM Configuration".

## Constrained Ontology Generation

`Generate Complete Ontology` uses a constrained pipeline to prevent edge type proliferation.

### Why Constraints Are Needed

Unconstrained generation causes combinatorial explosion: 17 entities × edge types per entity × mappings per edge type = thousands of edge type entries. A single unconstrained run can inflate `ontology.json` to 6,000+ lines, wasting tokens on every sync and degrading extraction quality.

### How It Works

| Step | Description |
|---|---|
| **1. Pre-flight** | Loads default properties and descriptions for all enabled entities before any LLM calls. |
| **2. Batching** | Processes 4 entities per batch. Each batch receives the full list of existing edge type names as context. |
| **3. Reuse-first** | Prompt instructs: "Reuse existing edge types wherever they apply. Only propose a NEW type if no existing type adequately describes the relationship." |
| **4. Cap enforcement** | New edge types per batch = `min(batchSize × 2, 8, remaining_cap)`. When cap is reached, batch generates mappings only. |
| **5. Consolidation** | After all batches, one final LLM call identifies semantic duplicates and produces a merge map. Redundant types are removed from `edgeTypes` and `edgeTypeMap`. |

### Recommended Workflow

1. Enable entity types you want to include (Entity Types tab).
2. Set **Max Edge Types** to your desired cap (default: 25 is recommended for personal vaults).
3. Click **🤖 Generate Complete Ontology** → choose **New Only** or **Regenerate All**.
4. Review the results — use **🗑️ Cleanup Edge Types** to prune unwanted entries.
5. Click **Refresh Schemas** to rebuild Pydantic models from the updated ontology.

## Cleanup Operations

Each tab has a dedicated **🗑️ Cleanup** button for removing stale or redundant entries:

| Tab | Button | Best for |
|---|---|---|
| Entity Types | 🗑️ Cleanup Selections | Removing orphaned `propertySelections` after entity types are deleted |
| Properties | 🗑️ Cleanup Properties | Removing descriptions for disabled or deleted properties |
| Edge Types | 🗑️ Cleanup Edge Types | Pruning unused or over-generated edge types |
| Edge Mappings | 🗑️ Cleanup Mappings | Removing stale or test mappings |

The **Skip User-Defined** toggle (on Edge Types and Edge Mappings cleanup) protects any entries you manually created or marked as user-defined.

## Per-Namespace Configuration

Each folder mapping in your namespace settings (configured under **Knowledge Namespacing → Custom Folder Mappings** in plugin settings) supports per-namespace options that control how notes in that namespace are processed and stored. These settings appear on each folder mapping row.

### Custom Extraction Instructions

An optional free-text field that overrides the vault-wide **Global Extraction Instructions** for notes in this namespace only. Use this when a specific folder requires different extraction guidance — for example, telling the LLM to focus only on action items in your Tasks folder, or to extract entities differently for your Journal namespace.

When left empty, the global extraction instructions (set in plugin settings) apply.

> **Note:** `globalExtractionInstructions` applies to entity extraction only — it does not reach Graphiti's edge extraction step. Edge naming is always SCREAMING_SNAKE_CASE (Graphiti-enforced).

### Saga Grouping

Controls how episodes from this namespace are grouped into **Sagas** — ordered timeline nodes that link related episodes together chronologically.

| Option | Behavior |
|---|---|
| `By Note Type (default)` | Creates sagas named `{note-type}-{group_id}` (e.g. `daily-note-Journal`) |
| `Single Saga for namespace` | All notes in this namespace share one saga named `all-{group_id}` |
| `No saga grouping` | Episodes are stored without saga connections |
| `Custom frontmatter property` | The saga name is read from a frontmatter key you specify |

### Saga Property Key

*(Visible when Saga Grouping = "Custom frontmatter property")* Specifies which frontmatter key's value to use as the saga name. For example, if set to `project`, a note with `project: Acme Corp` in its frontmatter will be grouped under the `Acme Corp` saga.
