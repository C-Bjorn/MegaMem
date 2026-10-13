#!/usr/bin/env python3
"""
Graphiti Bridge Sync Script

Main script for syncing Obsidian notes with Graphiti temporal knowledge graphs.
This script is called by the TypeScript plugin and handles the sync process for a single note.
"""

# Performance optimization flags
import json
# Day85.03: provider-specific LLM clients (GeminiClient, AnthropicClient, OpenAIClient,
# OpenAIGenericClient), Neo4jDriver, and OpenAIRerankerClient/OpenAIEmbedder used to be
# imported eagerly here, on every daemon/MCP-server launch, regardless of which single
# provider a given vault actually configures. Measured cost: 57s for this module's own
# import on a real client machine (see Day85.03 DevDoc). They are now loaded on first
# use via graphiti_bridge/lazy_imports.py's get_*() accessors, following the same
# lazy-loading pattern already established there for the Gemini/Voyage/Azure embedders.
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EpisodicNode
from graphiti_core.utils.bulk_utils import RawEpisode
from graphiti_core.nodes import EpisodeType
from graphiti_core import Graphiti
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import re
import argparse
import traceback
import sys
import asyncio
import logging
import time
import os

# Sentinel passed as embedding_dim to embedder branches whose graphiti-core client
# slices the real API response to a frozen 1024D default when unset, making the slice
# a permanent no-op. Value exceeds every embedding model dimension known to this
# codebase. See Day79.01 and create_embedder_client()'s docstring.
NO_TRUNCATION_EMBEDDING_DIM = 8192

# Buffer for critical diagnostics that must survive even when a caller captures only
# stdout (not stderr).
_DIAGNOSTICS_BUFFER = []

try:
    # UTF-8 stdout encoding for Windows environments
    if hasattr(sys, 'stdout') and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    else:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# UTF-8 stdin encoding for Windows environments (mirrors stdout fix above)
try:
    if hasattr(sys, 'stdin') and hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
    else:
        import io
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
except Exception:
    pass


# Day85.03: FalkorDB driver (and the other provider drivers/clients below) is now
# loaded lazily via lazy_imports.get_falkor_driver() at the point of use in
# initialize_graphiti(), instead of eagerly here on every module import.

# Import LLM client creation function and configurations

# Embedding provider imports (try graceful fallbacks)
GEMINI_EMBEDDER_AVAILABLE = False
GeminiEmbedder = None
GeminiEmbedderConfig = None
try:
    from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
    GEMINI_EMBEDDER_AVAILABLE = True
except ImportError:
    pass  # Gemini embedder not available

VOYAGE_EMBEDDER_AVAILABLE = False
VoyageAIEmbedder = None
VoyageAIEmbedderConfig = None
try:
    from graphiti_core.embedder.voyage import VoyageAIEmbedder, VoyageAIEmbedderConfig
    VOYAGE_EMBEDDER_AVAILABLE = True
except ImportError:
    pass  # Voyage embedder not available

AZURE_EMBEDDER_AVAILABLE = False
AzureOpenAIEmbedderClient = None
try:
    from graphiti_core.embedder.azure_openai import AzureOpenAIEmbedderClient
    AZURE_EMBEDDER_AVAILABLE = True
except ImportError:
    pass  # Azure embedder not available

# OpenAI embedder availability (always available since it's imported directly)
OPENAI_EMBEDDER_AVAILABLE = True

# No separate Ollama embedder - Graphiti uses OpenAIEmbedder with custom base_url for Ollama
OLLAMA_EMBEDDER_AVAILABLE = True  # Always available since it uses OpenAIEmbedder


# Import local modules - always use relative imports (production-safe)
from .config import BridgeConfig, load_config_from_stdin, setup_environment_variables
from .utils import (
    setup_logging,
    format_success_response,
    format_error_response,
    extract_frontmatter,
    extract_text_content,
    validate_note_file,
    print_json_response,
    print_final_json_response,
    print_error_and_exit,
    install_attribute_cap_capture,
    summarize_attribute_cap_drops,
    verify_attribute_cap_env_effect,
)
from .models import initialize_global_loader, get_node_types, get_edge_types, get_entity_type_definitions, get_edge_type_definitions, get_edge_type_map, get_graphiti_entity_types, get_graphiti_edge_types, get_graphiti_edge_type_map
# InfrastructureError is stdlib-only (graphiti_bridge/errors.py) so it can stay eager —
# it's caught in a top-level except clause below regardless of which provider ran.
# OpenRouterClient/OllamaGenericClient themselves (and their openai/httpx/graphiti_core
# import chains) are loaded lazily via lazy_imports.get_openrouter_client() /
# get_ollama_client() only inside their respective provider branches. See Day85.03.
from .errors import InfrastructureError
from .lazy_imports import (
    get_openai_client,
    get_openai_generic_client,
    get_anthropic_client,
    get_gemini_client,
    get_neo4j_driver,
    get_falkor_driver,
    get_falkordb_client,
    get_openai_reranker_client,
    get_openai_embedder,
    get_openrouter_client,
    get_ollama_client,
)


def build_falkor_connection(config: BridgeConfig) -> Dict[str, Any]:
    """
    Parse config.database_url into FalkorDB/Redis connection kwargs (Day86.01).

    Single source of truth shared by both this module's initialize_graphiti() (runtime
    driver construction) and test_connections.py's test_falkordb_connection() (the Test
    Connection probe). Before this, those two built FalkorDB connections through two
    independently-maintained code paths -- sync.py via FalkorDriver(host=...), and the
    probe via a raw redis.Redis(host=...) -- and only sync.py had any route to TLS. That
    divergence meant the probe could never represent what a real sync would do.

    Accepts both 'redis://' and 'falkor://' schemes, falling back to localhost:6379 on no
    match -- exact parity with the regex this replaces (previously inline in
    initialize_graphiti()).

    Returns a dict with keys: host (str), port (int), username (Optional[str]),
    password (Optional[str]), ssl (bool). ssl_cert_reqs is intentionally NOT included --
    'required' (certificate verification on) is the falkordb-py/redis-py library default,
    so omitting it here is transparent (identical behavior with or without this override),
    not hidden magic. A caller needing to relax verification would pass ssl_cert_reqs
    explicitly at the construction site, not through this helper.
    """
    match = re.match(r'(?:redis|falkor)://([^:]+):(\d+)', config.database_url)
    if match:
        host, port_str = match.groups()
        port = int(port_str)
    else:
        host, port = 'localhost', 6379

    return {
        'host': host,
        'port': port,
        'username': config.database_username or None,
        'password': config.database_password or None,
        'ssl': bool(getattr(config, 'database_ssl', False)),
    }


