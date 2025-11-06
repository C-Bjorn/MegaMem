"""
Configuration handling for Graphiti Bridge

Handles configuration validation, environment variables, and provider-specific settings.
"""

import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class BridgeConfig:
    """Configuration container for Graphiti Bridge"""

    # Required LLM Configuration
    llm_provider: str
    llm_model: str

    # Required Embedder Configuration
    embedder_provider: str
    embedding_model: str

    # Required Database Configuration
    database_type: str
    database_url: str
    database_username: Optional[str]  # FalkorDB supports no authentication
    database_password: Optional[str]  # FalkorDB supports no authentication
    database_name: str

    # Required Processing Configuration
    notes: List[str]

    # Optional Processing Configuration (dynamic vs static model loading)
    # For backward compatibility with static models
    models_path: Optional[str] = None
    vault_path: Optional[str] = None   # For new dynamic model loading approach

    # Provider-specific API keys
    api_keys: Optional[Dict[str, str]] = None

    # Legacy single API key fields (for backward compatibility)
    llm_api_key: Optional[str] = None
    embedder_api_key: Optional[str] = None

    # Optional LLM Configuration
    llm_small_model: Optional[str] = None

    # Optional Cross-Encoder Configuration
    cross_encoder_client: Optional[str] = None
    cross_encoder_model: Optional[str] = None

    # Optional Provider-specific settings
    azure_endpoint: Optional[str] = None
    azure_api_version: Optional[str] = None
    ollama_base_url: Optional[str] = None
    openrouter_preset_slug: Optional[str] = None
    openrouter_use_preset_with_custom_model: bool = False

    # Optional Processing settings
    batch_size: int = 10
    max_retries: int = 3
    timeout: int = 30
    debug: bool = False

    # Episode and Ontology Configuration
    use_custom_ontology: bool = False
    use_bulk_sync: bool = False
    default_namespace: str = "vault"
    enable_folder_namespacing: bool = False
    enable_property_namespacing: bool = False
    namespace_strategy: str = "vault"  # 'vault', 'folder', 'property', 'custom'
    folder_namespace_mappings: Optional[List[Dict[str, str]]] = None

    # Episode source description
    source_description: Optional[str] = None

    # Optional override of namespace group_id provided by TS side (pass-through like source_description)
    group_id: Optional[str] = None
    # WebSocket Configuration for Extended MCP
    ws_port: int = 8765
    ws_auth_token: str = ""
    graph_view_id: str = "vault"

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'BridgeConfig':
        """Create BridgeConfig from dictionary (JSON input)"""

        # Handle both new (snake_case) and old (camelCase) field naming
        return cls(
            # LLM Configuration
            llm_provider=config_dict.get(
                'llm_provider') or config_dict.get('llmProvider', 'openai'),
            llm_model=config_dict.get(
                'llm_model') or config_dict.get('llmModel', 'gpt-4o'),
            llm_small_model=config_dict.get(
                'llm_small_model') or config_dict.get('llmSmallModel'),

            # Cross-Encoder Configuration
            cross_encoder_client=config_dict.get(
                'cross_encoder_client') or config_dict.get('crossEncoderClient'),
            cross_encoder_model=config_dict.get(
                'cross_encoder_model') or config_dict.get('crossEncoderModel'),

            # Embedder Configuration
            embedder_provider=config_dict.get(
                'embedder_provider') or config_dict.get('embedderProvider', 'openai'),
            embedding_model=config_dict.get('embedding_model') or config_dict.get(
                'embeddingModel', 'text-embedding-3-small'),

            # Database Configuration
            database_type=config_dict.get(
                'database_type') or config_dict.get('databaseType', 'neo4j'),
            database_url=cls._get_database_url_from_config(config_dict),
            database_username=cls._get_database_field(
                config_dict, 'database_username', 'databaseUsername', 'neo4j'),
            database_password=cls._get_database_field(
                config_dict, 'database_password', 'databasePassword', ''),
            database_name=config_dict.get(
                'database_name') or config_dict.get('databaseName', 'neo4j'),

            # Provider-specific API keys (new format)
            api_keys=config_dict.get('api_keys'),

            # Legacy API keys (backward compatibility)
            llm_api_key=config_dict.get(
                'llm_api_key') or config_dict.get('llmApiKey', ''),
            embedder_api_key=config_dict.get(
                'embedder_api_key') or config_dict.get('embedderApiKey'),

            # Provider-specific settings
            azure_endpoint=config_dict.get(
                'azure_endpoint') or config_dict.get('azureEndpoint'),
            azure_api_version=config_dict.get(
                'azure_api_version') or config_dict.get('azureApiVersion'),
            ollama_base_url=config_dict.get(
                'ollama_base_url') or config_dict.get('ollamaBaseUrl'),
            openrouter_preset_slug=config_dict.get(
                'openrouter_preset_slug') or config_dict.get('openrouterPresetSlug'),
            openrouter_use_preset_with_custom_model=config_dict.get(
                'openrouter_use_preset_with_custom_model') or config_dict.get('openrouterUsePresetWithCustomModel', False),

            # Processing Configuration
            models_path=config_dict.get(
                'models_path') or config_dict.get('modelsPath'),
            vault_path=config_dict.get(
                'vault_path') or config_dict.get('vaultPath'),
            notes=config_dict.get('notes', []),

            # Optional settings
            batch_size=config_dict.get(
                'batch_size') or config_dict.get('batchSize', 10),
            max_retries=config_dict.get(
                'max_retries') or config_dict.get('maxRetries', 3),
            timeout=config_dict.get('timeout', 30),
            debug=config_dict.get('debug') or config_dict.get(
                'debugMode', False),

            # Episode and Ontology Configuration
            use_custom_ontology=config_dict.get(
                'use_custom_ontology') or config_dict.get('useCustomOntology', False),
            use_bulk_sync=config_dict.get(
                'use_bulk_sync') or config_dict.get('useBulkSync', False),
            default_namespace=config_dict.get(
                'default_namespace') or config_dict.get('defaultNamespace', 'vault'),
            enable_folder_namespacing=config_dict.get(
                'enable_folder_namespacing') or config_dict.get('enableFolderNamespacing', False),
            enable_property_namespacing=config_dict.get(
                'enable_property_namespacing') or config_dict.get('enablePropertyNamespacing', False),
            namespace_strategy=config_dict.get(
                'namespace_strategy') or config_dict.get('namespaceStrategy', 'vault'),
            folder_namespace_mappings=config_dict.get(
                'folder_namespace_mappings') or config_dict.get('folderNamespaceMappings', []),

            # Episode source description
            source_description=config_dict.get(
                'source_description') or config_dict.get('sourceDescription'),

            # Optional namespace override (mirrors source_description pass-through)
            group_id=config_dict.get('group_id') or config_dict.get('groupId'),

            # WebSocket Configuration for Extended MCP
            ws_port=config_dict.get(
                'ws_port') or config_dict.get('wsPort', 8765),
            ws_auth_token=config_dict.get(
                'ws_auth_token') or config_dict.get('wsAuthToken', ''),
            graph_view_id=config_dict.get('graph_view_id') or config_dict.get(
                'graphViewId') or config_dict.get('defaultNamespace', 'vault')
        )

    @classmethod
    def _get_database_field(cls, config_dict: Dict[str, Any], snake_key: str, camel_key: str, default_value: str) -> Optional[str]:
        """Get database field with proper None handling for FalkorDB"""
        # Check snake_case first
        if snake_key in config_dict:
            value = config_dict[snake_key]
            # For FalkorDB, None values should remain None (no authentication)
            if value is None:
                return None
            # Empty string should use default for Neo4j compatibility
            return value if value else default_value

        # Check camelCase fallback
        if camel_key in config_dict:
            value = config_dict[camel_key]
            if value is None:
                return None
            return value if value else default_value

        # Return default if neither key exists
        return default_value

    @classmethod
    def _get_database_url_from_config(cls, config_dict: Dict[str, Any]) -> str:
        """
        Get database URL with priority handling:
        1. Direct databaseUrl in config
        2. Database-specific configuration (Neo4j: uri, FalkorDB: host+port)
        3. Fallback to default URL
        """
        # @vessel-protocol:Heimdall governs:validation context:Database URL configuration priority resolution
        # @inter-dependencies: BridgeConfig.from_dict, database connection setup
        # @purpose: Ensure proper database URL resolution from plugin settings with fallback handling
        # @result: Sync process uses correct database URL from plugin configuration instead of hardcoded defaults
        # @signed: C.Bjørn

        # Priority 1: Direct databaseUrl (highest priority)
        direct_url = config_dict.get(
            'databaseUrl') or config_dict.get('database_url')
        if direct_url:
            return direct_url

        # Priority 2: Database-specific configuration based on type
        database_type = config_dict.get(
            'database_type') or config_dict.get('databaseType', 'neo4j')
        database_configs = config_dict.get('databaseConfigs', {})

        if database_type == 'neo4j' and 'neo4j' in database_configs:
            neo4j_config = database_configs['neo4j']
            neo4j_uri = neo4j_config.get('uri')
            if neo4j_uri:
                return neo4j_uri
        elif database_type == 'falkordb' and 'falkordb' in database_configs:
            falkor_config = database_configs['falkordb']
            host = falkor_config.get('host', 'localhost')
            port = falkor_config.get('port', 6379)
            return f"falkor://{host}:{port}"

        # Priority 3: Fallback defaults based on database type
        if database_type == 'falkordb':
            return "falkor://localhost:6379"
        else:  # neo4j default
            return "bolt://localhost:7687"

        # @vessel-close:Heimdall

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []

        # Required fields
        # LLM API key is NOT required for Ollama provider
        if self.llm_provider != 'ollama' and not self.get_effective_llm_api_key():
            errors.append("LLM API key is required")

        if not self.llm_model:
            errors.append("LLM model is required")

        if not self.embedding_model:
            errors.append("Embedding model is required")

        if not self.database_url:
            errors.append("Database URL is required")

        if not self.database_password and self.database_type == 'neo4j':
            errors.append("Database password is required for Neo4j")

        # NEW DYNAMIC VALIDATION: Either models_path OR vault_path is required
        if not self.models_path and not self.vault_path:
            errors.append(
                "Either models_path (static) or vault_path (dynamic) is required")

        if not self.notes:
            errors.append("At least one note is required")

        # Provider-specific validation
        if self.llm_provider == 'azure':
            if not self.azure_endpoint:
                errors.append("Azure endpoint is required for Azure provider")
            if not self.azure_api_version:
                errors.append(
                    "Azure API version is required for Azure provider")

        if self.llm_provider == 'ollama':
            if not self.ollama_base_url:
                errors.append(
                    "Ollama base URL is required for Ollama provider")

        # Path validation - check whichever path is provided
        if self.models_path and not Path(self.models_path).exists():
            errors.append(f"Models path does not exist: {self.models_path}")

        if self.vault_path and not Path(self.vault_path).exists():
            errors.append(f"Vault path does not exist: {self.vault_path}")

        # File validation - make paths relative to vault_path if provided
        vault_base = Path(self.vault_path) if self.vault_path else Path.cwd()
        for note_path in self.notes:
            # Try absolute path first, then relative to vault
            note_file = Path(note_path)
            if not note_file.exists():
                # Try relative to vault path
                vault_relative = vault_base / note_path
                if not vault_relative.exists():
                    errors.append(f"Note file does not exist: {note_path}")

        return errors

    def get_effective_llm_api_key(self) -> str:
        """Get the API key to use for LLM from new or legacy format"""
        # Try new api_keys format first
        if self.api_keys and self.llm_provider in self.api_keys:
            return self.api_keys[self.llm_provider]
        # Fall back to legacy format
        return self.llm_api_key or ''

    def get_effective_embedder_api_key(self) -> str:
        """Get the API key to use for embedder (fallback to LLM key if not provided)"""
        # Try new api_keys format first
        if self.api_keys and self.embedder_provider in self.api_keys:
            return self.api_keys[self.embedder_provider]
        # Fall back to legacy format, then to LLM key
        return self.embedder_api_key or self.get_effective_llm_api_key()

    def get_database_uri(self) -> str:
        """Get the properly formatted database URI"""
        return self.database_url

    def to_graphiti_llm_config(self) -> Dict[str, Any]:
        """Convert to Graphiti LLM configuration format"""
        config = {
            'api_key': self.get_effective_llm_api_key(),
            'model': self.llm_model
        }

        # Add provider-specific settings
        if self.llm_provider == 'azure' and self.azure_endpoint:
            config['azure_endpoint'] = self.azure_endpoint
        if self.llm_provider == 'azure' and self.azure_api_version:
            config['api_version'] = self.azure_api_version
        elif self.llm_provider == 'ollama' and self.ollama_base_url:
            config['base_url'] = self.ollama_base_url

        return config

    def to_graphiti_embedder_config(self) -> Dict[str, Any]:
        """Convert to Graphiti embedder configuration format"""
        return {
            'api_key': self.get_effective_embedder_api_key(),
            'model': self.embedding_model
        }

    def to_dict(self) -> Dict[str, Any]:
        """Converts the dataclass to a dictionary, redacting sensitive information."""
        d = asdict(self)
        # Redact sensitive fields for safe logging
        if d.get('api_keys'):
            d['api_keys'] = {
                provider: 'REDACTED' for provider in d['api_keys']}
        if d.get('llm_api_key'):
            d['llm_api_key'] = 'REDACTED'
        if d.get('embedder_api_key'):
            d['embedder_api_key'] = 'REDACTED'
        if d.get('database_password'):
            d['database_password'] = 'REDACTED'
        if d.get('ws_auth_token'):
            d['ws_auth_token'] = 'REDACTED'

        # Summarize long lists
        if 'notes' in d and isinstance(d['notes'], list):
            d['notes'] = f"[{len(d['notes'])} notes]"

        return d


