"""
Configuration handling for Graphiti Bridge

Handles configuration validation, environment variables, and provider-specific settings.
"""

import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field
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

    # Day86.01: FalkorDB TLS support. graphiti_core's FalkorDriver has no ssl kwarg of
    # its own -- the only way to enable TLS is build_falkor_connection()'s falkor_db=
    # escape hatch (see sync.py). Boolean, so it cannot reuse _get_database_field()
    # (that helper's "falsy value -> default" behavior would silently coerce an explicit
    # False back to whatever default_value it was given). Resolved via _get_database_ssl()
    # instead, which is boolean-safe. Default False preserves today's no-TLS behavior for
    # every existing local Docker FalkorDB setup untouched.
    database_ssl: bool = False

    # Provenance marker — set when the connection was auto-filled via Endogon's
    # "Connect via API Key" flow, as opposed to manually entered. Optional, defaults
    # to None; consumed later for auth-failure error messaging (Day87.01).
    source: Optional[str] = None

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

    # Day78.04 (Issue #20): Ollama context window size (num_ctx), passed via
    # extra_body by OllamaGenericClient (ollama_client.py). graphiti_core's
    # LLMConfig has no field for this — Ollama otherwise loads models at its
    # 131072-token default context (observed: ~22GB reserved for a 2.5GB model
    # vs ~3.9GB at num_ctx=8192). Only consumed when llm_provider == 'ollama'.
    ollama_num_ctx: int = 8192

    # Episode and Ontology Configuration
    use_custom_ontology: bool = False
    use_bulk_sync: bool = False
    default_namespace: str = "vault"
    enable_folder_namespacing: bool = False
    enable_property_namespacing: bool = False
    namespace_strategy: str = "vault"  # 'vault', 'folder', 'property', 'custom'
    folder_namespace_mappings: Optional[List[Dict[str, str]]] = None

    # Extraction instruction overrides (Graphiti v0.28.1+ custom_extraction_instructions)
    global_extraction_instructions: Optional[str] = None

    # Episode source description
    source_description: Optional[str] = None

    # Issue #11: configurable frontmatter property name whose value becomes source_description.
    # When set, metadata[source_description_key] wins over frontmatter.type.
    # e.g. source_description_key = "mm_source" → note's mm_source frontmatter value is used.
    source_description_key: Optional[str] = None

    # Optional override of namespace group_id provided by TS side (pass-through like source_description)
    group_id: Optional[str] = None

    # Episode body field filtering (Phases 2 + 3)
    globally_ignored_fields: List[str] = field(default_factory=lambda: ['cssclass', 'mm_uid', 'mm_sync'])
    property_inclusion_mode: str = 'permissive'  # 'permissive' | 'strict'
    enabled_properties: Optional[Dict[str, List[str]]] = None  # { EntityType: [prop1, prop2] } for strict mode

    # Dynamic Ontology Rules (Day59.01) — per-note-type scoping of entity_types/edge_types/
    # edge_type_map before add_episode(). Each dict: {id, name, matchField, matchValues,
    # includedEntityTypes, includedEdgeTypes, enabled}. None/empty = no filtering (unchanged behaviour).
    dynamic_rules: Optional[List[Dict[str, Any]]] = None

    # Cap on prior episodes fetched for context per sync (Phase 3 token-cost fix)
    # When previous_episode_uuids is None, Graphiti defaults to last_n=10 (RELEVANT_SCHEMA_LIMIT).
    # Capping to 2 cuts ~80% of the previous_episodes prompt block (~40-50% total token reduction).
    previous_episodes_limit: int = 2

    # Wikilink extraction hints (Phase 5)
    wikilink_extraction_hints: bool = True

    # Episode contributor — injected as mm_contributor for shared-DB attribution
    episode_contributor: Optional[str] = None

    # WebSocket Configuration for Extended MCP
    ws_port: int = 8765
    ws_auth_token: str = ""
    graph_view_id: str = "vault"

    # Explicit client-side output size for graphs created with truncated vectors.
    # None preserves the provider's native output size.
    embedding_dimensions: Optional[int] = None

    @classmethod
    def _resolve_field(cls, config_dict: Dict[str, Any], snake_key: str,
                        camel_key: Optional[str] = None, default: Any = None) -> Any:
        """Day86.03: presence-based field resolver.

        Checks `snake_key` first, then `camel_key` (if given), and returns
        `default` ONLY when NEITHER key is present in `config_dict`. Never uses
        truthiness -- this is the fix for the `X or Y.get(camel, default)` idiom
        used throughout the old from_dict(), which silently discarded an
        explicitly-sent falsy value (`""`, `0`, `False`) under the snake_case key
        alone, because `or` treats "falsy" and "absent" as the same thing. They
        are not: an explicit `default_namespace: ""` means "use empty string";
        an absent key means "use the default." Collapsing that distinction
        produced the Day86.02 'vault' graph-naming incident.
        """
        if snake_key in config_dict:
            return config_dict[snake_key]
        if camel_key is not None and camel_key in config_dict:
            return config_dict[camel_key]
        return default

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any],
                   db_entry: Optional[Dict[str, Any]] = None) -> 'BridgeConfig':
        """Create BridgeConfig from dictionary (JSON input)

        Day86.04 Task 1: optional db_entry pins every database- and embedder-scoped
        resolution (embedder_provider/embedding_model, database_url/username/password/
        name/ssl) to a specific databases[] entry instead of whichever entry
        _get_primary_database_entry(config_dict) would otherwise pick. Purely additive:
        omitting db_entry (every existing caller) preserves today's primary-database
        behavior exactly -- see _create_bridge_config() (no-database_id default path).
        """

        # Day83.02: embedder_provider/embedding_model used to read the legacy
        # top-level-only field, which could silently disagree with the per-database
        # value the settings UI actually writes -- a call resolved through this
        # function (e.g. the no-database_id default client) would route to whichever
        # provider the top-level field happened to hold, not the one the user selected
        # for their database. Resolved the same way database credentials already are
        # (_get_database_field): explicit override on this payload -> primary
        # databases[] entry (or db_entry, when a specific database is targeted --
        # Day86.04) -> legacy top-level field as a last-resort migration input.
        # Unlike database credentials, no literal default is applied when nothing
        # resolves -- an unconfigured provider must fail loudly here (naming the
        # setting and database), not silently default to 'openai' and let the
        # upstream API reject a key that was never meant for that provider.
        embedder_provider = cls._get_embedder_field(
            config_dict, 'embedder_provider', 'embedderProvider', db_entry=db_entry)
        embedding_model = cls._get_embedder_field(
            config_dict, 'embedding_model', 'embeddingModel', db_entry=db_entry)
        if not embedder_provider or not embedding_model:
            primary_db = cls._get_primary_database_entry(config_dict)
            db_name = primary_db.get('label') or primary_db.get(
                'id') or 'the default database'
            missing = 'embedderProvider' if not embedder_provider else 'embeddingModel'
            raise ValueError(
                f"{missing} is not configured for {db_name}. Set it in Plugin "
                f"Settings -> Databases before running graph operations."
            )

        # Day86.03: default_namespace resolved once, up front, via the presence-based
        # _resolve_field() -- the headline fix for the Day86.02 incident (an explicit
        # default_namespace: "" no longer collapses to the 'vault' literal). Hoisted
        # to a local so graph_view_id's fallback below can reuse the already-resolved
        # value instead of re-reading defaultNamespace raw from the dict.
        default_namespace = cls._resolve_field(
            config_dict, 'default_namespace', 'defaultNamespace', 'vault')

        # Handle both new (snake_case) and old (camelCase) field naming
        return cls(
            # LLM Configuration
            llm_provider=cls._resolve_field(
                config_dict, 'llm_provider', 'llmProvider', 'openai'),
            llm_model=cls._resolve_field(
                config_dict, 'llm_model', 'llmModel', 'gpt-4o'),
            llm_small_model=cls._resolve_field(
                config_dict, 'llm_small_model', 'llmSmallModel', None),

            # Embedder Configuration
            embedder_provider=embedder_provider,
            embedding_model=embedding_model,
            embedding_dimensions=cls._get_embedder_field(
                config_dict, 'embedding_dimensions', 'embeddingDimensions', db_entry=db_entry),

            # Database Configuration
            database_type=cls._resolve_field(
                config_dict, 'database_type', 'databaseType', 'neo4j'),
            database_url=cls._get_database_url_from_config(config_dict, db_entry=db_entry),
            database_username=cls._get_database_field(
                config_dict, 'database_username', 'databaseUsername', 'neo4j',
                nested_key='username', db_entry=db_entry),
            database_password=cls._get_database_field(
                config_dict, 'database_password', 'databasePassword', '',
                nested_key='password', db_entry=db_entry),
            database_name=cls._get_database_field(
                config_dict, 'database_name', 'databaseName', 'neo4j',
                nested_key='database', db_entry=db_entry),

            # Day86.01: FalkorDB TLS flag (boolean-safe resolver, see field comment above)
            # Day86.04 Task 1: db_entry threaded through so a targeted database_id
            # resolves its own ssl flag, not the primary databases[] entry's.
            database_ssl=cls._get_database_ssl(config_dict, db_entry=db_entry),

            # Provider-specific API keys (new format)
            api_keys=cls._resolve_field(config_dict, 'api_keys', 'apiKeys', None),

            # Legacy API keys (backward compatibility)
            llm_api_key=cls._resolve_field(config_dict, 'llm_api_key', 'llmApiKey', ''),
            embedder_api_key=cls._resolve_field(
                config_dict, 'embedder_api_key', 'embedderApiKey', None),

            # Provider-specific settings
            azure_endpoint=cls._resolve_field(
                config_dict, 'azure_endpoint', 'azureEndpoint', None),
            azure_api_version=cls._resolve_field(
                config_dict, 'azure_api_version', 'azureApiVersion', None),
            ollama_base_url=cls._resolve_field(
                config_dict, 'ollama_base_url', 'ollamaBaseUrl', None),
            openrouter_preset_slug=cls._resolve_field(
                config_dict, 'openrouter_preset_slug', 'openrouterPresetSlug', None),
            openrouter_use_preset_with_custom_model=cls._resolve_field(
                config_dict, 'openrouter_use_preset_with_custom_model',
                'openrouterUsePresetWithCustomModel', False),

            # Processing Configuration
            models_path=cls._resolve_field(config_dict, 'models_path', 'modelsPath', None),
            vault_path=cls._resolve_field(config_dict, 'vault_path', 'vaultPath', None),
            notes=config_dict.get('notes', []),

            # Optional settings
            batch_size=cls._resolve_field(config_dict, 'batch_size', 'batchSize', 10),
            # Day86.03: migrated to the presence-based resolver -- unlike the other
            # fields in this block, this IS an intended behavior change. An explicit
            # max_retries: 0 previously silently became 3 via the old
            # `X or Y.get(camel, 3)` pattern; it now survives as 0, matching the
            # "explicit falsy means use this value" decision recorded for this field
            # in the Day86.03 audit.
            max_retries=cls._resolve_field(config_dict, 'max_retries', 'maxRetries', 3),
            # Day86.03: GraphitiService.ts:1686 sends `connection_timeout`, never
            # `timeout` -- from_dict() previously only ever read the 'timeout' key,
            # so this field was a dead wire (BridgeConfig.timeout was ALWAYS the
            # hardcoded 30 regardless of the user's Settings UI value). Fixed
            # trivially alongside this migration by checking 'connection_timeout'
            # as the second key.
            timeout=cls._resolve_field(config_dict, 'timeout', 'connection_timeout', 30),
            debug=cls._resolve_field(config_dict, 'debug', 'debugMode', False),

            # Day78.04 (Issue #20): Ollama context window override
            ollama_num_ctx=cls._resolve_field(
                config_dict, 'ollama_num_ctx', 'ollamaNumCtx', 8192),

            # Episode and Ontology Configuration
            use_custom_ontology=cls._resolve_field(
                config_dict, 'use_custom_ontology', 'useCustomOntology', False),
            use_bulk_sync=cls._resolve_field(
                config_dict, 'use_bulk_sync', 'useBulkSync', False),
            # Day86.03 HEADLINE FIX: an explicit default_namespace: "" now survives
            # as "" instead of collapsing to the 'vault' literal (the Day86.02 root
            # cause). Resolved once above; reused here and by graph_view_id below.
            default_namespace=default_namespace,
            enable_folder_namespacing=cls._resolve_field(
                config_dict, 'enable_folder_namespacing', 'enableFolderNamespacing', False),
            enable_property_namespacing=cls._resolve_field(
                config_dict, 'enable_property_namespacing', 'enablePropertyNamespacing', False),
            namespace_strategy=cls._resolve_field(
                config_dict, 'namespace_strategy', 'namespaceStrategy', 'vault'),
            folder_namespace_mappings=cls._resolve_field(
                config_dict, 'folder_namespace_mappings', 'folderNamespaceMappings', []),

            # Episode source description
            source_description=cls._resolve_field(
                config_dict, 'source_description', 'sourceDescription', None),

            # Issue #11: configurable frontmatter key for source_description override
            source_description_key=cls._resolve_field(
                config_dict, 'source_description_key', 'sourceDescriptionKey', None),

            # Extraction instruction overrides
            global_extraction_instructions=cls._resolve_field(
                config_dict, 'global_extraction_instructions',
                'globalExtractionInstructions', None),

            # Optional namespace override (mirrors source_description pass-through)
            group_id=cls._resolve_field(config_dict, 'group_id', 'groupId', None),

            # Endogon-sourced connection marker (Day87.01) — internal only, no camelCase variant
            source=cls._resolve_field(config_dict, 'source', 'source', None),

            # Episode body field filtering (Phases 2 + 3) -- Day86.03 audit: already
            # presence-safe (no `or`), left exactly as-is; these three demonstrate
            # the target pattern the rest of this method now follows.
            globally_ignored_fields=config_dict.get('globally_ignored_fields', config_dict.get('globallyIgnoredFields', ['cssclass', 'mm_uid', 'mm_sync'])),
            property_inclusion_mode=config_dict.get('property_inclusion_mode', config_dict.get('propertyInclusionMode', 'permissive')),
            enabled_properties=config_dict.get('enabled_properties', config_dict.get('enabledProperties')),

            # Dynamic Ontology Rules (Day59.01). Day86.03: dropped the trailing
            # `or None` -- this field was already presence-safe internally
            # (`.get(key, .get(camelKey))`); the field's own comment already treats
            # []/'' as equivalent to None downstream, so the `or None` was a
            # no-op dressed up as a guard. Routed through _resolve_field for
            # consistency with the rest of this method.
            dynamic_rules=cls._resolve_field(config_dict, 'dynamic_rules', 'dynamicRules', None),

            # Prior episode context cap (Phase 3 token-cost fix) -- Day86.03 audit:
            # already presence-safe, left exactly as-is.
            previous_episodes_limit=int(config_dict.get('previous_episodes_limit', config_dict.get('previousEpisodesLimit', 2))),

            # Wikilink extraction hints (Phase 5) -- Day86.03 audit: already
            # presence-safe, left exactly as-is.
            wikilink_extraction_hints=config_dict.get('wikilink_extraction_hints', config_dict.get('wikilinkExtractionHints', True)),

            # Episode contributor. Day86.03: dropped the trailing `or None` (same
            # already-presence-safe + no-op-guard reasoning as dynamic_rules above).
            episode_contributor=cls._resolve_field(
                config_dict, 'episode_contributor', 'episodeContributor', None),

            # WebSocket Configuration for Extended MCP
            ws_port=cls._resolve_field(config_dict, 'ws_port', 'wsPort', 8765),
            ws_auth_token=cls._resolve_field(config_dict, 'ws_auth_token', 'wsAuthToken', ''),
            # Day86.03: simplified from a 3-link chain that cross-referenced a
            # DIFFERENT field's camelCase key as a tertiary fallback
            # (`.get('graph_view_id') or .get('graphViewId') or
            # .get('defaultNamespace', 'vault')`) -- that read defaultNamespace raw
            # and un-resolved, bypassing whatever default_namespace itself actually
            # resolved to. Now falls back to the already-resolved `default_namespace`
            # local (computed above), so the coupling is explicit and consistent
            # rather than an accident of dict lookup order.
            graph_view_id=cls._resolve_field(
                config_dict, 'graph_view_id', 'graphViewId', default_namespace)
        )

    @classmethod
    def _get_database_field(cls, config_dict: Dict[str, Any], snake_key: str, camel_key: str, default_value: str,
                             nested_key: Optional[str] = None, db_entry: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get database field with proper None handling for FalkorDB

        Day86.04 Task 1: db_entry, when provided, pins the nested-databases[]
        fallback (below) to that specific entry instead of
        _get_primary_database_entry(config_dict) -- mirrors the precedent
        _get_embedder_field() already established (Day83.02). Purely additive:
        omitting db_entry preserves today's primary-database behavior exactly.
        """

        # Issue #19: Neo4j no-auth catch-22 fix.
        # An empty database_username was unconditionally re-defaulted to 'neo4j' below,
        # which then tripped validate()'s "password required when username is set" check
        # for intentional no-auth setups (empty username + empty password).
        # Only apply the 'neo4j' default when a password is actually present, so an
        # empty username + empty password pair is preserved as no-auth. FalkorDB's
        # None-preserving behavior (below) is untouched by this branch.
        if snake_key == 'database_username':
            database_type = config_dict.get('database_type') or config_dict.get('databaseType', 'neo4j')
            if database_type == 'neo4j':
                password = cls._get_database_field(
                    config_dict, 'database_password', 'databasePassword', '',
                    nested_key='password', db_entry=db_entry)
                if not password:
                    default_value = ''
                # Day86.03 audit: known, unmitigated edge case -- flagged, not fixed,
                # to keep this migration scoped to the falsy-collapse pattern rather
                # than Issue #19's carve-out logic itself. An empty username +
                # NON-empty password still collapses username to 'neo4j' below,
                # because default_value only becomes '' when password is ALSO
                # empty. Whether that pairing should instead be preserved or
                # treated as a config error is a real open question, deliberately
                # left as a follow-up rather than answered here.

        if snake_key in config_dict:
            value = config_dict[snake_key]
            # Day79.02 Task 4: retained, not superseded by any upstream FalkorDB fix -
            # works around FalkorDB no-auth setups. FalkorDB, unlike Neo4j, has no
            # mandatory default credential, so a None here must stay None rather than
            # being coerced to an empty-string/default value that would force
            # unwanted authentication. No upstream issue tracks this; it is a genuine
            # backend behavioral difference, not a bug being worked around.
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

        # Fall through to nested database entries (databases[] array, then legacy databaseConfigs)
        if nested_key:
            # Day86.04 Task 1: db_entry pins the first fallback source to the caller's
            # targeted database instead of scanning for the primary one.
            target_db = db_entry if db_entry is not None else cls._get_primary_database_entry(config_dict)
            for db_config in (
                target_db,
                cls._get_current_database_config(config_dict),
            ):
                if nested_key in db_config:
                    value = db_config[nested_key]
                    if value is None:
                        return None
                    return value if value else default_value

        # Return default if neither key exists
        return default_value

    @classmethod
    def _get_database_ssl(cls, config_dict: Dict[str, Any],
                            db_entry: Optional[Dict[str, Any]] = None) -> bool:
        """Get FalkorDB TLS/SSL flag (Day86.01).
        Mirrors the database_username/database_password/database_name resolution order
        (top-level snake_case -> top-level camelCase -> nested databases[] entry) but is
        boolean-safe: _get_database_field()'s `value if value else default_value` pattern
        would silently coerce an explicit False back to its default, which is wrong for a
        boolean flag. Nested key on a databases[] entry is bare 'ssl', matching the bare
        'username'/'password'/'database' nested_key convention already used above.

        Day86.03: this method is the pre-existing precedent that _resolve_field()
        above generalizes -- it already checks presence via `in`, never truthiness,
        for the top-level keys. Left as its own method rather than migrated onto
        _resolve_field() because its nested-databases[] fallback has no equivalent
        in the shared helper; the top-level shape is otherwise identical.

        Day86.04 Task 1: db_entry, when provided, pins the nested-databases[]
        fallback to that specific entry instead of the primary one -- same
        additive pattern as _get_database_field()/_get_database_url_from_config()."""
        if 'database_ssl' in config_dict:
            return bool(config_dict['database_ssl'])
        if 'databaseSsl' in config_dict:
            return bool(config_dict['databaseSsl'])

        target_db = db_entry if db_entry is not None else cls._get_primary_database_entry(config_dict)
        for db_config in (
            target_db,
            cls._get_current_database_config(config_dict),
        ):
            if 'ssl' in db_config:
                return bool(db_config['ssl'])

        return False

    @classmethod
    def _get_database_url_from_config(cls, config_dict: Dict[str, Any],
                                        db_entry: Optional[Dict[str, Any]] = None) -> str:
        """
        Get database URL with priority handling:
        1. Direct databaseUrl in config
        2. Database-specific configuration (Neo4j: uri, FalkorDB: host+port)
        3. Fallback to default URL

        Day86.04 Task 1: db_entry, when provided, pins priority 2's databases[]
        lookup to that specific entry instead of _get_primary_database_entry() --
        same additive pattern as _get_database_field()/_get_database_ssl().
        """
        # @vessel-protocol:Heimdall governs:validation context:Database URL configuration priority resolution
        # @inter-dependencies: BridgeConfig.from_dict, database connection setup
        # @purpose: Ensure proper database URL resolution from plugin settings with fallback handling
        # @result: Sync process uses correct database URL from plugin configuration instead of hardcoded defaults
        # @signed: C.Bjørn

        # Priority 1: Direct databaseUrl (highest priority)
        # Day86.03 audit: reviewed, left truthiness-based deliberately. An empty
        # URL string is never a legitimate deliberate value (there is no valid
        # "explicitly no database URL" state, unlike default_namespace's valid
        # empty string) -- falling through to priority 2/3/4 on an empty string is
        # correct here, not a falsy-collapse bug. Low priority, not migrated.
        direct_url = config_dict.get(
            'databaseUrl') or config_dict.get('database_url')
        if direct_url:
            return direct_url

        database_type = config_dict.get(
            'database_type') or config_dict.get('databaseType', 'neo4j')

        # Priority 2: New multi-database list entry (databases[] array)
        primary_db = db_entry if db_entry is not None else cls._get_primary_database_entry(config_dict)
        if database_type == 'neo4j':
            neo4j_uri = primary_db.get('uri')
            if neo4j_uri:
                return neo4j_uri
        elif database_type == 'falkordb' and primary_db:
            host = primary_db.get('host', 'localhost')
            port = primary_db.get('port', 6379)
            return f"falkor://{host}:{port}"

        # Priority 3: Legacy databaseConfigs
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

        # Priority 4: Fallback defaults based on database type
        if database_type == 'falkordb':
            return "falkor://localhost:6379"
        else:  # neo4j default
            return "bolt://localhost:7687"

        # @vessel-close:Heimdall

    # Day86.04 Task 1: _get_database_field()/_get_database_ssl()/_get_database_url_from_config()
    # above now accept the same db_entry override _get_embedder_field() has had since
    # Day83.02, closing the Day84.02 follow-up that used to be noted here. This method
    # itself remains the "no specific database targeted" fallback those three resolvers
    # use when db_entry is omitted -- unchanged, since every existing caller (the default/
    # no-database_id path) still needs a primary-entry scan.
    @classmethod
    def _get_primary_database_entry(cls, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Return first enabled non-child-vault DB entry matching databaseType from databases[]."""
        database_type = config_dict.get('database_type') or config_dict.get('databaseType', 'neo4j')
        databases = config_dict.get('databases', [])
        if not isinstance(databases, list):
            return {}
        for database in databases:
            if (
                isinstance(database, dict)
                and database.get('type') == database_type
                and database.get('category') != 'child-vault'
                and database.get('enabled', True)
            ):
                return database
        return {}

    @classmethod
    def _get_embedder_field(cls, config_dict: Dict[str, Any], snake_key: str, camel_key: str,
                             db_entry: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Resolve an embedder-config field with per-database priority,
        the single resolver every caller routes through (Day83.02):
        1. Explicit snake_case override on this payload (non-Obsidian-shaped callers,
           e.g. sync_daemon/publish requests and test fixtures already resolve
           per-DB TS-side and pass the resolved value directly).
        2. The target database entry -- db_entry if the caller already resolved one
           (e.g. megamem_mcp_server._get_graphiti_client's named database_id lookup),
           else the primary databases[] entry.
        3. Legacy top-level camelCase field, read only as a migration input -- never
           checked ahead of the per-database value, and never applied as a runtime
           fallback once a database entry exists.
        No literal default is applied when nothing resolves -- from_dict() (and
        _create_bridge_config_for_db) decide what an unresolved value means: loud
        failure naming the setting and database, not a silent 'openai'.

        Day86.03: migrated steps 1 and 2 from truthiness (`if config_dict.get(...)`)
        to presence (`in`) for consistency with _resolve_field(). This is a
        deliberate behavior change at this layer: an explicit embedder_provider=""
        sent directly on the payload, or present on the target db entry, is now
        returned as-is instead of falling through to the next source. It still
        fails loudly -- from_dict()'s `if not embedder_provider or not
        embedding_model` check downstream treats the empty string as unconfigured
        and raises ValueError, which is exactly the Day83.02 "no default, loud
        failure" design this field depends on. Confirmed by
        test_day86_03_falsy_value_resolution.py."""
        if snake_key in config_dict:
            return config_dict[snake_key]

        target_db = db_entry if db_entry is not None else cls._get_primary_database_entry(config_dict)
        if camel_key in target_db:
            return target_db[camel_key]

        # Legacy top-level fallback (Day83.02: migration input only, never a runtime default)
        return config_dict.get(camel_key)

    @classmethod
    def _get_current_database_config(cls, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Return legacy databaseConfigs[type] dict."""
        database_type = config_dict.get('database_type') or config_dict.get('databaseType', 'neo4j')
        database_configs = config_dict.get('databaseConfigs', {})
        if isinstance(database_configs, dict):
            current = database_configs.get(database_type)
            if isinstance(current, dict):
                return current
        return {}

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

        if self.database_username and not self.database_password and self.database_type == 'neo4j':
            errors.append("Database password is required for Neo4j when username is set")

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


# Day79.02 Task 2.2 — interim mitigation for graphiti-core's cap_string_attributes
# backstop, which DROPS (not truncates) any string entity-attribute value over 250
# chars (DEFAULT_ATTRIBUTE_MAX_LENGTH in attribute_utils.py). Value derived from the
# Task 0.6 vault-wide frontmatter measurement: the single longest observed scalar
# value across the vault was 1,734 chars (`description` field); 2000 gives headroom
# above that without reopening the meta-reasoning-leak hole the cap exists to guard
# against (upstream's threat model is multi-hundred/thousand-char LLM rambling).
# This is an interim, global mitigation only — Task 2.3's per-field Field(max_length=...)
# in the Ontology Manager is the durable fix. Per DevDoc Rev 5 Sec.3: use the
# supported env var; graphiti_core source is never edited.
ATTRIBUTE_CAP_ENV_VAR = 'GRAPHITI_ATTRIBUTE_MAX_LENGTH'
ATTRIBUTE_CAP_INTERIM_VALUE = '2000'


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

    if config.debug:
        os.environ['GRAPHITI_BRIDGE_DEBUG'] = '1'

    # Day79.02 Task 2.2 — only set if not already configured (respects an operator's
    # own explicit override); called before any Graphiti calls in both sync.py's
    # main() and sync_daemon.py's run_sync_with_config().
    os.environ.setdefault(ATTRIBUTE_CAP_ENV_VAR, ATTRIBUTE_CAP_INTERIM_VALUE)


def get_vault_path() -> Optional[str]:
    """Get vault path from environment variable"""
    return os.environ.get('OBSIDIAN_VAULT_PATH')