async def main():
    """Main entry point for the sync script"""
    import sys
    import os

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Graphiti Bridge Sync Script')
    parser.add_argument('--vault-path', type=str,
                        help='Path to the Obsidian vault for dynamic model loading')
    parser.add_argument('--plugin-data-path', type=str,
                        help='Explicit path to plugin data.json (overrides probing and env)')
    args = parser.parse_args()

    # CRITICAL: Redirect stderr to devnull immediately for non-debug mode to suppress ALL library output
    original_stderr = sys.stderr
    logger = None
    debug_mode = False  # Initialize debug_mode early to avoid UnboundLocalError

    try:
        # Load configuration from stdin
        config = load_config_from_stdin()

        # Get debug mode from config

        # Override vault_path from command line argument if provided
        if args.vault_path:
            config.vault_path = args.vault_path

        debug_mode = getattr(config, 'debug', False)
        if not debug_mode:
            # DO NOT use logging.disable() - it globally disables ALL logging
            # Instead, selectively disable specific third-party loggers
            # Disable all known third-party loggers (comprehensive list for ML libraries)
            # BUT preserve 'graphiti_bridge.sync' logger for our debug messages
            for logger_name in [
                'openai', 'httpx', 'neo4j', 'asyncio', 'urllib3', 'httpcore',
                'sentence_transformers', 'transformers', 'torch',
                'tokenizers', 'safetensors', 'accelerate', 'datasets',
                'requests', 'urllib3.connectionpool', 'matplotlib', 'PIL',
                'anthropic', 'google', 'gemini', 'voyageai',
                'azure', 'azure.identity', 'azure.core',
                'botocore', 'boto3', 's3transfer',
                'numpy', 'scipy', 'sklearn', 'pandas'
            ]:
                # Skip disabling our sync logger even in non-debug mode
                if logger_name != 'graphiti_bridge.sync':
                    logger_obj = logging.getLogger(logger_name)
                    logger_obj.disabled = True
                    logger_obj.setLevel(logging.CRITICAL + 1)
                    logger_obj.handlers.clear()

            # Disable Graphiti telemetry properly
            import os
            os.environ['GRAPHITI_TELEMETRY_ENABLED'] = 'false'

        # Set up logging only if debug mode
        logger = setup_logging(debug_mode)

        if debug_mode:
            logger.info("Starting Graphiti Bridge sync process")

        # Validate configuration
        validation_errors = config.validate()
        if validation_errors:
            error_msg = f"Configuration validation failed: {'; '.join(validation_errors)}"
            if config.debug:
                logger.error(f"Validation failed: {error_msg}")
            print_error_and_exit(error_msg)

        setup_environment_variables(config)

        # Install the attribute-cap drop handler and verify the
        # GRAPHITI_ATTRIBUTE_MAX_LENGTH mitigation took effect. See Day79.02.
        attr_cap_handler = install_attribute_cap_capture()
        attr_cap_env_check = verify_attribute_cap_env_effect()
        _DIAGNOSTICS_BUFFER.append(f"[ATTR-CAP-ENV] {attr_cap_env_check}")
        if attr_cap_env_check.get('took_effect'):
            if debug_mode:
                logger.info(
                    f"attribute_cap_env_verified effective_max_length={attr_cap_env_check.get('effective_max_length')}")
        else:
            logger.warning(f"attribute_cap_env_not_verified {attr_cap_env_check}")

        # Initialize model loader only if custom ontology is enabled
        if config.use_custom_ontology:
            vault_path = getattr(config, 'vault_path', None)

            if not vault_path:
                print_error_and_exit(
                    "Vault path not provided for custom ontology mode.")

            # Allow TypeScript (or caller) to override the plugin data path explicitly via CLI arg or environment
            plugin_data_path = None
            # 1) CLI arg has highest priority (e.g., --plugin-data-path)
            if hasattr(args, 'plugin_data_path') and args.plugin_data_path:
                plugin_data_path = args.plugin_data_path
            # 2) Next, environment variable (OBSIDIAN_PLUGIN_DATA_PATH)
            elif os.environ.get('OBSIDIAN_PLUGIN_DATA_PATH'):
                plugin_data_path = os.environ.get('OBSIDIAN_PLUGIN_DATA_PATH')

            # Initialize loader: if plugin_data_path was provided, pass its parent vault path;
            # otherwise pass vault_path and loader will probe new/old plugin ids.
            init_vault_path = vault_path
            if plugin_data_path:
                # If plugin_data_path points directly to data.json, derive vault root
                pdp = Path(plugin_data_path)
                if pdp.name == 'data.json' and 'plugins' in str(pdp):
                    # vault/.obsidian/plugins/<plugin-id>/data.json -> vault is 4 parents up
                    init_vault_path = str(pdp.parent.parent.parent.parent)
                elif 'plugins' in str(pdp):
                    # If path contains 'plugins', assume it's a plugin directory: vault/.obsidian/plugins/<plugin-id>
                    # Need to go up 3 levels to reach vault root (directory not file)
                    init_vault_path = str(pdp.parent.parent.parent)
                else:
                    # Otherwise assume provided path is vault root or derive accordingly
                    init_vault_path = str(pdp)
                if config.debug:
                    logger.debug(
                        f"Using explicit plugin_data_path for loader: {plugin_data_path} -> vault {init_vault_path}")

            # DEFINITIVE FIX: Explicitly initialize the loader and load models.
            # This removes the fragile sys.path manipulation and dynamic import.
            # The loader will prefer megamem-mcp.
            if init_vault_path and not initialize_global_loader(init_vault_path):
                # Provide detailed guidance in error message showing checked path
                primary_path = Path(init_vault_path) / ".obsidian" / \
                    "plugins" / "megamem-mcp" / "data.json"
                print_error_and_exit(
                    "Failed to load custom ontology data from data.json.",
                    f"Checked path: {primary_path}. If your plugin data.json is elsewhere, pass it with --plugin-data-path or set OBSIDIAN_PLUGIN_DATA_PATH."
                )

            if config.debug:
                logger.info(
                    "Custom ontology models loaded successfully via DynamicModelLoader.")
        else:
            if config.debug:
                logger.debug(
                    "Custom ontology disabled - skipping model loader")
                logger.info(
                    "Custom ontology disabled - skipping model loader initialization")

        # Initialize Graphiti with timing
        graphiti_init_start = time.time()
        if debug_mode:
            logger.debug("Initializing Graphiti...")

        graphiti = await initialize_graphiti(config, config.debug)
        if not graphiti:
            print_error_and_exit("Failed to initialize Graphiti")

        if debug_mode:
            graphiti_init_time = time.time() - graphiti_init_start
            logger.debug(
                f"Graphiti initialization completed in {graphiti_init_time:.2f}s")

        # Pre-sync smoke test: verify embedder dimensions match existing DB vectors
        dim_ok, existing_dims, expected_dims = await check_dimension_compatibility(graphiti, config, logger)
        if not dim_ok:
            db_label = config.database_name or config.database_url or 'unknown'
            logger.error(
                f'[EMBEDDER-DIMENSION-MISMATCH] "{db_label}": existing vectors are {existing_dims}D '
                f'but {config.embedder_provider}/{config.embedding_model} produces {expected_dims}D. '
                f'Fix the embedder in MegaMem Settings \u2192 Databases.'
            )
            # Close graphiti cleanly before exit to suppress asyncio StreamWriter cleanup noise
            try:
                if hasattr(graphiti, 'close'):
                    await graphiti.close()
                elif hasattr(graphiti, '_driver') and graphiti._driver:
                    await graphiti._driver.close()
            except Exception:
                pass
            print_error_and_exit(
                f'Embedder dimension mismatch in "{db_label}": DB has {existing_dims}D vectors, '
                f'configured embedder produces {expected_dims}D. '
                f'Fix the embedder provider/model in MegaMem Settings \u2192 Databases.'
            )

        # Validate that we have exactly one note
        if len(config.notes) != 1:
            print_error_and_exit(
                f"Expected exactly 1 note, got {len(config.notes)}")

        note_processing_start = time.time()
        if debug_mode:
            logger.debug(f"Processing note: {config.notes[0]}")

        # Clear drops from a prior note (defensive; main() processes one note per run).
        attr_cap_handler.clear()

        result = await process_note(config.notes[0], graphiti, logger, config)

        if debug_mode:
            note_processing_time = time.time() - note_processing_start
            logger.debug(
                f"Note processing completed in {note_processing_time:.2f}s")

        # Surface attribute-length-cap drops in the sync result. See Day79.02.
        if isinstance(result, dict):
            result['dropped_attributes'] = summarize_attribute_cap_drops(attr_cap_handler)

        # Ensure database connection is properly closed
        if config.debug:
            logger.debug("Closing Graphiti connection...")
        try:
            if hasattr(graphiti, 'close'):
                await graphiti.close()
            elif hasattr(graphiti, '_driver') and graphiti._driver:
                await graphiti._driver.close()
        except Exception as e:
            if debug_mode and logger:
                logger.warning(f"Error closing Graphiti connection: {e}")

        # Return success response
        try:
            # Ensure we have a valid result before printing
            if result is None:
                result = {
                    'status': 'error',
                    'message': 'No result generated'
                }

            # Attach diagnostics buffer to result so callers that only capture stdout can see critical diagnostics
            try:
                if isinstance(result, dict):
                    result['_diagnostics'] = '\n'.join(
                        str(item) for item in _DIAGNOSTICS_BUFFER)
                else:
                    # If result is a non-dict (unexpected), wrap into dict preserving original
                    result = {
                        'status': 'success',
                        'result': result,
                        '_diagnostics': '\n'.join(str(item) for item in _DIAGNOSTICS_BUFFER)
                    }
            except Exception:
                pass

            # Force flush stdout before JSON response
            sys.stdout.flush()

            # Add debug logging for final response (but don't log the full JSON to avoid contamination)
            if debug_mode:
                logger.debug(
                    "Sync completed successfully, sending final result to TypeScript")

            # Print the JSON response to stdout with explicit newline
            # CRITICAL: This MUST only go to stdout - TypeScript bridge communication
            print_final_json_response(result)

            # Force flush again to ensure it's sent
            sys.stdout.flush()

        except Exception as print_error:
            # If JSON printing fails, send a basic error response
            fallback_result = {
                'status': 'error',
                'message': f'Failed to print JSON response: {print_error}'
            }
            print(json.dumps(fallback_result, ensure_ascii=False,
                  separators=(',', ':')), flush=True)

    except KeyboardInterrupt:
        if logger:
            logger.debug("Keyboard interrupt")
        # Return structured JSON for keyboard interrupt
        error_response = {
            "success": False,
            "message": "Sync process interrupted by user",
            "exception": "KeyboardInterrupt",
            "traceback": None
        }
        # Attach diagnostics buffer if available
        try:
            error_response['_diagnostics'] = '\n'.join(
                str(item) for item in _DIAGNOSTICS_BUFFER)
        except Exception:
            pass
        # Ensure logger info if debug
        if logger and debug_mode:
            logger.debug("Printing keyboard interrupt JSON response")
        print(json.dumps(error_response, ensure_ascii=False,
                         separators=(',', ':')), flush=True)
        sys.exit(1)
    except Exception as e:
        # Capture full traceback
        tb = traceback.format_exc()
        short_exc = str(e)
        # Log full exception if debug enabled
        if logger and debug_mode:
            logger.error(f"Unexpected error in sync process: {short_exc}")
            logger.debug(tb)
        # Build structured JSON response containing traceback so TS side can show full details
        error_response = {
            "success": False,
            "message": f"Sync process failed: {short_exc}",
            "exception": short_exc,
            "traceback": tb
        }
        # Attempt to include any captured stderr content if present (best-effort)
        try:
            # If stderr was redirected to a file-like object, try to read from it if it's seekable
            if hasattr(original_stderr, 'name') and original_stderr.name and original_stderr.name != '<stderr>':
                try:
                    with open(original_stderr.name, 'r', encoding='utf-8', errors='ignore') as f:
                        stderr_contents = f.read()[-8000:]
                        error_response['stderr_tail'] = stderr_contents
                except Exception:
                    # ignore read failures
                    pass
        except Exception:
            pass
        # Attach diagnostics buffer if available
        try:
            error_response['_diagnostics'] = '\n'.join(
                str(item) for item in _DIAGNOSTICS_BUFFER)
        except Exception:
            pass
        # Print JSON error response
        print(json.dumps(error_response, ensure_ascii=False,
                         separators=(',', ':')), flush=True)
        sys.exit(1)


def _get_ollama_base_url(url: Optional[str]) -> str:
    """
    Ensure Ollama base URL ends with /v1, appending if missing.
    """
    if not url:
        return 'http://localhost:11434/v1'
    # Ensure URL ends with /v1
    if not url.endswith('/v1') and not url.endswith('/v1/'):
        return f'{url.rstrip("/")}/v1'
    return url.rstrip('/')  # Remove trailing slash if it exists