def load_config_from_stdin() -> BridgeConfig:
    """Load configuration from stdin JSON"""
    import sys

    try:
        stdin_raw = sys.stdin.read().strip()

        # Parse JSON configuration without debug output to prevent contamination
        config_data = json.loads(stdin_raw)

        # Handle potential double JSON encoding
        if isinstance(config_data, str):
            config_data = json.loads(config_data)

        # Ensure we have a dictionary
        if not isinstance(config_data, dict):
            raise ValueError(
                f"Configuration must be a JSON object, got {type(config_data)}: {config_data}")

        return BridgeConfig.from_dict(config_data)

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON configuration: {e}")
    except Exception as e:
        raise ValueError(f"Failed to parse configuration: {e}")


def load_config_from_file(file_path: str) -> BridgeConfig:
    """Load configuration from JSON file"""
    try:
        with open(file_path, 'r') as f:
            config_data = json.load(f)
        return BridgeConfig.from_dict(config_data)
    except FileNotFoundError:
        raise ValueError(f"Configuration file not found: {file_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in configuration file: {e}")


def setup_environment_variables(config: BridgeConfig):
    """Set up environment variables for providers that need them"""

    # Set database name for Graphiti (fixes default_db issue)
    os.environ['DEFAULT_DATABASE'] = config.database_name

    # Set API keys as environment variables for providers that expect them
    llm_api_key = config.get_effective_llm_api_key()
    if config.llm_provider == 'openai':
        os.environ['OPENAI_API_KEY'] = llm_api_key
    elif config.llm_provider == 'anthropic':
        os.environ['ANTHROPIC_API_KEY'] = llm_api_key
    elif config.llm_provider == 'google':
        os.environ['GOOGLE_API_KEY'] = llm_api_key
    elif config.llm_provider == 'groq':
        os.environ['GROQ_API_KEY'] = llm_api_key
    elif config.llm_provider == 'venice':
        os.environ['VENICE_API_KEY'] = llm_api_key
    elif config.llm_provider == 'openrouter':
        os.environ['OPENROUTER_API_KEY'] = llm_api_key

    # Set embedder API keys
    embedder_key = config.get_effective_embedder_api_key()
    if config.embedder_provider == 'openai':
        os.environ['OPENAI_API_KEY'] = embedder_key
    elif config.embedder_provider == 'voyage':
        os.environ['VOYAGE_API_KEY'] = embedder_key

    # Set debug flag
    if config.debug:
        os.environ['GRAPHITI_BRIDGE_DEBUG'] = '1'


def get_vault_path() -> Optional[str]:
    """Get vault path from environment variable"""
    return os.environ.get('OBSIDIAN_VAULT_PATH')
