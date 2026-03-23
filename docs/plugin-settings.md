---
date_created: 2025-09-23T11:21
date_updated: 2026-03-23
---
# MegaMem Plugin Settings

The settings panel has **three tabs**: **General Settings** (core config — database, LLM, sync, servers, MCP tools), **Advanced Settings** (multi-vault, auto-sync, CLI/WebSocket, schema discovery, developer options, updates), and **✦ MegaMem Pro** (license key and content packages).

**General Settings** contains: Python Environment, API Keys, Model Library, LLM Configuration, Database Configuration, Sync Configuration, Knowledge Namespacing, Servers, MCP Tools.

**Advanced Settings** contains: Multi-Vault Mode, Obsidian CLI and WebSocket, Schema Discovery and UI, Auto-Sync, Development Options, Updates.

## ✦ MegaMem Pro Tab

### License Key

Enter your `mm_live_...` API key and click **Validate**. The key is stored in `data.json` and validated against `megamem.endogon.com`.

**States:**
- **Empty** — helper text with link to [endogon.com/stewards](https://endogon.com/stewards)
- **Validating** — input disabled, spinner
- **Valid** — green banner showing plan name, masked key, and expiry ("Active subscription" if on recurring plan) + **Remove Key** button
- **Invalid** — red error message, input stays editable

### Content Packages

Only visible when a valid key is present. Shows one card per entitled package from your plan.

**Each card displays:**
- Package name and description
- Installed version vs. available version
- Status badge: **Not installed** / **Update available (vX.Y.Z)** / **Up to date**
- **Install** or **Update** button (absent when up to date)

On install/update: the plugin fetches a signed download URL from the edge function, downloads the zip, and extracts it to your vault root. `MegaMemPro/Version.md` is the version sentinel.

### Premium Features

Placeholder for upcoming hosted services — currently shows the **Ask Bjørn** coming-soon card.

---

## API Keys

Configure API keys for various AI service providers.

### OpenAI API Key <i data-lucide="check-circle"></i>
- Description: API key for OpenAI services
- Developer Note: Required for OpenAI LLM and embedding models. Fully implemented and tested.

### Anthropic API Key <i data-lucide="check-circle"></i>
- Description: API key for Anthropic services
- Developer Note: Required for Claude models. Fully implemented and tested.

### Google API Key <i data-lucide="check-circle"></i>
- Description: API key for Google services
- Developer Note: Required for Gemini models and Google embeddings. Fully implemented and tested.

### Azure OpenAI API Key <i data-lucide="check-circle"></i>
- Description: API key for Azure OpenAI services
- Developer Note: Required for Azure-hosted OpenAI models. Fully implemented and tested.

### Voyage AI API Key <i data-lucide="check-circle"></i>
- Description: API key for Voyage AI services
- Developer Note: Required for Voyage embedding models. Fully implemented and tested.

### Venice.ai API Key <i data-lucide="alert-triangle"></i>
- Description: API key for Venice.ai services
- Developer Note: Basic API connection implemented but not fully supported yet. Use with caution.

### OpenRouter API Key <i data-lucide="check-circle"></i>
- Description: API key for OpenRouter services
- Developer Note: Required for OpenRouter models and presets. Fully implemented and tested.

### Ollama - Fully Private Local Models <i data-lucide="alert-triangle"></i>
- Description: Run AI models locally on your machine without sending data to external services
- Developer Note: NOT fully working - pending development to support JSON schema for custom entities (works ok with generic entities). Complete local model management with installation, status checking, and model downloads.

#### Actions:
- **Install Ollama** <i data-lucide="download"></i>: Downloads and installs Ollama on your system
- **Refresh Status** <i data-lucide="refresh-cw"></i>: Checks Ollama installation status and available models

### Validate All API Keys <i data-lucide="check-circle"></i>
#### Actions:
- **Validate API Keys** <i data-lucide="shield-check"></i>: Validates all configured API keys without testing models

## Model Library <i data-lucide="check-circle"></i>

Fetch and manage available models from your configured LLM providers. Appears between API Keys and LLM Configuration.

- **Purpose**: Discover models available from each provider's API, curate a personal short-list, and control which models appear in LLM Configuration dropdowns.
- **Developer Note**: Fetched model data is cached in `model-library-cache.json` (separate from `data.json` for performance). Cache TTL is 24 hours.

### Fetch All Models
#### Actions:
- **Fetch All Models** <i data-lucide="download"></i>: Queries all configured providers simultaneously for their current model catalog
- **Clear Cache** <i data-lucide="trash"></i>: Clears the model library cache — next fetch will pull fresh data

### LLM Models / Embedding Models

For each section, select a provider and click **Fetch** to load its model list.

**Capability Filters (OpenRouter only):**

| Filter | Meaning |
|--------|---------|
| 🟢 Graphiti Compatible | Model supports both `structured_outputs` AND `temperature` — works reliably with Graphiti's knowledge extraction pipeline |
| Structured Outputs | Supports `json_schema` response format |
| Tool Use | Supports function calling |
| Vision | Accepts image inputs |
| ZDR | Zero Data Retention — provider does not use your data for training |

> **Important for OpenRouter users**: Always filter by **🟢 Graphiti Compatible** when selecting models for sync. GPT-5/o1/o3 models support structured outputs but reject the `temperature` parameter, causing 404 routing errors with Graphiti's extraction pipeline.

**Model Row Controls:**
- **Checkbox**: Toggle model on/off in your short-list. Enabled models appear in LLM Configuration dropdowns.
- **★ badge**: Recommended by MegaMem (from built-in defaults)
- **Metadata badges**: Context window (e.g. `128K`), dimensions for embeddings, pricing (`$/1M` tokens)

> **Note**: When 11 or more models are in your short-list, the LLM Model selector switches from a dropdown to a searchable text input with keyboard autocomplete (↑↓ Enter Esc).

## LLM Configuration

Configure language model providers and specific models.

### LLM Defaults
#### Actions:
- **Load Defaults** <i data-lucide="download"></i>: Merge recommended defaults into your current settings without overwriting custom entries

### LLM Provider <i data-lucide="check-circle"></i>
- Description: Choose your language model provider
- Options: OpenAI, Anthropic, Google AI, Azure OpenAI, Ollama (Local), Venice.ai, OpenRouter
- Developer Note: All providers implemented with proper model selection and testing.

### LLM Model <i data-lucide="check-circle"></i>
- Description: Primary language model for processing
- Developer Note: Dynamic model loading from provider-specific defaults. When 11+ models are in your Model Library short-list, this becomes a searchable text input with autocomplete. Supports custom models for Ollama.

### LLM Model Small <i data-lucide="check-circle"></i>
- Description: Smaller, faster model for re-ranking operations (optional)
- Developer Note: Used for performance optimization in re-ranking scenarios.

### OpenRouter Preset Slug <i data-lucide="check-circle"></i>
- Description: OpenRouter preset name to use (leave empty to disable preset usage)
- Developer Note: Allows using OpenRouter presets for model management.

#### Actions:
- **Add Default** <i data-lucide="plus"></i>: Add preset model to dropdowns

### Use Preset with Custom Model <i data-lucide="check-circle"></i>
- Description: When enabled, append preset to custom OpenRouter models
- Developer Note: Combines custom models with preset configurations.

### LLM Connection Testing
#### Actions:
- **Test LLM Connection** <i data-lucide="zap"></i>: Test your language model provider configuration

### Embedding Provider <i data-lucide="check-circle"></i>
- Description: Choose your embedding provider (global default — now overridable per-database)
- Options: OpenAI, Google AI, Voyage AI, Ollama (Local)
- Developer Note: Legacy global setting. As of v1.5, embedding is configured per-DB in the Database accordion. This field remains as a fallback for users with a single database.

### Embedding Model <i data-lucide="check-circle"></i>
- Description: Model for generating embeddings (global default)
- Developer Note: Legacy global setting — now overridable per-database in the Databases section.

### Custom LLM Model (Ollama only) <i data-lucide="check-circle"></i>
- Description: Download any Ollama LLM model by name (e.g., llama3.2:3b, codellama:13b)

#### Actions:
- **Download** <i data-lucide="download"></i>: Download this model from Ollama registry

### Custom Embedding Model (Ollama only) <i data-lucide="check-circle"></i>
- Description: Download any Ollama embedding model by name (e.g., nomic-embed-text, mxbai-embed-large)

#### Actions:
- **Download** <i data-lucide="download"></i>: Download this embedding model from Ollama registry

### Embedding Connection Testing
#### Actions:
- **Test Embedding** <i data-lucide="activity"></i>: Test your embedding provider configuration

### Provider Testing
#### Actions:
- **Test Full Pipeline** <i data-lucide="cpu"></i>: Test that your LLM and embedding providers work together correctly with full pipeline testing

### Daemon Management (when enabled)
#### Actions:
- **Reload Sync Daemon** <i data-lucide="rotate-cw"></i>: Restart the sync daemon to apply new provider configuration
- Developer Note: When Daemon is enabled, be sure to click this anytime you change your LLM settings.

## Database Configuration

Configure your graph database backend(s). As of **v1.5**, MegaMem supports multiple named databases simultaneously.

### Databases List <i data-lucide="check-circle"></i>

The "Databases" accordion shows all configured database targets. Each entry collapses to a summary row and expands to a full edit form.

**Summary row shows:** label, type badge (Neo4j / FalkorDB), embedding model, enabled state.

**Expanded edit form fields:**
- **Label**: Human-readable name (e.g., "Personal Neo4j", "Company Graph")
- **Type**: Neo4j or FalkorDB
- **URI / Host / Port**: Connection coordinates
- **Username / Password / Database Name**: Authentication
- **Embedding Provider**: Per-database embedding provider (OpenAI, Google, Voyage, Ollama)
- **Embedding Model**: Per-database embedding model
- **Embedding Dimensions** *(Ollama only)*: Required when using Ollama embeddings

**Actions per entry:**
- **Test Connection**: Verifies connection to this specific database
- **Remove**: Deletes this database configuration

**Add Database:** Opens an inline form to add a new database entry. Fill connection details and embedding config, then save.

> **Note:** Existing single-database configs are auto-migrated to `databases[0]` on first load after upgrading to v1.5. No manual action required.

> **Note:** The Multi-Vault Mode accordion has moved to the **Advanced Settings** tab.

### Sync Identity (Per-Database Icons)

Each named database can have a configurable **Lucide icon** and **icon color** shown in the note ribbon and file explorer:
- **Icon**: Lucide icon name (quick-pick buttons for common choices: brain, database, cloud, server, archive, etc.). Default: `brain`.
- **Icon Color**: Hex color for the icon. Default: `#fea120`.
- **Write Sync Breadcrumb**: When enabled, writes an `mm_sync: {db_label: ISO-timestamp}` entry to note frontmatter after sync — useful for shared Relay folders so partners can see what's been synced.

These settings are available both when **editing an existing database** and when **adding a new database**.

> **Sync State**: As of v1.6, sync state is stored in `sync.db` (SQLite) — a local database inside the plugin directory. This replaces the old `sync.json` file. Migration from sync.json happens automatically on first load.

### Multi-Vault Mode <i data-lucide="check-circle"></i>

> **Located in:** Advanced Settings tab → Multi-Vault Mode accordion.

A dedicated **"Multi-Vault Mode"** accordion controls master/child vault relationships.

**Master Vault toggle:** When enabled, this vault runs the MCP server and shows a "Registered Child Vaults" panel.

**Registered Child Vaults** *(masterVault only)*: Lists vaults registered as children. Each entry shows vault path, linked database, and a Remove button.

**Register Child Vault:** Opens a form to register another Obsidian vault. Vaults are auto-discovered from the OS Obsidian registry (`obsidian.json`) and shown in a dropdown. On registration, the child vault's DB config is read and added to the master's `databases[]` array with `category: 'child-vault'`.

> **Child vault behaviour:** When a vault is registered as a child, its MCP settings show an info notice: "MCP Server is managed by masterVault." MCP is disabled in child mode.

### Database Testing and Setup
#### Actions:
- **Test Connection** <i data-lucide="database"></i>: Verify connection for the selected database configuration
- **Initialize Schema** <i data-lucide="table"></i>: Set up the required Graphiti schema in your database (run after successful connection test)

## Python Environment

**IMPORTANT**: This section appears first in the plugin settings. Python dependencies must be installed before anything will work properly.

### Python Path (Optional) <i data-lucide="check-circle"></i>
- Description: Specify custom Python executable path (leave empty for auto-detection)
- Developer Note: Allows custom Python interpreter specification.

### Python Dependency Management
**Installation Methods:**
- **UV Package Manager (Recommended)**: Default installation method with better cross-platform compatibility for macOS, Windows, and Linux. Handles platform-specific archive formats automatically.
- **System Python**: For advanced users who prefer to use their own Python installation.

#### Actions:
- **Check Dependencies** <i data-lucide="search"></i>: Check if Graphiti Python dependencies are installed
- **Install Dependencies** <i data-lucide="package-plus"></i>: Install Graphiti and required Python packages. The default UV method downloads the uv package manager and uses it to create an isolated Python environment with all required dependencies.

### Python Environment Location <i data-lucide="check-circle"></i>
- Description: The Python virtual environment is **vault-specific** — each Obsidian vault gets its own isolated environment to prevent conflicts between vaults.
- **Windows**: `%LOCALAPPDATA%\MegaMem\python\{vault-name}\venv`
- **macOS**: `~/Library/Application Support/MegaMem/python/{vault-name}/venv`
- **Linux**: `~/.local/share/MegaMem/python/{vault-name}/venv`
- Developer Note: On first upgrade from an older version, the shared venv is automatically copied to the vault-specific location. No manual action required.

## Sync Configuration

Configure per-note sync behavior, extraction settings, and folder exclusions.

> **Auto-sync settings** (schedule, interval, included folders) have moved to **Advanced Settings → Auto-Sync**.

Settings in this accordion (in order):

### Episode Contributor <i data-lucide="check-circle"></i>
- Description: Your name or ID — injected as `mm_contributor` on every synced episode. Useful in shared team databases. Leave blank to omit.

### Global Extraction Instructions <i data-lucide="check-circle"></i>
- Description: Free-text instructions injected into Graphiti's extraction prompts for all notes. Guides the LLM on what to extract, what to ignore, or how to interpret your vault's content. Can be overridden per namespace in Custom Folder Mappings.

### Wikilink Extraction Hints <i data-lucide="check-circle"></i>
- Description: When enabled, `[[wikilinks]]` found in the note body are injected as entity hints in the LLM extraction instructions. Default: on.

### Property Inclusion Mode <i data-lucide="check-circle"></i>
- Description: Controls which frontmatter properties are included in the episode body.
  - **Permissive (default)**: All frontmatter fields except Globally Ignored Fields
  - **Strict**: Only properties enabled in ontology.json for the note's entity type (requires Custom Ontologies)

### Excluded Folders <i data-lucide="check-circle"></i>
- Description: Folders to exclude from sync (e.g., .obsidian, .trash).
- Developer Note: Dynamic folder exclusion management.

#### Actions:
- **Add Folder** <i data-lucide="folder-plus"></i>: Add a new folder to exclude from sync
- **Delete** <i data-lucide="x"></i>: Remove folder from exclusion list (per folder)

### Globally Ignored Fields <i data-lucide="check-circle"></i>
- Description: YAML frontmatter fields to exclude from the episode body sent to Graphiti. Default: `cssclass`, `mm_uid`, `mm_sync`. These fields are now actually stripped from the episode body (was silently broken in earlier versions).
- Developer Note: Filters happen in `sync.py` Stage 3 before YAML serialization.

#### Actions:
- **Add Field** <i data-lucide="plus"></i>: Add a new field to ignore globally
- **Delete** <i data-lucide="x"></i>: Remove field from ignore list (per field)

### Property Inclusion Mode <i data-lucide="check-circle"></i>
- Description: Controls which frontmatter properties are included in the episode body sent to Graphiti.
  - **Permissive (default)**: All frontmatter fields except `Globally Ignored Fields`
  - **Strict**: Only properties that are enabled/checked in ontology.json for the note's entity type. Falls back to Permissive if the note's type has no ontology entry. Requires Custom Ontologies to be enabled.

### Wikilink Extraction Hints <i data-lucide="check-circle"></i>
- Description: When enabled, `[[wikilinks]]` found in the note body are injected as entity hints in the LLM extraction instructions. Obsidian wikilinks are the strongest entity signal available — this toggle ensures the LLM treats them as confirmed knowledge graph references. Default: on.

### Episode Contributor <i data-lucide="check-circle"></i>
- Description: Your name or ID — injected as `mm_contributor` in every episode created by this vault. Useful in shared team databases to track who contributed each piece of knowledge. Applied to Obsidian note syncs, `add_memory`, and `add_conversation_memory`. Leave blank to omit the field.

## Knowledge Namespacing

Configure how knowledge is organized in the graph database.

### Use Custom Ontology <i data-lucide="check-circle"></i>
- Description: Enable custom entity types with pre-existing Pydantic models. When disabled, uses generic text episodes.
- Developer Note: Controls entity type customization level.

### Namespace Strategy <i data-lucide="check-circle"></i>
- Description: Primary strategy for organizing knowledge in the graph
- Options: Vault Name, Folder Path, Property Value, Custom Value
- Developer Note: Intelligent preset controller for namespace organization.

### Default Namespace <i data-lucide="check-circle"></i>
- Description: Default namespace when strategy is "custom" or when other strategies fail
- Developer Note: Fallback namespace configuration.

### Global Extraction Instructions <i data-lucide="check-circle"></i>
- Description: Free-text instructions injected into Graphiti's extraction prompts for all notes. Use this to guide the LLM on what to extract, what to ignore, or how to interpret your vault's content.
- Developer Note: Applies globally to all synced notes. Can be overridden per namespace in Custom Folder Mappings.

### Enable Folder Namespacing <i data-lucide="check-circle"></i>
- Description: Use top-level folder names as namespaces. Subfolders are not supported.
- Developer Note: Top-level folder-based namespace generation.

### Custom Folder Mappings <i data-lucide="check-circle"></i>
- Description: Map specific folders to custom group_id namespaces. Leave empty to use automatic folder names. Each mapping row also supports per-namespace extraction instructions, saga grouping, and a saga property key.
- Developer Note: Advanced folder-to-namespace mapping with auto-population.

**Per-mapping options (available on each folder mapping row):**
- **Custom Extraction Instructions**: Override the global extraction instructions for this namespace only. When left empty, the vault-wide Global Extraction Instructions apply.
- **Saga Grouping**: How episodes from this namespace are grouped into sagas. Options: `By Note Type (default)`, `Single Saga for namespace`, `No saga grouping`, `Custom frontmatter property`.
- **Saga Property Key**: *(Visible when Saga Grouping = "Custom frontmatter property")* The frontmatter key whose value is used as the saga name.

#### Actions:
- **Add Folder Mapping** <i data-lucide="folder-plus"></i>: Add a new folder-to-namespace mapping
- **Delete** <i data-lucide="x"></i>: Remove folder mapping (per mapping)

### Enable Property Namespacing <i data-lucide="check-circle"></i>
- Description: Use `mm_group_id` frontmatter property as namespace when available. (`g_group_id` is deprecated — still supported with a warning log, but rename to `mm_group_id`.)
- Developer Note: Property-based namespace detection.

### Namespace Discovery
#### Actions:
- **Generate** <i data-lucide="refresh-cw"></i>: Scan the vault and generate the list of available namespaces based on the settings above

### Enable Multi-Vault Mode <i data-lucide="wrench"></i>
- Description: Enable advanced features for managing multiple Obsidian vaults
- Developer Note: Multi-vault features planned for future release.

### Current Vault Priority <i data-lucide="wrench"></i>
- Description: Priority level for this vault in multi-vault scenarios (higher numbers = higher priority)
- Developer Note: Multi-vault priority management (planned feature).

### Vault Configurations <i data-lucide="wrench"></i>
- Description: Currently tracking vault configurations
- Developer Note: Multi-vault management features planned for future release.

#### Actions:
- **Manage Vaults** <i data-lucide="settings"></i>: Manage vault configurations (disabled - planned feature)

## Servers

MCP server configuration. The Servers accordion contains two sub-accordions.

> **Obsidian CLI and WebSocket settings** have moved to **Advanced Settings → Obsidian CLI and WebSocket**.

### STDIO MCP Server _(sub-accordion)_

STDIO mode connects Claude Desktop and other local MCP clients. Launch via your MCP client config — no plugin-side start/stop required.

- **Enable STDIO Server** — Toggle STDIO mode on/off. Disable to run in HTTP-only mode. Default: on.
- **Generate MCP Config** — Generate the `mcpServers` config block for Claude Desktop / local clients.

### Streamable HTTP Access _(sub-accordion)_ <i data-lucide="check-circle"></i>

Opt-in HTTP transport (MCP spec 2025-03-26). Enables Roo Code, Cursor, Claude Code, VS Code, NemoClaw, and any HTTP-capable MCP client to connect directly — without Claude Desktop as a relay. Remote access via Tailscale is supported.

#### Settings:
- **Enable Streamable HTTP** — Toggle to start the dedicated HTTP MCP process. Restart after toggling.
- **HTTP Port** — Default `3838`.
- **HTTP Server** — Start / Stop buttons for manual control.

#### Token Profiles (Scoped Access) <i data-lucide="check-circle"></i>

Each profile is a collapsible accordion. The **Admin** profile (always first) has full access. Scoped profiles restrict access for public clients.

**Per-Profile Fields:**
- **Label** — Friendly name (e.g., "Endo"). The MCP server name is auto-generated as `megamem-{slug}` (e.g., `megamem-endo`).
- **Endpoint URL** — Base URL for this profile. Leave blank for `http://localhost:{port}/mcp`. Enter a full URL for Tailscale remote access (e.g., `https://your-host.ts.net/mcp/`).
- **Bearer Token** — Auto-generated. Copy or Regenerate. Regenerating live-updates all Copy Config buttons.
- **Copy Config buttons** — One button per supported client (Roo Code, Claude Desktop, Claude Code, Cursor, VS Code, NemoClaw). Each copies the correctly formatted config for that client.
- **Access Restrictions** *(scoped profiles only)*:
  - **Allowed Tools** — Checkboxes per MCP tool.
  - **Allowed Group IDs** — Comma-separated namespace IDs. Empty = no restriction.
  - **Allowed Databases** — Checkboxes per configured database. Unchecked all = all allowed.
  - **Allowed Vaults** — Checkboxes per registered vault. Unchecked all = all allowed.

#### Copy Config Formats:

| Client | Format |
|--------|--------|
| **Roo Code** | `streamable-http` type JSON |
| **Claude Desktop** | `npx mcp-remote` command |
| **Claude Code** | `claude mcp add` CLI command |
| **Cursor** | `streamable-http` type JSON |
| **VS Code** | `servers` key, `http` type JSON |
| **NemoClaw** | `baseUrl` + `headers` JSON |

#### Actions:
- **+ Add Profile** — Create a new scoped token profile
- **Delete** *(per profile)* — Remove a profile
- **Regenerate** *(per profile)* — Rotate the token (invalidates the old one immediately)

### Current Instances _(below sub-accordions)_

Shows all active MCP processes (STDIO and HTTP) with their PIDs and ownership status.

- **Kill Orphans** — Scan for and terminate orphaned MCP processes from previous sessions.

---

## Advanced Settings Tab

The **Advanced Settings** tab contains the following accordions:

---

### Multi-Vault Mode

> See [Database Configuration → Multi-Vault Mode](#multi-vault-mode) above for full documentation.

---

### Obsidian CLI and WebSocket

CLI and WebSocket configuration for MCP file operations.

#### Obsidian CLI File Tools (Recommended) <i data-lucide="check-circle"></i>
- **Use Obsidian CLI** — Replace WebSocket file operations with stateless CLI subprocess calls (Obsidian 1.12.4+ required). Eliminates connection errors and startup races. Recommended for all users.
- Requires Obsidian 1.12.4+ installer + CLI registered in PATH (`Settings → General → CLI → Register`).

#### Shared WebSocket Server <i data-lucide="check-circle"></i>
- **Enable WebSocket Server** — Required for MCP file tools when CLI mode is off.
- **WebSocket Port** — Read-only; managed automatically by MCP processes.
- **Authentication Token** — Auto-generated; copy for manual configuration.

---

### Schema Discovery and UI <i data-lucide="settings"></i>

Advanced schema and UI configuration options. Many are under development.

#### Schema Discovery Options
- **Auto-discover Schemas** — Automatically scan vault for schema patterns *(planned)*
- **Validate Naming Conventions** — Check property names against Graphiti best practices *(planned)*
- **Suggest Property Descriptions** — Auto-generate descriptions for common property names *(planned)*
- **Protected Attribute Warnings** — Show warnings for Graphiti protected attribute names *(planned)*

#### UI Preferences
- **Show Sync Status** — Display sync status icons in the note ribbon (per-DB colored icons)
- **Show Notifications** — Display notifications for sync operations

---

### Auto-Sync <i data-lucide="alert-triangle"></i>

> **WARNING**: Auto-sync is functional but not thoroughly tested. Use at your own risk.

- **Automatically sync notes at scheduled intervals** — Enable auto-sync on save or interval
- **Sync Options** — New notes only, or new + updated
- **Sync Interval** — Minutes between auto-sync runs (0 = disabled)
- **Included Folders** — Folders to include in auto-sync. Leave empty to include all.

#### Actions:
- **Add Folder** / **Delete** — Manage the folder inclusion list

---

### Development Options

Debugging, experimental features, and plugin management.

- **View Logs** — Open the plugin logs directory
- **Max Retry Attempts** — Maximum retry attempts for failed operations
- **Connection Timeout** — Connection timeout in seconds
- **Debug Logging** — Enable detailed logging for troubleshooting
- **Experimental Daemon Mode** — Keep a Python process warm between syncs for faster consecutive processing
- **Load Daemon on Launch** — Start daemon at plugin load (requires Daemon Mode)
- **Log Performance** — Enable detailed timing analysis
- **Export Settings** — Export current settings to a file
- **Import Settings** — Import settings from a file
- **Reset to Defaults** — Reset all settings to defaults (⚠️ destructive)

---

## Updates

Located at the bottom of MegaMem settings.

### Check for Updates
Manually check for plugin and Python component updates from GitHub. The plugin also performs this check automatically 3 seconds after loading.

- If Python components (`graphiti_bridge` or `mcp-server`) are missing or outdated, an install dialog will appear
- Click **Install / Update Components** to download and install the latest `python-components.zip` from GitHub releases
- If everything is current, you'll see: "MegaMem is up to date!"

#### Actions:
- **Check for Updates** <i data-lucide="refresh-cw"></i>: Fetch the latest release from GitHub and compare against installed component versions

## Development Options

Experimental features and development tools.

### Show Development Indicators <i data-lucide="check-circle"></i>
- Description: Display visual indicators showing which features are implemented vs. placeholder/TODO
- Developer Note: Visual development status indicators throughout the UI.

### Experimental Daemon Mode <i data-lucide="check-circle"></i>
- Description: Keeps a Python process warm between syncs for faster consecutive note processing
- Developer Note: Significant performance improvement for consecutive sync operations.

### Load Daemon on Launch <i data-lucide="check-circle"></i>
- Description: Start Python daemon when plugin loads to eliminate first-sync delay (requires Experimental Daemon Mode)
- Developer Note: Preloads daemon for immediate sync availability.

### Log Performance <i data-lucide="check-circle"></i>
- Description: Enable detailed timing analysis for sync performance debugging
- Developer Note: Comprehensive performance timing and analysis.

## Status Legend

- <i data-lucide="check-circle"></i> Implemented: Feature is fully functional and tested
- <i data-lucide="clock"></i> Partial: UI complete but backend implementation pending
- <i data-lucide="alert-triangle"></i> Under Development: Basic functionality but not fully supported
- <i data-lucide="wrench"></i> Todo: Planned feature not yet implemented

## Provider-Specific Settings

Additional settings that appear based on your provider selection:

### Azure OpenAI Settings
- Azure Endpoint: Your Azure OpenAI endpoint URL
- Azure API Version: Azure OpenAI API version

### Ollama Settings
- Ollama Base URL: Ollama server base URL (used for both LLM and embedding)
- Ollama Embedding Dimension: Dimension size for Ollama embeddings (typically 768)