def create_embedder_client(config: BridgeConfig, debug: bool = False):
    """
    Create embedder client based on config.embedder_provider.
    This allows mixing LLM and embedding providers (e.g., Google AI LLM + OpenAI embeddings).

    graphiti_core's EmbedderConfig.embedding_dim defaults to a frozen 1024, and
    OpenAIEmbedder/VoyageAIEmbedder slice every real API response to it client-side --
    silently truncating any model with a native output >1024D unless embedding_dim is
    passed explicitly. NO_TRUNCATION_EMBEDDING_DIM below makes that slice a permanent
    no-op so callers always get the embedder's true native output length. See Day79.01.
    """
    logger = logging.getLogger('graphiti_bridge.sync')

    # Get embedder API key
    embedder_api_key = config.get_effective_embedder_api_key()

    # Create embedder client based on provider
    if config.embedder_provider == "openai":
        # OpenAI Embedder. NOTE: also fixes a separate, adjacent bug found while fixing the
        # above - this branch previously passed `model=config.embedding_model`, but
        # OpenAIEmbedderConfig's field is named `embedding_model`, not `model`. Pydantic
        # BaseModel silently drops unknown kwargs (verified: constructing
        # OpenAIEmbedderConfig(api_key=..., model=...) leaves embedding_model at its class
        # default 'text-embedding-3-small' with NO error), so every OpenAI-provider sync
        # ignored the user's configured embedding model entirely. Distinct defect from the
        # 1024D truncation bug - documented separately, fixed here since it is the same
        # three lines.
        OpenAIEmbedder, OpenAIEmbedderConfig = get_openai_embedder()
        embedder_config = OpenAIEmbedderConfig(
            api_key=embedder_api_key,
            embedding_model=config.embedding_model,
            embedding_dim=NO_TRUNCATION_EMBEDDING_DIM,
        )
        embedder = OpenAIEmbedder(config=embedder_config)

    elif config.embedder_provider == "google" or config.embedder_provider == "google-ai" or config.embedder_provider == "gemini":
        # Google/Gemini Embedder
        if not GEMINI_EMBEDDER_AVAILABLE or GeminiEmbedder is None:
            raise NotImplementedError(
                f"Gemini embedder requested but not available. Install with: pip install graphiti-core[google-genai]")

        embedder_config = GeminiEmbedderConfig(
            api_key=embedder_api_key,
            embedding_model=config.embedding_model
        )
        embedder = GeminiEmbedder(config=embedder_config)

    elif config.embedder_provider == "voyage":
        # Voyage AI Embedder. Same 1024D client-side truncation bug as the openai branch
        # above (VoyageAIEmbedder.create()/.create_batch() also slice via
        # `[: self.config.embedding_dim]` - ../graphiti/graphiti_core/embedder/voyage.py) -
        # fixed identically, not part of the reported incident but the same failure class
        # in the same function, per the "anywhere else" instruction.
        if not VOYAGE_EMBEDDER_AVAILABLE or VoyageAIEmbedder is None:
            raise NotImplementedError(
                f"Voyage embedder requested but not available. Install with: pip install voyageai")

        # Use VoyageAIEmbedderConfig format (from test file)
        embedder_config = VoyageAIEmbedderConfig(
            api_key=embedder_api_key,
            model=config.embedding_model,
            embedding_dim=NO_TRUNCATION_EMBEDDING_DIM,
        )
        embedder = VoyageAIEmbedder(config=embedder_config)

    elif config.embedder_provider == "azure" or config.embedder_provider == "azure-openai":
        # Azure OpenAI Embedder
        if not AZURE_EMBEDDER_AVAILABLE or AzureOpenAIEmbedderClient is None:
            raise NotImplementedError(
                f"Azure OpenAI embedder requested but not available")

        # Use Azure-specific configuration
        embedder = AzureOpenAIEmbedderClient(
            api_key=embedder_api_key,
            azure_endpoint=getattr(config, 'azure_endpoint', None),
            api_version=getattr(config, 'azure_api_version',
                                '2024-02-15-preview'),
            model=config.embedding_model
        )

    elif config.embedder_provider == "ollama":
        # Ollama Embedder (Local) - uses OpenAI embedder with custom base_url per Graphiti docs
        OpenAIEmbedder, OpenAIEmbedderConfig = get_openai_embedder()

        # Use OpenAI embedder with Ollama base URL (official Graphiti pattern). Same
        # client-side truncation risk as the openai/voyage/openrouter branches (an
        # Ollama model like mxbai-embed-large outputs 1024D, exceeding the 768D
        # config.ollama_embedding_dim default) -- pass the no-truncation sentinel here
        # too so the real native output length is always returned. See Day79.01 and
        # Day81.02 Task 4.
        ollama_base_url = _get_ollama_base_url(
            getattr(config, 'ollama_base_url', None))
        embedder_config = OpenAIEmbedderConfig(
            api_key="ollama",  # Placeholder API key as per Graphiti docs
            embedding_model=config.embedding_model,  # Corrected parameter name
            embedding_dim=NO_TRUNCATION_EMBEDDING_DIM,
            base_url=ollama_base_url
        )
        embedder = OpenAIEmbedder(config=embedder_config)

    elif config.embedder_provider == "openrouter":
        # OpenRouter Embedder — OpenAI-compatible endpoint with custom base_url.
        # This is the exact branch that produced the "openrouter/openai/text-embedding-3-small
        # produces 1024D" incident - see create_embedder_client() docstring for the full
        # root-cause writeup (graphiti_core's shared, frozen EmbedderConfig.embedding_dim
        # default of 1024, silently truncating OpenAIEmbedder's real API response on every
        # call because this branch never passed embedding_dim explicitly).
        OpenAIEmbedder, OpenAIEmbedderConfig = get_openai_embedder()
        embedder_config = OpenAIEmbedderConfig(
            api_key=embedder_api_key,
            embedding_model=config.embedding_model,
            embedding_dim=NO_TRUNCATION_EMBEDDING_DIM,
            base_url="https://openrouter.ai/api/v1"
        )
        embedder = OpenAIEmbedder(config=embedder_config)

    else:
        # Unsupported embedder provider
        raise NotImplementedError(
            f"Embedder provider '{config.embedder_provider}' is not supported. Supported: openai, google, voyage, azure, ollama, openrouter")

    if debug:
        logger.debug(
            f"Embedder: {config.embedder_provider} model={config.embedding_model}")

    return embedder


async def check_dimension_compatibility(graphiti, config: 'BridgeConfig', logger) -> tuple:
    """
    Pre-sync smoke test: verify that the configured embedder produces vectors with the same
    dimensions as those already stored in the database. Returns (ok, existing_dims, expected_dims).
    Never raises — on any failure returns (True, None, None) to avoid blocking sync.
    """
    try:
        # Step 1: Query DB for existing embedding dimensions
        existing_dims = None
        if config.database_type == 'neo4j':
            driver = getattr(graphiti, '_driver', None) or getattr(graphiti, 'driver', None)
            if driver:
                try:
                    query = (
                        "MATCH (n:Entity) WHERE n.name_embedding IS NOT NULL "
                        "RETURN size(n.name_embedding) AS dims LIMIT 1"
                    )
                    async with driver.session(database=config.database_name) as session:
                        result = await session.run(query)
                        record = await result.single()
                        if record:
                            existing_dims = record["dims"]
                except Exception as db_err:
                    logger.debug(f"[DIM-CHECK] DB query failed: {db_err}")
                    return True, None, None

        if existing_dims is None:
            return True, None, None  # Empty DB or unsupported DB type — no conflict possible

        # Step 2: Get dims from configured embedder via a test embedding
        expected_dims = None
        try:
            embedder_client = create_embedder_client(config, False)
            if embedder_client and hasattr(embedder_client, 'create'):
                test_vector = await embedder_client.create("dimension check")
                if isinstance(test_vector, list) and len(test_vector) > 0:
                    expected_dims = len(test_vector)
        except Exception as embed_err:
            logger.debug(f"[DIM-CHECK] Embedder test failed: {embed_err}")
            return True, None, None

        if expected_dims is None:
            return True, None, None

        # Step 3: Compare
        if existing_dims != expected_dims:
            return False, existing_dims, expected_dims
        return True, existing_dims, expected_dims

    except Exception as e:
        logger.debug(f"[DIM-CHECK] Dimension check skipped: {e}")
        return True, None, None


def _make_noop_cross_encoder():
    """
    Minimal stub satisfying Graphiti's cross_encoder constructor requirement.
    Graphiti hardcodes RRF for ranking internally; this arg is unused for add_episode
    and search. Passing None causes Graphiti to instantiate OpenAIRerankerClient() as
    its default, which crashes without OPENAI_API_KEY. This stub satisfies the
    interface silently with zero API calls.
    """
    from graphiti_core.llm_client.config import LLMConfig

    OpenAIRerankerClient = get_openai_reranker_client()
    noop = OpenAIRerankerClient(config=LLMConfig(api_key="noop", model="noop"))

    async def rank(query: str, passages: list, top_k=None):
        return [(p, 0.0) for p in passages]

    noop.rank = rank
    return noop


