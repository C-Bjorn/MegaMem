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

This section provides tools (currently under development) for leveraging Language Models to automatically generate and suggest entity descriptions based on your vault content.

-   **Generate Entity Descriptions**: (Coming Soon) Use AI to draft descriptions for your entity types.
-   **Suggest Property Descriptions**: (Coming Soon) Enables AI to suggest property definitions.
-   **Generate Complete Ontology**: (Coming Soon) Automatically generates a comprehensive schema.
-   **Load All Default Entity Descriptions**: Populates descriptions for all discovered entity types using predefined defaults, if available.

<i data-lucide="alert-triangle"></i> LLM Integration Coming Soon
The LLM integration features within the Ontology Manager are currently under active development. While buttons are present, their full functionality with AI suggestions is not yet available.
:::

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
-   **LLM Suggest**: (Coming Soon) Provides AI-generated description suggestions.
-   **Details**: Shows the number of files associated with the entity type, the count of its properties, and its individual compliance score.

## 2. Properties

This tab lists all properties associated with your entity types, allowing for detailed configuration.

### LLM Automatic Property Descriptions

Similar to Entity Types, this section (under development) will provide AI-driven assistance for property management.

-   **Generate All Property Descriptions**: (Coming Soon) Auto-generate descriptions for all entity properties.
-   **Suggest Property Types**: (Coming Soon) AI-assisted suggestions for property field types.
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
    -   **Description Input**: Edit the property's description. Can "Load Default" or use "LLM Suggest" (coming soon).
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