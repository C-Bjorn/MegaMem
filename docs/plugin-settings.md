---
date_created: 2025-09-23T11:21
date_updated: 2025-09-28T11:36
---
# MegaMem Plugin Settings

This document provides a comprehensive overview of all available settings in the MegaMem plugin. Settings are organized into logical sections for easy navigation.

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
- Developer Note: Dynamic model loading from provider-specific defaults. Supports custom models for Ollama.

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
- Description: Choose your embedding provider
- Options: OpenAI, Google AI, Voyage AI, Ollama (Local)
- Developer Note: All providers implemented with automatic vault registry updates. **IMPORTANT**: Each database can only support one embedder config. If you change it later - all things will break. *In the future, MegaMem plans to support multiple databases with multiple configs.*

### Embedding Model <i data-lucide="check-circle"></i>
- Description: Model for generating embeddings
- Developer Note: Includes embedding model change detection and database conflict warnings.

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

### Cross-Encoder Provider <i data-lucide="check-circle"></i>
- Description: Choose your cross-encoder/reranker provider for improved search ranking
- Options: None - Disable reranking, OpenAI Reranker, BGE Reranker (Local), Gemini Reranker
- Developer Note: Improves search result quality through reranking. Currently the only fully Private Cross-Encoder is "BGE Reranker" (from huggingface) which is not configurable. *In the future, MegaMem will support selecting multiple models. Also, this can add a lot of time to each sync, so we recommend enabling "Experimental Daemon Mode" in Development Options when running BGE.*

### Cross-Encoder Model <i data-lucide="check-circle"></i>
- Description: Specific model for cross-encoding/reranking operations
- Developer Note: Conditionally visible based on provider selection.

### Provider Testing
#### Actions:
- **Test Full Pipeline** <i data-lucide="cpu"></i>: Test that your LLM and embedding providers work together correctly with full pipeline testing

### Daemon Management (when enabled)
#### Actions:
- **Reload Sync Daemon** <i data-lucide="rotate-cw"></i>: Restart the sync daemon to apply new provider configuration
- Developer Note: When Daemon is enabled, be sure to click this anytime you change your LLM settings.

## Database Configuration

Configure your graph database backend.

### Database Type <i data-lucide="check-circle"></i>
- Description: Choose your graph database backend
- Options: Neo4j, FalkorDB
- Developer Note: Neo4j fully tested with latest. FalkorDB - not tested in a while, proceed with caution.