async def initialize_graphiti(config: BridgeConfig, debug: bool = False):
    """
    Initialize Graphiti with the provided configuration.
    This function now directly instantiates LLM and Embedder clients based on config.
    
    NOTE: This function is async in Graphiti 0.22+ to support async driver initialization.
    """
    logger = logging.getLogger('graphiti_bridge.sync')

    try:
        # Retrieve API keys robustly
        llm_api_key = None
        if hasattr(config, 'api_keys') and config.api_keys:
            llm_api_key = config.api_keys.get(config.llm_provider)
        if not llm_api_key and config.llm_api_key:
            llm_api_key = config.llm_api_key
        embedder_api_key = None
        # Assuming embedder API key is the same as LLM for now, or falls back to separate config field
        if hasattr(config, 'api_keys') and config.api_keys:
            # Using LLM provider key as a common fallback
            embedder_api_key = config.api_keys.get(config.llm_provider)
        if not embedder_api_key and config.embedder_api_key:  # If there's a specific embedder API key
            embedder_api_key = config.embedder_api_key
        if not embedder_api_key and config.llm_api_key:  # Fallback to LLM api key if no specific embedder key
            embedder_api_key = config.llm_api_key

        # =====================================================================
        # PROVIDER-SPECIFIC CLIENT CREATION (if/elif pattern)
        # =====================================================================

        # Create embedder client (separate from LLM provider for mix-and-match support)
        embedder_client = create_embedder_client(config, debug)

        if config.llm_provider == "openai":
            # ===== OPENAI PROVIDER =====
            if debug:
                logger.info(
                    f"OpenAI LLM: {config.llm_model}, Embedder: {config.embedder_provider}")

            # Check if the model supports reasoning parameters (o1-series models only)
            is_reasoning_model = any(config.llm_model.startswith(
                p) for p in ('o1-', 'o1_', 'o3-', 'o3_'))

            # Create OpenAI LLM client with model-specific configuration
            llm_config_params = {
                'api_key': llm_api_key,
                'model': config.llm_model,
                'small_model': getattr(config, 'llm_small_model', None),
                'base_url': getattr(config, 'llm_base_url', None)
            }

            # Create LLMConfig (reasoning parameters not supported in LLMConfig itself)
            llm_config = LLMConfig(**llm_config_params)

            # Prepare OpenAI client parameters with reasoning/verbosity handling
            client_params = {
                'config': llm_config,
                'cache': False
            }

            # Only add reasoning/verbosity parameters for o1-series models
            if is_reasoning_model:
                # Add reasoning effort for o1-series models (default to 'medium' if not specified)
                reasoning_effort = getattr(
                    config, 'reasoning_effort', 'medium')
                verbosity_level = getattr(config, 'verbosity_level', 'low')
                client_params['reasoning'] = reasoning_effort
                client_params['verbosity'] = verbosity_level
                if debug:
                    logger.debug(
                        f"Using reasoning model {config.llm_model} with reasoning: {reasoning_effort}, verbosity: {verbosity_level}")
            else:
                # Explicitly set reasoning and verbosity to None for non-o1 models
                client_params['reasoning'] = None
                client_params['verbosity'] = None
                if debug:
                    logger.debug(
                        f"Using standard GPT model {config.llm_model} - excluding reasoning/verbosity parameters")

            OpenAIClient = get_openai_client()
            llm_client = OpenAIClient(**client_params)

            cross_encoder = _make_noop_cross_encoder()

        elif config.llm_provider == "google" or config.llm_provider == "google-ai":
            # ===== GOOGLE AI PROVIDER =====
            if debug:
                logger.info(
                    f"Initializing Google AI provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")

            # Create Google AI LLM client using the factory function
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            GeminiClient = get_gemini_client()
            llm_client = GeminiClient(config=llm_config)
            if debug:
                logger.info(
                    f"Google AI LLM client instantiated with model: {config.llm_model}")

            cross_encoder = _make_noop_cross_encoder()

        elif config.llm_provider == "anthropic" or config.llm_provider == "claude":
            # ===== ANTHROPIC PROVIDER =====
            if debug:
                logger.info(
                    f"Initializing Anthropic provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")

            # Create Anthropic LLM client using the factory function
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            AnthropicClient = get_anthropic_client()
            llm_client = AnthropicClient(config=llm_config)
            if debug:
                logger.info(
                    f"Anthropic LLM client instantiated with model: {config.llm_model}")

            cross_encoder = _make_noop_cross_encoder()

        elif config.llm_provider == "ollama":
            # ===== OLLAMA PROVIDER =====
            if debug:
                logger.info(
                    f"Initializing Ollama provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")

            # Create Ollama LLM client using OpenAIGenericClient per Graphiti docs
            OllamaGenericClient, ensure_bounded_ollama_model, DERIVATIVE_STATE_FILENAME = get_ollama_client()
            ollama_base_url = _get_ollama_base_url(
                getattr(config, 'ollama_base_url', None))
            # For Ollama, ignore llm_small_model to improve structured JSON reliability
            ollama_small = None
            if debug and getattr(config, 'llm_small_model', None):
                logger.debug(
                    "Ollama provider: ignoring llm_small_model for structured JSON reliability")

            # Ollama's OpenAI-compat endpoint does not honor extra_body.num_ctx (verified
            # against Ollama 0.32.1) -- pre-create a bounded-context derivative model
            # instead. Soft-fails to the unbounded base model on any error so a broken
            # /api/create call never blocks a sync. See Day78.04b.
            ollama_num_ctx = int(getattr(config, 'ollama_num_ctx', 8192))
            ollama_llm_model = config.llm_model
            try:
                state_dir = getattr(config, 'models_path', None) or getattr(config, 'vault_path', None) or '.'
                llm_model_for_ollama = await ensure_bounded_ollama_model(
                    ollama_base_url=ollama_base_url,
                    base_model=config.llm_model,
                    num_ctx=ollama_num_ctx,
                    state_path=Path(state_dir) / DERIVATIVE_STATE_FILENAME,
                )
                ollama_llm_model = llm_model_for_ollama
            except Exception as e:
                logger.warning(
                    f"[Day78.04b] Could not create/verify bounded-context Ollama derivative model "
                    f"for '{config.llm_model}' (num_ctx={ollama_num_ctx}) — falling back to the base "
                    f"model unbounded. Error: {e}")

            llm_config = LLMConfig(
                api_key="ollama",
                model=ollama_llm_model,
                small_model=ollama_small,
                base_url=ollama_base_url
            )
            # OllamaGenericClient bounds call timeout and still passes num_ctx via
            # extra_body for non-Ollama backends that honor it. See Day78.04.
            llm_client = OllamaGenericClient(
                config=llm_config,
                num_ctx=ollama_num_ctx,
                timeout=float(getattr(config, 'timeout', 30)),
            )
            if debug:
                logger.info(
                    f"Ollama LLM client instantiated with model: {ollama_llm_model} "
                    f"(num_ctx={ollama_num_ctx}, timeout={getattr(config, 'timeout', 30)}s)")

            cross_encoder = _make_noop_cross_encoder()

        elif config.llm_provider == "venice":
            # ===== VENICE.AI PROVIDER =====
            if debug:
                logger.info(
                    f"Initializing Venice.ai provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")
            # Venice uses an OpenAI-compatible API surface; use OpenAIGenericClient with Venice base URL
            venice_base = "https://api.venice.ai/api/v1"
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=venice_base
            )
            OpenAIGenericClient = get_openai_generic_client()
            llm_client = OpenAIGenericClient(config=llm_config)
            if debug:
                logger.info(
                    f"Venice.ai LLM client instantiated with model: {config.llm_model} (base_url={venice_base})")

            cross_encoder = _make_noop_cross_encoder()

        elif config.llm_provider == "openrouter":
            # ===== OPENROUTER PROVIDER =====
            if debug:
                logger.info(
                    f"Initializing OpenRouter provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")
            
            # @purpose: Handle OpenRouter preset appending for custom model combinations @depends: preset settings @results: Model name with optional preset suffix
            processed_model = config.llm_model
            processed_small_model = getattr(config, 'llm_small_model', None)
            
            # Check for preset configuration with debug logging
            preset_slug = getattr(config, 'openrouter_preset_slug', None)
            use_preset_with_custom = getattr(config, 'openrouter_use_preset_with_custom_model', False)
            
            if debug:
                logger.info(f"OpenRouter preset config: slug='{preset_slug}', use_with_custom={use_preset_with_custom}")
                logger.debug(f"OpenRouter small model config: llm_small_model='{processed_small_model}'")
            
            if preset_slug and use_preset_with_custom:
                preset_suffix = f"@preset/{preset_slug}"
                
                # Append preset to main model if it's not already a preset model
                if processed_model and not processed_model.startswith('@preset/'):
                    processed_model = f"{processed_model}{preset_suffix}"
                    if debug:
                        logger.info(f"Appended preset to main model: {processed_model}")
                
                # Append preset to small model if it exists and is not already a preset model
                if processed_small_model and not processed_small_model.startswith('@preset/'):
                    processed_small_model = f"{processed_small_model}{preset_suffix}"
                    if debug:
                        logger.info(f"Appended preset to small model: {processed_small_model}")
            
            # OpenRouter uses an OpenAI-compatible API surface; use OpenAIGenericClient with OpenRouter base URL
            openrouter_base = "https://openrouter.ai/api/v1"
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=processed_model,
                small_model=processed_small_model,
                base_url=openrouter_base
            )
            # Use custom OpenRouter client for proper structured output handling
            OpenRouterClient = get_openrouter_client()
            llm_client = OpenRouterClient(config=llm_config)
            if debug:
                logger.info("Using custom OpenRouter client for proper structured output support")
            if debug:
                logger.info(
                    f"OpenRouter LLM client instantiated with model: {processed_model} (base_url={openrouter_base})")

            cross_encoder = _make_noop_cross_encoder()

        else:
            # ===== UNSUPPORTED PROVIDER =====
            raise NotImplementedError(
                f"LLM provider '{config.llm_provider}' is not yet supported. Supported providers: openai, google, anthropic, ollama, venice, openrouter")

        # Create database driver (v0.17.0+ pattern) - supports both Neo4j and FalkorDB

        db_type = getattr(config, 'database_type', 'neo4j').lower()

        if db_type == 'falkordb':
            # ===== FALKORDB DRIVER =====
            # Day86.02: get_falkor_driver() returns PinnedGraphFalkorDriver, a
            # graphiti_bridge subclass of graphiti_core's FalkorDriver whose clone()
            # ignores its database argument and always returns self. This is the
            # single choke point that neutralizes BOTH graphiti-core's add_episode/
            # add_episode_bulk-level reclone (graphiti_core/graphiti.py) AND every
            # FalkorDB ops file's independent get_by_group_ids() reclone -- both call
            # driver.clone(database=...) on this instance. Every FalkorDriver(...)
            # construction below therefore already produces a pinned driver; no
            # change to build_falkor_connection()'s connection-kwargs plumbing was
            # needed for this. See lazy_imports.get_falkor_driver().
            FalkorDriver, FALKORDB_AVAILABLE = get_falkor_driver()
            if not FALKORDB_AVAILABLE or FalkorDriver is None:
                raise NotImplementedError(
                    f"FalkorDB driver requested but not available. Install with: pip install graphiti-core[falkordb]")

            # Day86.01: connection kwargs now built by the single shared helper also
            # used by test_connections.py's probe (see build_falkor_connection()
            # docstring). Host/port regex parity with the original inline version is
            # preserved inside that helper.
            conn = build_falkor_connection(config)
            db_name = getattr(config, 'database_name', 'default_db') or 'default_db'

            if debug:
                logger.info(
                    f"Creating FalkorDB driver: {conn['host']}:{conn['port']} "
                    f"ssl={conn['ssl']} database={db_name}")

            if conn['ssl']:
                # No ssl kwarg exists on FalkorDriver itself -- pre-construct the raw
                # falkordb-py client with TLS enabled and hand it in via the falkor_db=
                # escape hatch. Confirmed safe: FalkorDriver never reconstructs
                # self.client outside __init__.
                FalkorDB = get_falkordb_client()
                falkor_db_instance = FalkorDB(
                    host=conn['host'],
                    port=conn['port'],
                    username=conn['username'],
                    password=conn['password'],
                    ssl=True,
                )
                driver = FalkorDriver(
                    falkor_db=falkor_db_instance,
                    database=db_name
                )
            else:
                # No TLS requested -- construct FalkorDriver directly exactly as before
                # Day86.01, so existing no-TLS/no-auth local Docker setups are unaffected.
                driver = FalkorDriver(
                    host=conn['host'],
                    port=conn['port'],
                    username=conn['username'],
                    password=conn['password'],
                    database=db_name
                )
        else:
            # ===== NEO4J DRIVER (DEFAULT) =====
            Neo4jDriver = get_neo4j_driver()

            driver = Neo4jDriver(
                uri=config.database_url,
                user=config.database_username,
                password=config.database_password,
                database=getattr(config, 'database_name', 'neo4j') or 'neo4j'
            )

        # Initialize Graphiti instance with driver and clients

        graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
            embedder=embedder_client,
            cross_encoder=cross_encoder,
            store_raw_episode_content=True
        )

        return graphiti

    except NotImplementedError as e:
        if debug:
            logger.error(f"Configuration Error: {e}")
        return None
    except Exception as e:
        # Always log initialization errors to help debug driver pattern issues
        if debug:
            logger.error(f"Failed to initialize Graphiti: {e}")
            logger.exception("Full exception details:")
            logger.error(
                "Ensure graphiti-core is installed and configured correctly.")
        import traceback
        return None


async def init_graphiti_bridge(config: BridgeConfig, debug: bool = False):
    """
    Public wrapper function for initializing Graphiti from external modules (like MCP server).

    This function provides a clean interface for the MCP server to initialize Graphiti
    using the same proven configuration and provider support.
    
    NOTE: This function is async in Graphiti 0.22+ to support async driver initialization.

    Args:
        config: BridgeConfig instance with provider and database settings
        debug: Enable debug logging

    Returns:
        Graphiti instance or None if initialization fails
    """
    return await initialize_graphiti(config, debug)


def extract_episode_uuid_from_result(graphiti_result, debug_mode: bool, logger) -> Optional[str]:
    """
    Extract the episode UUID from an AddEpisodeResults. graphiti-core 0.29.x's
    AddEpisodeResults.episode is a required EpisodicNode with a required uuid field --
    always present (verified against graphiti_core.graphiti.AddEpisodeResults).
    """
    if not graphiti_result:
        return None
    return str(graphiti_result.episode.uuid)


