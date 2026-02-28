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
last_updated: 2025-09-23
date_created: 2025-09-23T17:40
date_updated: 2025-09-28T11:36
---

# Ontology Manager

The MegaMem Ontology Manager provides a comprehensive interface for defining and fine-tuning the structure of your knowledge graph. It allows you to discover entity types from your vault, manage their properties, define custom relationship (edge) types, and configure how these relationships can exist between different entities (edge mappings). This ensures a consistent and structured representation of your knowledge, enabling powerful querying and analysis.

## Accessing the Ontology Manager

The Ontology Manager can be accessed in two ways:

1.  **Ribbon Icon**: Click the `database` icon in the Obsidian ribbon (left sidebar).
2.  **Command Palette**: Open the Command Palette (Ctrl/Cmd + P) and search for "Open Schema Manager".

## Overview

The Ontology Manager is divided into four main tabs:

-   **Entity Types**: Manage the different types of entities (e.g., Person, Project, Concept) discovered in your vault.
-   **Properties**: Configure the attributes associated with each entity type.
-   **Edge Types**: Define the types of relationships that can exist between entities (e.g., WorksFor, Uses).
-   **Edge Mappings**: Specify which entity types can be connected by which edge types.

Each section offers tools for defining schema elements, editing descriptions, and interacting with default or LLM-suggested configurations.

## 1. Entity Types

This tab allows you to manage the primary building blocks of your knowledge graph.

### LLM Automatic Ontologies

This section provides tools for leveraging Language Models to automatically generate and suggest entity descriptions based on your vault content.

-   **Generate Entity Descriptions**: Use AI to draft descriptions for your entity types with three filter modes:
    -   **Regenerate All**: Regenerate descriptions for all entity types, overwriting existing descriptions.
    -   **Skip User Defined**: Only generate descriptions for entities without user-defined descriptions.
    -   **New Only**: Generate descriptions only for newly discovered entity types.
-   **Suggest Property Descriptions**: Enables AI to suggest property definitions using the same filter modes.
-   **Generate Complete Ontology**: Automatically generates a comprehensive schema including entities, properties, edge types, and mappings.
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

-   **Toggle Entity Enabled/Disabled**: Activates or deactivates an entity type for Pydantic model generation. Enabled entities will be included in your generated knowledge graph schema.
-   **Edit Description**: Allows you to manually edit the description for an entity type. You can also "Load Default" if a predefined description exists.
-   **LLM Suggest**: Provides AI-generated description suggestions. A confirmation modal allows you to review and accept/reject the suggested description before applying.
-   **Details**: Shows the number of files associated with the entity type, the count of its properties, and its individual compliance score.

## 2. Properties

This tab lists all properties associated with your entity types, allowing for detailed configuration.

### LLM Automatic Property Descriptions

This section provides AI-driven assistance for property management.

-   **Generate All Property Descriptions**: Auto-generate descriptions for all entity properties with filter modes:
    -   **Regenerate All**: Regenerate descriptions for all properties, overwriting existing ones.
    -   **Skip User Defined**: Only generate descriptions for properties without user-defined descriptions.
    -   **New Only**: Generate descriptions only for newly discovered properties.
-   **Suggest Property Types**: AI-assisted suggestions for property field types.
-   **Load Default Descriptions**: Applies predefined descriptions to properties.
-   **Enable Default Properties**: Activates all properties that have default descriptions, excluding protected or globally ignored fields.

#### All Entity Properties

An expandable list of all discovered entity types, each showing its properties.

-   **Accordion Toggle**: Expands/collapses the list of properties for each entity type.
-   **Bulk Actions**:
    -   **Select All**: Enables all non-protected and non-globally-ignored properties for the specific entity type.
    -   **Deselect All**: Disables all properties (except protected) for the specific entity type.
-   **Property Details**: For each property:
    -   **Enable/Disable Checkbox**: Includes or excludes the property from Pydantic model generation. Protected or globally ignored properties cannot be changed.
    -   **Property Mapping Indicator**: Shows if a property name has been mapped (e.g., from `MyProperty` to `my_property`).
    -   **Property Defined**: Toggles whether the property's description is stored in `data.json`.
    -   **Status Indicator**: Shows if a property is `PROTECTED` (system-reserved), `IGNORED` (globally), has `NAMING` issues, is `ENABLED`, or `DISABLED`.
    -   **Description Input**: Edit the property's description. Can "Load Default" or use "LLM Suggest" with confirmation modal.
    -   **Validation Warnings**: Alerts for protected attributes, globally ignored fields, and naming suggestions, with options to apply suggestions.

## 3. Edge Types

Manage the different kinds of relationships between entities.

### Edge Types Management

-   **Current Edge Types**: Lists all currently defined edge types, along with their property counts.
-   **Edit Description**: Modify the description of a custom edge type.
-   **Delete Edge Type**: Remove a custom edge type.
-   **Add Property**: Add custom properties (name, type, description, required status) to an edge type.
-   **Quick Add Common Types**: Pre-fills common relationship types like `WorksFor`, `Uses`, `Creates`, `MemberOf`, `Manages`, `Contains`.
-   **Add New Edge Type**: Manually add a new custom edge type with a name and description.
-   **LLM Suggest Edge Types**: AI-generated suggestions for edge type descriptions based on your vault content.

### Available Default Edge Types

A list of predefined relationship types with descriptions. You can add these to your custom edge types with a single click or "Add All" unused defaults.

## 4. Edge Mappings

Define the rules for how entities can be connected.

### Edge Type Mappings

This section allows you to rigorously define permissible relationships between different entity types, controlling the structural integrity of your knowledge graph.

-   **Mapping List**: Displays existing mappings (e.g., `Person` → `Project` via `WorksOn` or `Manages`).
-   **Edit Mapping**: Modify the source entity, target entity, and allowed edge types for an existing mapping.
-   **Delete Mapping**: Remove a custom edge mapping.
-   **Quick Add Common Mappings**: Pre-fills common mappings like `Person` → `Technology` (Uses, RelatesTo) or `Entity` → `Entity` (RelatesTo).
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
-   **Generate Complete Ontology**: Comprehensive schema generation including entities, properties, edge types, and valid mappings between them.

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

## Per-Namespace Configuration

Each folder mapping in your namespace settings (configured under **Knowledge Namespacing → Custom Folder Mappings** in plugin settings) supports per-namespace options that control how notes in that namespace are processed and stored. These settings appear on each folder mapping row.

### Custom Extraction Instructions

An optional free-text field that overrides the vault-wide **Global Extraction Instructions** for notes in this namespace only. Use this when a specific folder requires different extraction guidance — for example, telling the LLM to focus only on action items in your Tasks folder, or to extract entities differently for your Journal namespace.

When left empty, the global extraction instructions (set in plugin settings) apply.

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