### Neo4j URI <i data-lucide="check-circle"></i>
- Description: Neo4j connection URI (e.g., bolt://localhost:7687)
- Developer Note: Standard Neo4j bolt protocol connection.

### Neo4j Username <i data-lucide="check-circle"></i>
- Description: Neo4j database username
- Developer Note: Authentication for Neo4j database access.

### Neo4j Password <i data-lucide="check-circle"></i>
- Description: Neo4j database password
- Developer Note: Secure password field for Neo4j authentication.

### Neo4j Database Name <i data-lucide="check-circle"></i>
- Description: Name of the Neo4j database to use
- Developer Note: Use the default: "neo4j". Currently there is a bug in graphiti wherein custom db names break things.

### FalkorDB Host <i data-lucide="check-circle"></i>
- Description: FalkorDB host address
- Developer Note: Redis-compatible FalkorDB connection.

### FalkorDB Port <i data-lucide="check-circle"></i>
- Description: FalkorDB port number
- Developer Note: Configurable port with validation (1-65535).

### FalkorDB Username (Optional) <i data-lucide="check-circle"></i>
- Description: FalkorDB username (leave empty if not using authentication)
- Developer Note: Optional authentication for secured FalkorDB instances.

### FalkorDB Password (Optional) <i data-lucide="check-circle"></i>
- Description: FalkorDB password (leave empty if not using authentication)
- Developer Note: Optional secure password field.

### FalkorDB Database Name <i data-lucide="check-circle"></i>
- Description: Name of the FalkorDB database to use
- Developer Note: Database name configuration for FalkorDB.

### Database Testing and Setup
#### Actions:
- **Test Connection** <i data-lucide="database"></i>: Verify your database connection settings
- **Initialize Schema** <i data-lucide="table"></i>: Set up the required Graphiti schema in your database (run this after successful connection test)

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

## Sync Configuration <i data-lucide="alert-triangle"></i>

Configure automatic synchronization behavior. **WARNING**: This works, but we HIGHLY RECOMMEND NOT USING IT. It is not thoroughly tested, conflicts may arise between Included & Excluded folders and time intervals. Much work remains to be done.

### Automatically sync notes at scheduled intervals <i data-lucide="clock"></i>
- Description: Automatically sync notes when they are saved or at regular intervals
- Developer Note: Enhanced UI complete, sync engine needs update.

### Sync Options <i data-lucide="clock"></i>
- Description: Choose which notes to include in automatic sync operations
- Options: New notes only, New and updated notes
- Developer Note: UI implementation complete.

### Sync Interval <i data-lucide="clock"></i>
- Description: Automatic sync interval in minutes (0 to disable)
- Developer Note: UI complete, sync engine not implemented.

### Included Folders <i data-lucide="check-circle"></i>
- Description: Folders to include in sync. Leave empty to include all folders.
- Developer Note: Dynamic folder management with FolderSuggest integration.

#### Actions:
- **Add Folder** <i data-lucide="folder-plus"></i>: Add a new folder to include in sync
- **Delete** <i data-lucide="x"></i>: Remove folder from inclusion list (per folder)

### Excluded Folders <i data-lucide="check-circle"></i>
- Description: Folders to exclude from sync (e.g., .obsidian, .trash).
- Developer Note: Dynamic folder exclusion management.

#### Actions:
- **Add Folder** <i data-lucide="folder-plus"></i>: Add a new folder to exclude from sync
- **Delete** <i data-lucide="x"></i>: Remove folder from exclusion list (per folder)

### Globally Ignored Fields <i data-lucide="check-circle"></i>
- Description: YAML frontmatter fields to ignore globally across all notes.
- Developer Note: Prevents specific frontmatter fields from being synced.

#### Actions:
- **Add Field** <i data-lucide="plus"></i>: Add a new field to ignore globally
- **Delete** <i data-lucide="x"></i>: Remove field from ignore list (per field)

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

### Enable Folder Namespacing <i data-lucide="check-circle"></i>
- Description: Use top-level folder names as namespaces. Subfolders are not supported.
- Developer Note: Top-level folder-based namespace generation.

### Custom Folder Mappings <i data-lucide="check-circle"></i>
- Description: Map specific folders to custom group_id namespaces. Leave empty to use automatic folder names.
- Developer Note: Advanced folder-to-namespace mapping with auto-population.

#### Actions:
- **Add Folder Mapping** <i data-lucide="folder-plus"></i>: Add a new folder-to-namespace mapping
- **Delete** <i data-lucide="x"></i>: Remove folder mapping (per mapping)

### Enable Property Namespacing <i data-lucide="check-circle"></i>
- Description: Use g_group_id frontmatter property as namespace when available
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

WebSocket and MCP server configuration.

### WebSocket Port <i data-lucide="check-circle"></i>
- Description: Port number for the shared WebSocket server (configured via MCP)
- Developer Note: Managed automatically by MCP processes.

### Authentication Token <i data-lucide="check-circle"></i>
- Description: Authentication token for secure WebSocket connections (managed by MCP)
- Developer Note: Auto-generated secure token for WebSocket authentication.

#### Actions:
- **Copy** <i data-lucide="copy"></i>: Copy authentication token to clipboard

### MCP Configuration
#### Actions:
- **Generate Config** <i data-lucide="file-text"></i>: Generate configuration for MCP clients to connect to the MCP server

## Advanced Settings <i data-lucide="settings"></i>

Advanced configuration options for debugging and performance. Many of the settings here are under development, use at your own risk.

### Debug Logging <i data-lucide="check-circle"></i>
- Description: Enable detailed logging for troubleshooting
- Developer Note: Comprehensive debug logging system with immediate state updates. Debug logging is less verbose by default to reduce log file size.

### Log Management
#### Actions:
- **View Logs** <i data-lucide="file-text"></i>: Open the plugin logs directory

### Manual Testing
#### Actions:
- **Select and Sync Note** <i data-lucide="file-plus"></i>: Sync a single note manually to test the connection and process

### Performance Metrics <i data-lucide="wrench"></i>
- Description: Track and display performance metrics
- Developer Note: Metrics collection not implemented.

### Max Retry Attempts <i data-lucide="check-circle"></i>
- Description: Maximum number of retry attempts for failed operations
- Developer Note: Configurable retry logic for robust operation.

### Connection Timeout <i data-lucide="check-circle"></i>
- Description: Connection timeout in seconds
- Developer Note: Configurable timeout for all connection operations.

### Auto-discover Schemas <i data-lucide="wrench"></i>
- Description: Automatically scan vault for schema patterns
- Developer Note: Schema discovery not implemented.

### Validate Naming Conventions <i data-lucide="wrench"></i>
- Description: Check property names against Graphiti best practices
- Developer Note: Validation not implemented.

### Suggest Property Descriptions <i data-lucide="wrench"></i>
- Description: Auto-generate descriptions for common property names
- Developer Note: AI suggestions not implemented.

### Protected Attribute Warnings <i data-lucide="wrench"></i>
- Description: Show warnings for Graphiti protected attribute names
- Developer Note: Warning system not implemented.

### Show Sync Status <i data-lucide="clock"></i>
- Description: Display sync status in the status bar
- Developer Note: UI setting complete, status bar integration not implemented.

### Show Notifications <i data-lucide="clock"></i>
- Description: Display notifications for sync operations
- Developer Note: UI setting complete, sync notifications not implemented.

### Compact Mode <i data-lucide="wrench"></i>
- Description: Use compact UI layout to save space
- Developer Note: Compact UI styling not implemented.

## Actions

Plugin configuration management.

#### Actions:
- **Export Settings** <i data-lucide="download"></i>: Export your current settings to a file
- **Import Settings** <i data-lucide="upload"></i>: Import settings from a file
- **Reset to Defaults** <i data-lucide="rotate-ccw"></i>: Reset all settings to their default values

## Development Options

Experimental features and development tools.

### Show Development Indicators <i data-lucide="check-circle"></i>
- Description: Display visual indicators showing which features are implemented vs. placeholder/TODO
- Developer Note: Visual development status indicators throughout the UI.

### Experimental Daemon Mode <i data-lucide="check-circle"></i>
- Description: Use persistent Python daemon to eliminate BGE model loading overhead (reduces sync time by ~60%)
- Developer Note: Significant performance improvement for sync operations.

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