async def process_note(note_path: str, graphiti, logger, config: BridgeConfig) -> Optional[Dict[str, Any]]:
    """
    Process a single note file using correct Graphiti API
    Returns detailed result information or None if skipped
    """
    note_start_time = datetime.now()
    debug_mode = getattr(config, 'debug', False)  # Use config debug setting

    if debug_mode:
        logger.debug(f"Processing note: {note_path}")

    # Smart path resolution: only prepend vault_path if the note_path doesn't already include it
    full_note_path = note_path
    if hasattr(config, 'vault_path') and config.vault_path:
        # Get just the vault directory name
        vault_path_norm = Path(config.vault_path).name
        note_path_parts = Path(note_path).parts

        # Only prepend vault_path if the note_path doesn't start with the vault directory
        if not Path(note_path).is_absolute() and (not note_path_parts or note_path_parts[0] != vault_path_norm):
            full_note_path = str(Path(config.vault_path) / note_path)

    # Validate note file using resolved path
    if not validate_note_file(full_note_path):
        if debug_mode:
            logger.warning(
                f"Skipping invalid note file: {note_path} (resolved: {full_note_path})")
        return None

    try:
        # Read note content using resolved path
        with open(full_note_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract metadata and content
        metadata, text_content = extract_frontmatter(content)
        clean_text = extract_text_content(content)

        # Create episode name from file path
        note_name = Path(note_path).stem

        # Check if note should be processed (skip private notes)
        if metadata.get('private', False):
            if debug_mode:
                logger.debug(f"Skipping private note: {note_name}")
            return None

        # Get database type for compatibility handling
        database_type = getattr(config, 'database_type', 'neo4j')

        # Extract reference time from various possible metadata fields
        reference_time = extract_reference_time(
            metadata, logger, database_type)

        # Resolve namespace for episode (TS override takes precedence if provided)
        group_id_override = getattr(config, 'group_id', None)
        if group_id_override:
            group_id = str(group_id_override)
            if debug_mode:
                logger.debug(
                    f"Using group_id override from config: {group_id}")
        else:
            group_id = resolve_namespace(note_path, metadata, config, logger)

        # Resolve custom_extraction_instructions: namespace override > vault-level > None
        custom_extraction_instructions = None
        global_instructions = getattr(config, 'global_extraction_instructions', None) or None
        if hasattr(config, 'folder_namespace_mappings') and config.folder_namespace_mappings:
            try:
                note_posix = Path(note_path).as_posix()
                vault_posix = Path(getattr(config, 'vault_path', '') or '').as_posix().rstrip('/')
                rel_path = note_posix
                if vault_posix and note_posix.lower().startswith((vault_posix + '/').lower()):
                    rel_path = note_posix[len(vault_posix) + 1:]
                for mapping in config.folder_namespace_mappings:
                    folder_path = mapping.get('folderPath', '')
                    if folder_path and rel_path.lower().startswith(folder_path.lower().rstrip('/') + '/'):
                        ns_instructions = mapping.get('customExtractionInstructions') or None
                        custom_extraction_instructions = ns_instructions or global_instructions
                        break
            except Exception:
                pass
        if custom_extraction_instructions is None:
            custom_extraction_instructions = global_instructions

        # Phase 5: Wikilink extraction hints — inject [[wikilinks]] found in note as entity hints
        if getattr(config, 'wikilink_extraction_hints', True) and text_content:
            wikilinks = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', text_content)
            unique_links = list(dict.fromkeys(wikilinks))  # deduplicate, preserve order
            if unique_links:
                link_display = ', '.join(f'[[{lnk}]]' for lnk in unique_links[:30])  # cap at 30
                hint_block = (
                    f"\n\nThe following wiki-style links in the text represent known entity references "
                    f"in the user's knowledge base. Treat each as a likely entity: {link_display}. "
                    f"When a link uses alias format like [[target|display]], the target is the canonical entity name."
                )
                custom_extraction_instructions = (custom_extraction_instructions or '') + hint_block

        # Resolve saga name and previous episode UUID for timeline chaining
        saga_name = None
        saga_previous_uuid = None
        if hasattr(config, 'folder_namespace_mappings') and config.folder_namespace_mappings:
            try:
                note_posix = Path(note_path).as_posix()
                vault_posix = Path(getattr(config, 'vault_path', '') or '').as_posix().rstrip('/')
                rel_path = note_posix
                if vault_posix and note_posix.lower().startswith((vault_posix + '/').lower()):
                    rel_path = note_posix[len(vault_posix) + 1:]
                for mapping in config.folder_namespace_mappings:
                    folder_path = mapping.get('folderPath', '')
                    if folder_path and rel_path.lower().startswith(folder_path.lower().rstrip('/') + '/'):
                        saga_grouping = mapping.get('sagaGrouping', 'byNoteType')
                        saga_property_key = mapping.get('sagaPropertyKey')
                        note_type = metadata.get('type') if metadata else None
                        saga_name = resolve_saga_name(
                            saga_grouping, saga_property_key, group_id, note_type, metadata or {}
                        )
                        break
            except Exception:
                pass
        if saga_name:
            # Use DbConfig.id if passed from TypeScript (Day58); fall back to database_type
            db_id_for_saga = getattr(config, 'database_id', None) or getattr(config, 'database_type', 'neo4j')
            saga_previous_uuid = lookup_saga_previous_uuid_sqlite(
                saga_name, db_id_for_saga,
                getattr(config, 'vault_path', None), debug_mode, logger
            )
            if debug_mode:
                logger.debug(f"Saga: name='{saga_name}', db_id='{db_id_for_saga}', previous_uuid='{saga_previous_uuid}'")

        # Build episode_meta — injected into frontmatter after all field filtering, immune to Phase 2/3
        # Allows MCP search results to return vault path, vault_id, obsidian URL, and contributor
        episode_meta: Dict[str, str] = {}
        try:
            from urllib.parse import quote as _url_quote
            vault_path_str = (getattr(config, 'vault_path', '') or '').replace('\\', '/').rstrip('/')
            vault_name = Path(vault_path_str).name if vault_path_str else getattr(config, 'default_namespace', 'vault')
            note_posix = note_path.replace('\\', '/')
            # Use vault-relative path — what Obsidian MCP tools expect; vault_id disambiguates which vault
            if vault_path_str and note_posix.lower().startswith(vault_path_str.lower() + '/'):
                vault_rel = note_posix[len(vault_path_str) + 1:]
            else:
                vault_rel = note_posix
            episode_meta['mm_note_path'] = vault_rel
            episode_meta['mm_vault_id'] = vault_name
            episode_meta['mm_obsidian_url'] = f"obsidian://open?vault={_url_quote(vault_name)}&file={_url_quote(vault_rel, safe='/')}"
            contributor = getattr(config, 'episode_contributor', None) or ''
            if contributor:
                episode_meta['mm_contributor'] = contributor
        except Exception:
            pass

        # Reset token tracker before episode creation (Phase 4b)
        if hasattr(graphiti, 'token_tracker') and graphiti.token_tracker:
            try:
                graphiti.token_tracker.reset()
            except Exception:
                pass

        # Choose episode creation strategy based on ontology setting
        if config.use_custom_ontology:
            # Use custom entity episodes with Pydantic models
            graphiti_result = await create_custom_entity_episode(
                graphiti, note_name, clean_text, reference_time, group_id, metadata, logger, database_type, config, debug_mode, custom_extraction_instructions,
                saga_name=saga_name, saga_previous_uuid=saga_previous_uuid,
                episode_meta=episode_meta
            )
        else:
            # Use generic text episodes
            graphiti_result = await create_generic_text_episode(
                graphiti, note_name, clean_text, reference_time, group_id, logger, database_type, config, debug_mode, metadata, custom_extraction_instructions,
                saga_name=saga_name, saga_previous_uuid=saga_previous_uuid,
                episode_meta=episode_meta
            )

        # Read token usage after episode creation (Phase 4b)
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        if hasattr(graphiti, 'token_tracker') and graphiti.token_tracker:
            try:
                usage = graphiti.token_tracker.get_total_usage()
                if usage:
                    input_tokens = getattr(usage, 'input_tokens', 0) or 0
                    output_tokens = getattr(usage, 'output_tokens', 0) or 0
                    total_tokens = getattr(usage, 'total_tokens', None)
                    if total_tokens is None:
                        total_tokens = input_tokens + output_tokens
            except Exception:
                pass

        note_end_time = datetime.now()
        processing_duration = (note_end_time - note_start_time).total_seconds()

        # Log results based on episode creation success
        if graphiti_result:
            # Extract metrics if available
            entities_count = 0
            relationships_count = 0
            episode_uuid = None

            if hasattr(graphiti_result, 'nodes'):
                entities_count = len(graphiti_result.nodes)
            if hasattr(graphiti_result, 'edges'):
                relationships_count = len(graphiti_result.edges)
            elif hasattr(graphiti_result, 'relationships'):
                relationships_count = len(graphiti_result.relationships)
            community_count = len(graphiti_result.communities) if hasattr(graphiti_result, 'communities') and graphiti_result.communities else 0

            # Use the dedicated helper to extract the episode UUID
            episode_uuid = extract_episode_uuid_from_result(
                graphiti_result, debug_mode, logger)

            if debug_mode:
                logger.info(
                    f"Successfully processed '{note_name}' with namespace '{group_id}': {entities_count} entities, {relationships_count} relationships")

            result_dict = {
                'note_path': note_path,
                'note_name': note_name,
                'status': 'success',
                'namespace': group_id,
                'episode_uuid': episode_uuid,
                'saga_name': saga_name,
                'reference_time': reference_time.isoformat(),
                'processing_duration_seconds': processing_duration,
                'start_time': note_start_time.isoformat(),
                'end_time': note_end_time.isoformat(),
                # Analytics fields (Phase 5a) — consumed by SyncStorageService.recordSync()
                'entity_count': entities_count,
                'edge_count': relationships_count,
                'community_count': community_count,
                'sync_duration_ms': int(processing_duration * 1000),
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': total_tokens,
                'metrics': {
                    'entities_count': entities_count,
                    'relationships_count': relationships_count,
                    'content_length': len(clean_text),
                    'metadata_fields': len(metadata)
                }
                # REMOVED metadata and graphiti_response - they were causing massive output
            }
            return result_dict
        else:
            if debug_mode:
                logger.warning(
                    f"Episode creation returned no result for '{note_name}'")
            return {
                'note_path': note_path,
                'note_name': note_name,
                'status': 'failed',
                'namespace': group_id,
                'reference_time': reference_time.isoformat(),
                'processing_duration_seconds': processing_duration,
                'start_time': note_start_time.isoformat(),
                'end_time': note_end_time.isoformat(),
                'error': 'Episode creation returned no result'
                # REMOVED metadata - was causing massive output
            }

    except InfrastructureError as e:
        note_end_time = datetime.now()
        processing_duration = (note_end_time - note_start_time).total_seconds()
        
        if debug_mode:
            logger.error(f"Infrastructure error for note {note_path}: {e}")
        
        return {
            'note_path': note_path,
            'note_name': Path(note_path).stem,
            'status': 'infrastructure_error',
            'error': 'Service provider infrastructure issue - please try again later',
            'processing_duration_seconds': processing_duration,
            'start_time': note_start_time.isoformat(),
            'end_time': note_end_time.isoformat(),
            'provider_message': str(e),
            'cancel_sync': True  # Signal to cancel the entire sync operation
        }
    except Exception as e:
        note_end_time = datetime.now()
        processing_duration = (note_end_time - note_start_time).total_seconds()

        if debug_mode:
            logger.error(f"[SYNC-DEBUG] Exception type: {type(e).__name__}, repr: {repr(e)}")
            if hasattr(e, '__cause__') and e.__cause__ is not None:
                logger.error(f"[SYNC-DEBUG] Caused by: {type(e.__cause__).__name__}: {repr(e.__cause__)}")

        # Enhanced rate limiting detection with reset time parsing
        error_message = str(e).lower()
        original_error = str(e)  # Keep original case for parsing
        if 'http/1.1 400 bad request' in error_message or 'rate limit' in error_message or 'too many requests' in error_message or 'usage limits' in error_message:
            if debug_mode:
                logger.error(
                    f"API rate limit detected for note {note_path}: {e}")

            # Parse Anthropic-specific reset time: "You will regain access on 2025-10-01 at 00:00 UTC"
            retry_after = 60  # Default fallback
            reset_time = None

            # Try to parse Anthropic reset time format
            anthropic_pattern = r'You will regain access on (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) UTC'
            match = re.search(anthropic_pattern, original_error)
            if match:
                date_str = match.group(1)
                time_str = match.group(2)
                try:
                    reset_time = datetime.strptime(
                        f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    if reset_time > now:
                        retry_after = int((reset_time - now).total_seconds())
                        reset_time = reset_time.isoformat()
                except Exception:
                    pass  # Fall back to default

            # Check for generic retry-after patterns
            if retry_after == 60:  # Still using default
                retry_match = re.search(
                    r'retry[- ]?after[:\s]+(\d+)', original_error, re.IGNORECASE)
                if retry_match:
                    retry_after = int(retry_match.group(1))

            return {
                'note_path': note_path,
                'note_name': Path(note_path).stem,
                'status': 'rate_limited',
                'error': 'API rate limit exceeded - sync will pause until reset',
                'processing_duration_seconds': processing_duration,
                'start_time': note_start_time.isoformat(),
                'end_time': note_end_time.isoformat(),
                'retry_after': retry_after,
                'reset_time': reset_time,
                # First line of original error
                'provider_message': original_error.split('\n')[0]
            }

        if debug_mode:
            logger.exception(f"Failed to process note {note_path}: {e}")
        # Re-raise to be caught by the calling main function
        raise


def strip_wikilink_paths(text: str) -> str:
    """Strip relative path prefixes from wikilinks, keeping brackets intact.
    [[../../path/to/Name]] -> [[Name]]
    [[../../path/to/Name|Alias]] -> [[Alias]]
    [[Name]] -> [[Name]] (unchanged)
    [[Name|Alias]] -> [[Alias]]
    """
    def replacer(m):
        target = m.group(1)
        alias = m.group(2)
        if alias:
            return f'[[{alias}]]'
        return f'[[{target.split("/")[-1]}]]'
    return re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', replacer, text)


async def create_generic_text_episode(graphiti, note_name: str, clean_text: str,
                                      reference_time: datetime, group_id: str, logger, database_type: str = 'neo4j', config=None, debug_mode: bool = False, metadata: Optional[Dict[str, Any]] = None, custom_extraction_instructions: Optional[str] = None,
                                      saga_name: Optional[str] = None, saga_previous_uuid: Optional[str] = None,
                                      episode_meta: Optional[Dict[str, str]] = None):
    """Create a generic text episode using EpisodeType.text"""

    try:
        # FalkorDB (RedisGraph-family) rejects/mishandles naive (tz-unaware) datetimes;
        # Neo4j tolerates them. No upstream issue tracks this. See Day79.02 Task 4.
        if isinstance(reference_time, datetime):
            # Convert to timezone-aware datetime for FalkorDB compatibility
            if reference_time.tzinfo is None:
                formatted_reference_time = reference_time.replace(
                    tzinfo=timezone.utc)
            else:
                formatted_reference_time = reference_time
        else:
            formatted_reference_time = reference_time

        # Resolve source_description: sourceDescriptionKey lookup > frontmatter.type > config fallback
        # Issue #11: when source_description_key is configured in settings, read that frontmatter
        # property as the source_description override (wins over frontmatter.type). Full backward-
        # compat: when not configured, existing behavior (frontmatter.type → config fallback) is unchanged.
        frontmatter_type = None
        if metadata and isinstance(metadata, dict):
            frontmatter_type = metadata.get('type')
        source_description_key = getattr(config, 'source_description_key', None)
        key_override = (
            metadata.get(source_description_key)
            if (source_description_key and metadata and isinstance(metadata, dict))
            else None
        )
        if key_override:
            source_description = str(key_override)
        elif frontmatter_type:
            source_description = str(frontmatter_type)
        else:
            # Use note filename as source_description when no type (custom ontology disabled)
            source_description = (getattr(config, 'source_description', None) if config else None) or note_name or 'obsidian_mm_default'

        # Merge frontmatter into the body if metadata is provided; otherwise use body as-is
        merged_body = clean_text
        if isinstance(metadata, dict) and metadata:
            # Phase 2: strip globally ignored fields from episode body
            ignored = set(getattr(config, 'globally_ignored_fields', []) or [])
            filtered_metadata = {k: v for k, v in metadata.items() if k not in ignored}

            # Phase 3: strict property inclusion — only include properties enabled in ontology.json
            if getattr(config, 'property_inclusion_mode', 'permissive') == 'strict':
                note_type = filtered_metadata.get('type')
                enabled_props = getattr(config, 'enabled_properties', None) or {}
                if note_type and note_type in enabled_props:
                    allowed = set(enabled_props[note_type]) | {'type'}  # always keep type field
                    filtered_metadata = {k: v for k, v in filtered_metadata.items() if k in allowed}

            frontmatter_lines = ["---"]
            for k, v in filtered_metadata.items():
                if isinstance(v, (dict, list)):
                    val = json.dumps(v, default=str)
                else:
                    val = str(v)
                frontmatter_lines.append(f"{k}: {val}")
            # Always inject episode_meta (back-references) — immune to Phase 2/3 filtering
            for meta_key, meta_val in (episode_meta or {}).items():
                frontmatter_lines.append(f"{meta_key}: {meta_val}")
            frontmatter_lines.append("---")
            frontmatter_block = "\n".join(frontmatter_lines)
            merged_body = f"{frontmatter_block}\n{clean_text}"
            if debug_mode:
                logger.debug(
                    f"Frontmatter: {len(filtered_metadata)} fields attached to body (filtered from {len(metadata)})")
        merged_body = strip_wikilink_paths(merged_body)
        episode_kwargs = {
            'name': note_name,
            'episode_body': merged_body,
            'source': EpisodeType.text,
            'source_description': source_description,
            'reference_time': formatted_reference_time
        }
        # group_id passed for all backends (previously Neo4j-only; FalkorDB episodes
        # landed in one undifferentiated graph). Omitted only when empty, since an
        # explicit '' clones a distinct empty-string-named graph on FalkorDB, while
        # omitting the kwarg keeps writes on the driver's configured database on both
        # backends. See Day79.02 Task 4.
        if group_id:
            episode_kwargs['group_id'] = group_id

        # Phase 3 token-cost fix: cap prior episode context (v0.29.0 upgrade).
        # Saga path: TS side passes explicit UUIDs via config.previous_episode_uuids — use as-is.
        # No-saga path: Graphiti default fetches last_n=10 (RELEVANT_SCHEMA_LIMIT), bloating prompts
        # ~40-50%. We fetch only previous_episodes_limit (default 2) and pass UUIDs explicitly.
        prev_uuids = getattr(config, 'previous_episode_uuids', None)
        if prev_uuids is None:
            limit = getattr(config, 'previous_episodes_limit', 2)
            recent = await graphiti.retrieve_episodes(
                formatted_reference_time, last_n=limit, group_ids=[group_id]
            )
            prev_uuids = [ep.uuid for ep in recent]
            if debug_mode:
                logger.debug(f"previous_episode_uuids: fetched {len(prev_uuids)} recent (limit={limit})")
        elif debug_mode:
            logger.debug(f"previous_episode_uuids: saga-provided {len(prev_uuids)} UUID(s)")
        episode_kwargs['previous_episode_uuids'] = prev_uuids

        # Inject custom extraction instructions when provided (Graphiti v0.28.1+)
        if custom_extraction_instructions:
            episode_kwargs['custom_extraction_instructions'] = custom_extraction_instructions

        # Inject saga name and previous episode UUID for timeline chaining (Graphiti v0.28.1+)
        if saga_name:
            episode_kwargs['saga'] = saga_name
        if saga_previous_uuid:
            episode_kwargs['saga_previous_episode_uuid'] = saga_previous_uuid

        # Create episode with database-specific parameters
        result = await graphiti.add_episode(**episode_kwargs)

        return result

    except Exception:
        raise


def resolve_dynamic_rule(metadata: Optional[Dict[str, Any]], config) -> Optional[Dict[str, Any]]:
    """Resolve which Dynamic Ontology Rule (Day59.01) applies to this note.

    Evaluates config.dynamic_rules top to bottom, first match wins. A rule matches when
    its matchField is the wildcard '*' (or its matchValues contains '*'), or when
    metadata[matchField] is present in matchValues. Disabled rules are skipped.

    Returns None when dynamic_rules is absent/empty or no rule matches — callers must treat
    None as "no filtering" (byte-identical to pre-Day59.01 behaviour), not as an error.
    """
    rules = getattr(config, 'dynamic_rules', None) if config is not None else None
    if not rules:
        return None

    for rule in rules:
        if not rule.get('enabled', True):
            continue
        match_field = rule.get('matchField') or rule.get('match_field')
        match_values = rule.get('matchValues') or rule.get('match_values') or []
        if match_field == '*' or '*' in match_values:
            return rule
        if not match_field:
            continue
        field_value = metadata.get(match_field) if isinstance(metadata, dict) else None
        if field_value is not None and str(field_value) in match_values:
            return rule

    return None


def apply_dynamic_rule_filter(entity_types: Dict[str, Any], edge_types: Dict[str, Any],
                               edge_type_map: Dict[tuple, List[str]], rule: Dict[str, Any],
                               logger) -> tuple:
    """Filter entity_types/edge_types/edge_type_map per the resolved Dynamic Ontology Rule
    (Day59.01) before they reach graphiti.add_episode().

    Axes (per Day59.01 DevDoc — property filtering is explicitly OUT of scope):
      1. includedEntityTypes — None means include all (including 'BaseEntity', a MegaMem-only
         construct synthesized in models.py, not a graphiti-core requirement).
      2. includedEdgeTypes — None means include all.
      3. edge_type_map filtered to pairs where both source and target survive axis 1 — EXCEPT
         wildcard 'X -> Entity' entries, which survive whenever X survives. 'Entity' is
         graphiti-core's universal base label (every node carries it in addition to its custom
         type), not a real compiled entity type — it must never be required to independently
         survive axis 1, and a literal ('Entity', 'Entity') entry must never be synthesized here
         (it would match every node pair and defeat the filter).
    """
    included_entity_types = rule.get('includedEntityTypes')
    included_edge_types = rule.get('includedEdgeTypes')

    if included_entity_types is None:
        filtered_entity_types = entity_types
    else:
        allowed_entities = set(included_entity_types)
        filtered_entity_types = {k: v for k, v in entity_types.items() if k in allowed_entities}

    if included_edge_types is None:
        filtered_edge_types = edge_types
    else:
        allowed_edges = set(included_edge_types)
        filtered_edge_types = {k: v for k, v in edge_types.items() if k in allowed_edges}

    if included_entity_types is None:
        filtered_edge_type_map = edge_type_map
    else:
        allowed_entities = set(included_entity_types)
        filtered_edge_type_map = {}
        for (source, target), edges in edge_type_map.items():
            source_survives = source in allowed_entities
            # Wildcard preservation: 'Entity' target survives whenever the source survives.
            target_survives = (target == 'Entity') or (target in allowed_entities)
            if source_survives and target_survives:
                filtered_edge_type_map[(source, target)] = edges

    logger.info(
        f"Dynamic Ontology Rule '{rule.get('name', rule.get('id', '?'))}' applied: "
        f"entity_types {len(entity_types)}->{len(filtered_entity_types)}, "
        f"edge_types {len(edge_types)}->{len(filtered_edge_types)}, "
        f"edge_type_map {len(edge_type_map)}->{len(filtered_edge_type_map)}"
    )

    return filtered_entity_types, filtered_edge_types, filtered_edge_type_map


async def create_custom_entity_episode(graphiti, note_name: str, clean_text: str,
                                       reference_time: datetime, group_id: str,
                                       metadata: Dict[str, Any], logger, database_type: str = 'neo4j', config=None, debug_mode: bool = False, custom_extraction_instructions: Optional[str] = None,
                                       saga_name: Optional[str] = None, saga_previous_uuid: Optional[str] = None,
                                       episode_meta: Optional[Dict[str, str]] = None):
    """Create a custom entity episode using Graphiti Custom Entities API"""

    try:
        # FalkorDB (RedisGraph-family) rejects/mishandles naive (tz-unaware) datetimes;
        # Neo4j tolerates them. No upstream issue tracks this. See Day79.02 Task 4.
        if isinstance(reference_time, datetime):
            # Convert to timezone-aware datetime for FalkorDB compatibility
            if reference_time.tzinfo is None:
                formatted_reference_time = reference_time.replace(
                    tzinfo=timezone.utc)
            else:
                formatted_reference_time = reference_time
        else:
            formatted_reference_time = reference_time

        # Get custom schema in Graphiti format (lists of classes and tuple-key dict)
        entity_types = get_graphiti_entity_types()
        edge_types = get_graphiti_edge_types()
        edge_type_map = get_graphiti_edge_type_map()

        # Dynamic Ontology Rules (Day59.01) — narrow the ontology actually sent to add_episode()
        # per note type, before the "no entity types" fallback below so the check reflects what
        # will really be sent. resolve_dynamic_rule() returns None when dynamic_rules is
        # absent/empty or nothing matches — filtering is skipped entirely in that case, which is
        # byte-identical to pre-Day59.01 behaviour.
        dynamic_rule = resolve_dynamic_rule(metadata, config)
        if dynamic_rule is not None:
            entity_types, edge_types, edge_type_map = apply_dynamic_rule_filter(
                entity_types, edge_types, edge_type_map, dynamic_rule, logger)

        # No custom entity types available, fall back to generic episode
        if not entity_types:
            return await create_generic_text_episode(graphiti, note_name, clean_text, reference_time, group_id, logger, database_type, config, custom_extraction_instructions=custom_extraction_instructions, saga_name=saga_name, saga_previous_uuid=saga_previous_uuid, episode_meta=episode_meta)

        # Resolve source_description: sourceDescriptionKey lookup > frontmatter.type > config fallback
        # Issue #11: when source_description_key is configured in settings, read that frontmatter
        # property as the source_description override (wins over frontmatter.type). Full backward-
        # compat: when not configured, existing behavior (frontmatter.type → config fallback) is unchanged.
        frontmatter_type = None
        if metadata and isinstance(metadata, dict):
            frontmatter_type = metadata.get('type')
        source_description_key = getattr(config, 'source_description_key', None)
        key_override = (
            metadata.get(source_description_key)
            if (source_description_key and metadata and isinstance(metadata, dict))
            else None
        )
        if key_override:
            source_description = str(key_override)
        elif frontmatter_type:
            source_description = str(frontmatter_type)
        else:
            source_description = (getattr(config, 'source_description', None) if config else None) or note_name or 'obsidian_mm_default'

        # Merge frontmatter into the body
        merged_body = clean_text
        if isinstance(metadata, dict) and metadata:
            # Phase 2: strip globally ignored fields from episode body
            ignored = set(getattr(config, 'globally_ignored_fields', []) or [])
            filtered_metadata = {k: v for k, v in metadata.items() if k not in ignored}

            # Phase 3: strict property inclusion — only include properties enabled in ontology.json
            if getattr(config, 'property_inclusion_mode', 'permissive') == 'strict':
                note_type = filtered_metadata.get('type')
                enabled_props = getattr(config, 'enabled_properties', None) or {}
                if note_type and note_type in enabled_props:
                    allowed = set(enabled_props[note_type]) | {'type'}
                    filtered_metadata = {k: v for k, v in filtered_metadata.items() if k in allowed}

            frontmatter_lines = ["---"]
            for k, v in filtered_metadata.items():
                if isinstance(v, (dict, list)):
                    val = json.dumps(v, default=str)
                else:
                    val = str(v)
                frontmatter_lines.append(f"{k}: {val}")
            # Always inject episode_meta (back-references) — immune to Phase 2/3 filtering
            for meta_key, meta_val in (episode_meta or {}).items():
                frontmatter_lines.append(f"{meta_key}: {meta_val}")
            frontmatter_lines.append("---")
            frontmatter_block = "\n".join(frontmatter_lines)
            merged_body = f"{frontmatter_block}\n{clean_text}"
            if debug_mode:
                logger.debug(
                    f"Frontmatter: {len(filtered_metadata)} fields attached to body (filtered from {len(metadata)})")
        merged_body = strip_wikilink_paths(merged_body)
        episode_kwargs = {
            'name': note_name,
            'episode_body': merged_body,
            'source': EpisodeType.text,
            'source_description': source_description,
            'reference_time': formatted_reference_time,
            'entity_types': entity_types,
            'edge_types': edge_types,
            'edge_type_map': edge_type_map
        }

        # group_id passed for all backends (previously Neo4j-only; FalkorDB episodes
        # landed in one undifferentiated graph). Omitted only when empty -- see the
        # matching comment at the create_generic_text_episode site above. See Day79.02 Task 4.
        if group_id:
            episode_kwargs['group_id'] = group_id

        # Phase 3 token-cost fix: cap prior episode context (v0.29.0 upgrade).
        # Saga path: TS side passes explicit UUIDs via config.previous_episode_uuids — use as-is.
        # No-saga path: Graphiti default fetches last_n=10 (RELEVANT_SCHEMA_LIMIT), bloating prompts
        # ~40-50%. We fetch only previous_episodes_limit (default 2) and pass UUIDs explicitly.
        prev_uuids = getattr(config, 'previous_episode_uuids', None)
        if prev_uuids is None:
            limit = getattr(config, 'previous_episodes_limit', 2)
            recent = await graphiti.retrieve_episodes(
                formatted_reference_time, last_n=limit, group_ids=[group_id]
            )
            prev_uuids = [ep.uuid for ep in recent]
            if debug_mode:
                logger.debug(f"previous_episode_uuids: fetched {len(prev_uuids)} recent (limit={limit})")
        elif debug_mode:
            logger.debug(f"previous_episode_uuids: saga-provided {len(prev_uuids)} UUID(s)")
        episode_kwargs['previous_episode_uuids'] = prev_uuids

        # Inject custom extraction instructions when provided (Graphiti v0.28.1+)
        if custom_extraction_instructions:
            episode_kwargs['custom_extraction_instructions'] = custom_extraction_instructions

        # Inject saga name and previous episode UUID for timeline chaining (Graphiti v0.28.1+)
        if saga_name:
            episode_kwargs['saga'] = saga_name
        if saga_previous_uuid:
            episode_kwargs['saga_previous_episode_uuid'] = saga_previous_uuid

        # Create custom entity episode using Graphiti Custom Entities API
        result = await graphiti.add_episode(**episode_kwargs)

        return result

    except Exception:
        # Day81.02 Task 1: no silent fallback -- a custom-entity episode failure must
        # not degrade to a generic episode missing ontology typing, frontmatter, and
        # mm_note_path/mm_vault_id/mm_obsidian_url back-references while still
        # reporting success. Re-raise so process_note()'s exception handling marks
        # the note status: failed.
        raise


def resolve_namespace(note_path: str, metadata: Dict[str, Any], config: BridgeConfig, logger) -> str:
    """
    Resolve the namespace (group_id) for an episode based on priority order:
    1. Property namespacing (highest priority): g_group_id in frontmatter
    2. Folder namespacing: Custom folder mappings from folderNamespaceMappings
    3. Namespace strategy: vault name or defaultNamespace
    """
    debug_mode = getattr(config, 'debug', False)

    try:
        # 1. Property namespacing (highest priority) — mm_group_id preferred, g_group_id deprecated
        if config.enable_property_namespacing and metadata:
            namespace = None
            if 'mm_group_id' in metadata:
                namespace = str(metadata['mm_group_id']).strip() or None
            elif 'g_group_id' in metadata:
                namespace = str(metadata['g_group_id']).strip() or None
                if namespace:
                    # Phase 6: deprecation warning for old field name
                    logger.warning("Frontmatter field 'g_group_id' is deprecated; rename to 'mm_group_id'")
            if namespace:
                if debug_mode:
                    logger.debug(f"Using property namespace: {namespace}")
                return namespace

        # 2. Folder namespacing (second priority)
        if config.enable_folder_namespacing:
            if debug_mode:
                logger.debug(
                    f"Folder namespacing enabled, checking for custom mappings")
            if hasattr(config, 'folder_namespace_mappings') and config.folder_namespace_mappings:
                # Normalize to vault-relative path for matching (align with TS logic)
                try:
                    note_posix = Path(note_path).as_posix()
                    vault_posix = Path(
                        getattr(config, 'vault_path', '') or '').as_posix().rstrip('/')
                    if vault_posix and note_posix.lower().startswith((vault_posix + '/').lower()):
                        note_path_for_mapping = note_posix[len(
                            vault_posix) + 1:]
                    else:
                        note_path_for_mapping = note_posix
                except Exception:
                    note_path_for_mapping = str(note_path).replace('\\', '/')
                if debug_mode:
                    logger.debug(
                        f"Found {len(config.folder_namespace_mappings)} custom folder mappings; matching with '{note_path_for_mapping}'")
                custom_group_id = _resolve_custom_folder_mapping(
                    note_path_for_mapping, config.folder_namespace_mappings, debug_mode, logger)
                if custom_group_id:
                    if debug_mode:
                        logger.debug(
                            f"Using custom folder mapping: {custom_group_id}")
                    return custom_group_id
            else:
                if debug_mode:
                    logger.debug(
                        f"No custom folder mappings available: hasattr={hasattr(config, 'folder_namespace_mappings')}, mappings={getattr(config, 'folder_namespace_mappings', None)}")

        # 3. Namespace strategy (lowest priority)
        if config.namespace_strategy == 'vault':
            # Resolve the actual vault name from config.vault_path (Day86.02 Task 2 fix —
            # previously this echoed default_namespace verbatim and never looked at the vault)
            vault_name = _extract_vault_name_from_path(
                note_path, getattr(config, 'vault_path', None), config.default_namespace, debug_mode, logger)
            if debug_mode:
                logger.debug(f"Using vault namespace: {vault_name}")
            return vault_name

        elif config.namespace_strategy == 'custom':
            # Use custom default namespace
            if debug_mode:
                logger.debug(
                    f"Using custom namespace: {config.default_namespace}")
            return config.default_namespace

        else:
            # Fallback to default namespace for any other strategy
            if debug_mode:
                logger.debug(
                    f"Using default namespace: {config.default_namespace}")
            return config.default_namespace

    except Exception:
        # Day81.02 Task 5: group_id is the partition boundary and the only permissible
        # publish predicate -- silently routing a note to default_namespace on any
        # resolution error while still reporting success is a defect, not a safety net.
        # Fail loudly so process_note()'s caller reports status: failed instead.
        raise


def _extract_vault_name_from_path(note_path: str, vault_path: Optional[str], default_namespace: str, debug_mode: bool, logger) -> str:
    """
    Resolve the real vault name for the 'vault' namespace strategy.

    Day86.02 Task 2: this previously ignored note_path/vault_path entirely and just
    echoed default_namespace back, making the 'vault' strategy a passthrough and the
    multi-vault case impossible (two vaults sharing one config collapsed to the same
    group_id). It now derives the vault name from config.vault_path using the same
    Path(vault_path_str).name pattern already used elsewhere in this file for
    mm_vault_id / mm_obsidian_url construction (see episode_meta build, ~line 1244-1245),
    so it actually resolves vault identity rather than passing through whatever
    default_namespace happens to be configured.
    """
    try:
        vault_path_str = (vault_path or '').replace('\\', '/').rstrip('/')
        if vault_path_str:
            vault_name = Path(vault_path_str).name
            if vault_name:
                if debug_mode:
                    logger.debug(f"Resolved vault name '{vault_name}' from vault_path")
                return vault_name

        # vault_path is genuinely unavailable (or resolved to an empty name) at this
        # call site -- say so explicitly rather than silently falling back to
        # default_namespace as if it were a real vault-name resolution.
        logger.warning(
            f"namespace_strategy='vault' but no usable vault_path was available to "
            f"resolve the vault name for note_path={note_path!r} (vault_path={vault_path!r}); "
            f"falling back to default_namespace={default_namespace!r} instead of the "
            f"actual vault name."
        )
        return default_namespace
    except Exception as e:
        logger.warning(f"Error extracting vault name from vault_path={vault_path!r}: {e}")
        return default_namespace


def _resolve_custom_folder_mapping(note_path: str, folder_mappings: list, debug_mode: bool, logger) -> Optional[str]:
    """
    Resolve custom folder mapping using longest-path-first algorithm.
    Matches TypeScript implementation in SyncRegistryService.generateGroupId().
    """
    if not folder_mappings:
        return None

    try:
        # Normalize the note path for consistent matching
        note_path_normalized = Path(note_path).as_posix()

        # Extract folder path from note path (remove filename)
        path_parts = note_path_normalized.split('/')
        note_folder_path = '/'.join(path_parts[:-1]
                                    ) if len(path_parts) > 1 else ''

        # Sort mappings by path length (longest first) for most specific matches
        sorted_mappings = sorted(
            folder_mappings,
            key=lambda m: len(m.get('folderPath', '') if isinstance(
                m, dict) else getattr(m, 'folderPath', '')),
            reverse=True
        )

        if debug_mode:
            logger.debug(
                f"Checking {len(sorted_mappings)} folder mappings for path: {note_path_normalized}")

        for mapping in sorted_mappings:
            # Handle both dict and object formats
            if isinstance(mapping, dict):
                folder_path = mapping.get('folderPath', '')
                group_id = mapping.get('groupId', '')
            else:
                folder_path = getattr(mapping, 'folderPath', '')
                group_id = getattr(mapping, 'groupId', '')

            if not folder_path or not group_id:
                continue

            # Normalize mapping path for consistent comparison
            folder_path_normalized = Path(folder_path).as_posix()

            # Check if note's folder path matches the mapped folder path exactly or is a subfolder
            if note_folder_path == folder_path_normalized or note_folder_path.startswith(folder_path_normalized + '/'):
                if debug_mode:
                    logger.debug(
                        f"Found matching folder mapping: '{folder_path_normalized}' -> '{group_id}'")
                return group_id

        if debug_mode:
            logger.debug(
                f"No custom folder mapping found for path: {note_path_normalized}")
        return None

    except Exception as e:
        if debug_mode:
            logger.warning(f"Error in custom folder mapping resolution: {e}")
        return None


def resolve_saga_name(
    saga_grouping: str,
    saga_property_key: Optional[str],
    group_id: str,
    note_type: Optional[str],
    frontmatter: dict,
) -> Optional[str]:
    """Resolve the saga name for an episode based on namespace saga grouping strategy."""
    if saga_grouping == 'none':
        return None
    if saga_grouping == 'singleSaga':
        return f"all-{group_id}"
    if saga_grouping == 'customProperty' and saga_property_key:
        prop_value = frontmatter.get(saga_property_key)
        if prop_value:
            safe = str(prop_value).lower().replace(' ', '-')[:80]
            return f"{safe}-{group_id}"
        return None  # no value = no saga
    # default: byNoteType
    if note_type:
        safe_type = str(note_type).lower().replace(' ', '-')[:40]
        return f"{safe_type}-{group_id}"
    return None  # no type = no saga


def lookup_saga_previous_uuid(saga_name: str, sync_records: list) -> Optional[str]:
    """Find the most recent episode UUID in a saga from existing sync records (legacy JSON fallback)."""
    matching = [
        entry
        for record in sync_records
        for entry in record.get('syncs', [])
        if entry.get('saga_name') == saga_name and entry.get('episode_uuid')
    ]
    if not matching:
        return None
    matching.sort(key=lambda e: e.get('last_sync', ''), reverse=True)
    return matching[0].get('episode_uuid')


def lookup_saga_previous_uuid_sqlite(
    saga_name: str,
    db_id: str,
    vault_path: Optional[str],
    debug_mode: bool,
    logger,
) -> Optional[str]:
    """
    Find the most recent episode UUID for a saga via SQLite O(log n) indexed query.
    Falls back to the JSON scan if sync.db doesn't exist yet (pre-migration).
    """
    if not saga_name or not vault_path:
        return None

    db_path = Path(vault_path) / '.obsidian' / 'plugins' / 'megamem-mcp' / 'sync.db'
    if db_path.exists():
        try:
            import sqlite3 as _sqlite3
            with _sqlite3.connect(str(db_path), timeout=5.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                row = conn.execute(
                    "SELECT episode_uuid FROM sync_records "
                    "WHERE saga_name=? AND db_id=? AND status='synced' "
                    "ORDER BY synced_at DESC LIMIT 1",
                    (saga_name, db_id),
                ).fetchone()
            if row and row[0]:
                if debug_mode and logger:
                    logger.debug(f"SQLite saga lookup: saga='{saga_name}' db='{db_id}' → {row[0]}")
                return row[0]
        except Exception as exc:
            if debug_mode and logger:
                logger.debug(f"SQLite saga lookup failed, falling back to JSON: {exc}")

    # Fallback: JSON scan (pre-migration or if SQLite unavailable)
    sync_records = _load_sync_records(vault_path, debug_mode, logger)
    return lookup_saga_previous_uuid(saga_name, sync_records)


def _load_sync_records(vault_path: Optional[str], debug_mode: bool, logger) -> list:
    """Load sync records from sync.json for legacy saga chain lookups (pre-SQLite-migration)."""
    if not vault_path:
        return []
    sync_json_path = Path(vault_path) / '.obsidian' / 'plugins' / 'megamem-mcp' / 'sync.json'
    try:
        if sync_json_path.exists():
            with open(sync_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('sync_records', [])
    except Exception as e:
        if debug_mode and logger:
            logger.debug(f"Could not load sync records for saga lookup: {e}")
    return []


def extract_reference_time(metadata: Dict[str, Any], logger, database_type: str = 'neo4j') -> datetime:
    """Extract reference time from various possible metadata fields"""
    reference_time = None
    for time_field in ['date', 'created', 'created_at', 'timestamp', 'modified']:
        if time_field in metadata and metadata[time_field]:
            try:
                # Handle various datetime formats
                if isinstance(metadata[time_field], str):
                    # Try common ISO formats
                    for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                        try:
                            reference_time = datetime.strptime(
                                metadata[time_field], fmt)
                            break
                        except ValueError:
                            continue
                elif hasattr(metadata[time_field], 'strftime'):
                    # Handle both datetime.date and datetime.datetime objects
                    if hasattr(metadata[time_field], 'tzinfo'):
                        # It's already a datetime object
                        reference_time = metadata[time_field]
                    else:
                        # It's a date object, convert to datetime
                        import datetime as dt
                        if isinstance(metadata[time_field], dt.date):
                            reference_time = datetime.combine(
                                metadata[time_field], datetime.min.time())
                        else:
                            reference_time = metadata[time_field]
            except Exception:
                # Silent failure - continue to next field or use current time
                pass
            if reference_time:
                break

    # Use current time if no reference time found
    if not reference_time:
        if database_type == 'falkordb':
            # FalkorDB rejects/mishandles naive datetimes. See Day79.02 Task 4.
            reference_time = datetime.now(timezone.utc)
        else:
            reference_time = datetime.now()
    else:
        # FalkorDB rejects/mishandles naive datetimes. See Day79.02 Task 4.
        if database_type == 'falkordb' and hasattr(reference_time, 'tzinfo') and reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

    return reference_time


if __name__ == "__main__":
    asyncio.run(main())
