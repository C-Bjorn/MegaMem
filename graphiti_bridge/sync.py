#!/usr/bin/env python3
"""
Graphiti Bridge Sync Script

Main script for syncing Obsidian notes with Graphiti temporal knowledge graphs.
This script is called by the TypeScript plugin and handles the sync process for a single note.
"""

# Performance optimization flags
import json
from graphiti_core.llm_client.gemini_client import GeminiClient
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EpisodicNode
from graphiti_core.utils.bulk_utils import RawEpisode
from graphiti_core.nodes import EpisodeType
from graphiti_core import Graphiti
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
import argparse
import traceback
import sys
import asyncio
import logging
import time
import os
SKIP_BGE_IMPORT = os.getenv('SKIP_BGE_IMPORT', 'false').lower() == 'true'
SKIP_GEMINI_IMPORT = os.getenv('SKIP_GEMINI_IMPORT', 'false').lower() == 'true'
SKIP_VOYAGE_IMPORT = os.getenv('SKIP_VOYAGE_IMPORT', 'false').lower() == 'true'

# Diagnostics buffer collected during run and attached to stdout JSON so callers that
# only capture stdout (and not stderr) will still receive critical diagnostic messages.
_DIAGNOSTICS_BUFFER = []

# Import timing removed - not useful in production
try:
    # UTF-8 stdout encoding for Windows environments
    if hasattr(sys, 'stdout') and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    else:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# Import timing removed - not useful in production

# Cross-encoder imports with graceful fallbacks
# LAZY IMPORT: BGE will be imported only when actually needed to avoid 35s startup
BGE_CROSS_ENCODER_AVAILABLE = None  # Will check on first use
BGERerankerClient = None

# Global cache for BGE cross-encoder to prevent repeated HuggingFace downloads
_BGE_CROSS_ENCODER_INSTANCE = None

GEMINI_CROSS_ENCODER_AVAILABLE = False
GeminiRerankerClient = None
try:
    from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
    GEMINI_CROSS_ENCODER_AVAILABLE = True
except ImportError:
    pass  # Gemini cross-encoder not available (requires google-genai)

# OpenAI cross-encoder always available (already imported above)
OPENAI_CROSS_ENCODER_AVAILABLE = True


# FalkorDB driver import with graceful fallback
FALKORDB_AVAILABLE = False
FalkorDriver = None
try:
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    FALKORDB_AVAILABLE = True
except ImportError:
    pass  # FalkorDB driver not available

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
    print_error_and_exit
)
from .models import initialize_global_loader, get_node_types, get_edge_types, get_entity_type_definitions, get_edge_type_definitions, get_edge_type_map, get_graphiti_entity_types, get_graphiti_edge_types, get_graphiti_edge_type_map
from .openrouter_client import OpenRouterClient, InfrastructureError


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
            # Redirect stderr to devnull to suppress ALL library output
            # sys.stderr = open(os.devnull, 'w')

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

        # Network debugging and initialization
        if debug_mode:
            logger.info("Starting Graphiti Bridge sync process")

            # Import timing removed - not useful in production

        # Validate configuration
        validation_errors = config.validate()
        if validation_errors:
            error_msg = f"Configuration validation failed: {'; '.join(validation_errors)}"
            if config.debug:
                logger.error(f"Validation failed: {error_msg}")
            print_error_and_exit(error_msg)

        # Set up environment variables for providers
        setup_environment_variables(config)

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

        # Validate that we have exactly one note
        if len(config.notes) != 1:
            print_error_and_exit(
                f"Expected exactly 1 note, got {len(config.notes)}")

        # Process note with timing
        note_processing_start = time.time()
        if debug_mode:
            logger.debug(f"Processing note: {config.notes[0]}")

        result = await process_note(config.notes[0], graphiti, logger, config)

        if debug_mode:
            note_processing_time = time.time() - note_processing_start
            logger.debug(
                f"Note processing completed in {note_processing_time:.2f}s")

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

        # Restore stderr before printing final result
        if not debug_mode:
            sys.stderr.close()
            sys.stderr = original_stderr

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
        # Restore stderr before error exit
        if not debug_mode and sys.stderr != original_stderr:
            try:
                sys.stderr.close()
            except Exception:
                pass
            sys.stderr = original_stderr
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
        # Restore stderr before error handling
        if not debug_mode and sys.stderr != original_stderr:
            try:
                sys.stderr.close()
            except Exception:
                pass
            sys.stderr = original_stderr

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
    @@vessel-protocol:Heimdall governs:validation context:Ollama base URL normalization
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

    Added lightweight runtime diagnostics when debug=True:
    - Logs configured embedding_dim and model
    - Attempts a single sample embedding call (if embedder exposes an async `embed` method)
        to validate returned vector length matches configured embedding_dim. This surface
        mismatches early and produces clearer logs instead of downstream Neo4j dimension errors.
    @@vessel-protocol:Heimdall governs:debug context:Embedder diagnostics for Ollama/embedding-dimension mismatches
    """
    logger = logging.getLogger('graphiti_bridge.sync')

    # Get embedder API key
    embedder_api_key = config.get_effective_embedder_api_key()

    # Create embedder client based on provider
    if config.embedder_provider == "openai":
        # OpenAI Embedder
        embedder_config = OpenAIEmbedderConfig(
            api_key=embedder_api_key,
            model=config.embedding_model
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
        # Voyage AI Embedder
        if not VOYAGE_EMBEDDER_AVAILABLE or VoyageAIEmbedder is None:
            raise NotImplementedError(
                f"Voyage embedder requested but not available. Install with: pip install voyageai")

        # Use VoyageAIEmbedderConfig format (from test file)
        embedder_config = VoyageAIEmbedderConfig(
            api_key=embedder_api_key,
            model=config.embedding_model
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
        # @@vessel-protocol:Heimdall governs:validation context:Ollama embedder provider integration via OpenAI embedder
        # Ollama Embedder (Local) - uses OpenAI embedder with custom base_url per Graphiti docs
        if not OPENAI_EMBEDDER_AVAILABLE or OpenAIEmbedder is None:
            raise NotImplementedError(
                f"Ollama embedder requested but OpenAI embedder not available. Install with: pip install graphiti-core")

        # Use OpenAI embedder with Ollama base URL (official Graphiti pattern)
        ollama_base_url = _get_ollama_base_url(
            getattr(config, 'ollama_base_url', None))
        embedder_config = OpenAIEmbedderConfig(
            api_key="ollama",  # Placeholder API key as per Graphiti docs
            embedding_model=config.embedding_model,  # Corrected parameter name
            embedding_dim=getattr(config, 'ollama_embedding_dim', 768),
            base_url=ollama_base_url
        )
        embedder = OpenAIEmbedder(config=embedder_config)

    else:
        # Unsupported embedder provider
        raise NotImplementedError(
            f"Embedder provider '{config.embedder_provider}' is not supported. Supported: openai, google, voyage, azure, ollama")

    # ---- Diagnostics (debug-only) ----
    if debug:
        try:
            # Log configured embedding dimension if available on config object
            logger.debug(
                f"Embedder: {config.embedder_provider} model={config.embedding_model}")
        except Exception:
            logger.debug(
                "[EMBEDDER-DEBUG] Could not read embedder_config for diagnostic logging")

        # If the embedder exposes an async embed method, attempt a single sample to get returned vector length.
        # Wrap in try/except to avoid breaking initialization if network/permissions fail.
        try:
            # Many Graphiti embedders implement either `embed` or `embed_documents` async methods.
            sample_call = None
            if hasattr(embedder, 'embed') and asyncio.iscoroutinefunction(embedder.embed):
                sample_call = embedder.embed(["diagnostic test"])
            elif hasattr(embedder, 'embed_documents') and asyncio.iscoroutinefunction(embedder.embed_documents):
                sample_call = embedder.embed_documents(["diagnostic test"])
            elif hasattr(embedder, 'embed') and not asyncio.iscoroutinefunction(embedder.embed):
                # sync embed
                vecs = embedder.embed(["diagnostic test"])
                if isinstance(vecs, list) and len(vecs) > 0 and isinstance(vecs[0], (list, tuple)):
                    logger.debug(
                        f"[EMBEDDER-DEBUG] Sample embedding length (sync): {len(vecs[0])}")
            if sample_call is not None:
                # Run the coroutine to completion (safe in initialization context)
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    # We're in an event loop — schedule task and await it
                    # Create task and wait synchronously with asyncio.run_coroutine_threadsafe if running in different thread
                    import concurrent.futures
                    import threading
                    fut = asyncio.run_coroutine_threadsafe(sample_call, loop)
                    vecs = fut.result(timeout=10)
                else:
                    # Safe to run with asyncio.run
                    vecs = asyncio.run(sample_call)
                if isinstance(vecs, list) and len(vecs) > 0 and isinstance(vecs[0], (list, tuple)):
                    logger.debug(
                        f"[EMBEDDER-DEBUG] Sample embedding length (async): {len(vecs[0])}")
                else:
                    logger.debug(
                        f"[EMBEDDER-DEBUG] Sample embedding returned type: {type(vecs)}")
        except Exception as e:
            logger.debug(
                f"[EMBEDDER-DEBUG] Sample embedding diagnostic failed: {e}")
    # ---- End diagnostics ----

    return embedder


def create_disabled_cross_encoder():
    """
    Create a privacy-preserving disabled cross-encoder using OpenAI client with fake config.
    This prevents unauthorized external API calls while satisfying Graphiti's type requirements.
    """
    from graphiti_core.llm_client.config import LLMConfig

    # Create OpenAI reranker with a fake config that won't make real API calls
    fake_config = LLMConfig(
        api_key="disabled-for-privacy",
        model="disabled-model"
    )

    # Create the client but override the rank method (not rerank!)
    disabled_client = OpenAIRerankerClient(config=fake_config)

    # Override the rank method to prevent API calls
    from typing import Optional

    async def disabled_rank(query: str, passages: list, top_k: Optional[int] = None):
        """Return passages in original order without ranking - NO API CALLS"""
        if top_k is not None and top_k < len(passages):
            return passages[:top_k]
        return passages

    disabled_client.rank = disabled_rank
    return disabled_client


def create_cross_encoder(config: BridgeConfig, debug: bool = False):
    """
    Create cross-encoder client based on config.cross_encoder_client.
    This allows independent selection of cross-encoder providers from LLM providers.

    PRIVACY FIX: Returns DisabledCrossEncoder instead of None to prevent unauthorized OpenAI fallback.

    @@vessel-protocol:Mimir governs:integration context:Cross-encoder provider abstraction with API key management
    """
    logger = logging.getLogger('graphiti_bridge.sync')

    if debug:
        logger.debug("[CROSS-ENCODER-DEBUG] create_cross_encoder() called")

    cross_encoder_provider = 'none'  # Default value to prevent unbound variable
    try:
        cross_encoder_provider = getattr(
            config, 'cross_encoder_client', 'none')
        # Do NOT invent provider-specific default model names here.
        # Respect explicit config.cross_encoder_model if provided; otherwise leave unset.
        cross_encoder_model = getattr(config, 'cross_encoder_model', None)

        if debug:
            model_text = f" model={cross_encoder_model}" if cross_encoder_model else " (no model)"
            logger.debug(
                f"Cross-encoder: {cross_encoder_provider}{model_text}")

        # Handle 'none' option to disable cross-encoder entirely (PRIVACY FIX: return disabled object instead of None)
        if cross_encoder_provider == 'none' or cross_encoder_provider is None:
            if debug:
                logger.debug(
                    "[CROSS-ENCODER-DEBUG] Cross-encoder disabled (provider set to 'none' or not configured) - using disabled cross-encoder for privacy")
            return create_disabled_cross_encoder()

        # Get API key for cross-encoder provider
        cross_encoder_api_key = None
        if hasattr(config, 'api_keys') and config.api_keys:
            cross_encoder_api_key = config.api_keys.get(cross_encoder_provider)

        # Fallback to general LLM API key if no specific cross-encoder key
        if not cross_encoder_api_key and hasattr(config, 'llm_api_key') and config.llm_api_key:
            cross_encoder_api_key = config.llm_api_key

        # Keep behavior minimal: do not invent alternative provider aliases or cascade lookups.
        # Providers that require no API key should be configured as such (e.g., 'bge' -> None).

        # Create cross-encoder client based on provider
        if cross_encoder_provider == 'openai':
            if debug:
                logger.debug(
                    "[CROSS-ENCODER-DEBUG] Creating OpenAI cross-encoder")
            # OpenAI Cross-Encoder/Reranker
            if not OPENAI_CROSS_ENCODER_AVAILABLE:
                if debug:
                    logger.warning(
                        "[CROSS-ENCODER-DEBUG] OpenAI cross-encoder requested but not available, disabling cross-encoder")
                return None

            # Use cross_encoder_model as primary model
            primary_model = cross_encoder_model or 'gpt-5-nano'

            # Create OpenAI reranker with only the primary model (no small_model usage)
            cross_encoder = OpenAIRerankerClient(
                config=LLMConfig(
                    api_key=cross_encoder_api_key or 'dummy-key',
                    model=primary_model
                )
            )
            if debug:
                logger.debug(
                    f"OpenAI cross-encoder created with model: {primary_model}")

        elif cross_encoder_provider == 'bge':
            # LAZY IMPORT: Check and import BGE only when actually needed
            global BGE_CROSS_ENCODER_AVAILABLE, BGERerankerClient

            if BGE_CROSS_ENCODER_AVAILABLE is None:  # First time check
                if not SKIP_BGE_IMPORT:
                    try:
                        if debug:
                            logger.debug(
                                "[CROSS-ENCODER-DEBUG] Lazy-loading BGE cross-encoder (first use)...")
                        _t = time.time()
                        from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient as BGEClient
                        BGERerankerClient = BGEClient
                        BGE_CROSS_ENCODER_AVAILABLE = True
                        if debug:
                            logger.debug(
                                f"[CROSS-ENCODER-DEBUG] BGE loaded in {time.time() - _t:.2f}s")
                    except ImportError:
                        BGE_CROSS_ENCODER_AVAILABLE = False
                        if debug:
                            logger.warning(
                                "[CROSS-ENCODER-DEBUG] BGE import failed (sentence-transformers not installed)")
                else:
                    BGE_CROSS_ENCODER_AVAILABLE = False
                    if debug:
                        logger.debug(
                            "[CROSS-ENCODER-DEBUG] BGE import skipped due to SKIP_BGE_IMPORT=true")

            if debug:
                logger.debug(
                    f"[CROSS-ENCODER-DEBUG] BGE cross-encoder requested. Available: {BGE_CROSS_ENCODER_AVAILABLE}, Client: {BGERerankerClient is not None}")

            # BGE Cross-Encoder (Local via sentence-transformers)
            if not BGE_CROSS_ENCODER_AVAILABLE or BGERerankerClient is None:
                if debug:
                    logger.warning(
                        "[CROSS-ENCODER-DEBUG] BGE cross-encoder not available, using disabled cross-encoder for privacy")
                return create_disabled_cross_encoder()

            # Use cached instance to prevent repeated HuggingFace model downloads
            global _BGE_CROSS_ENCODER_INSTANCE
            if _BGE_CROSS_ENCODER_INSTANCE is None:
                try:
                    # Set cache directory explicitly to ensure model is loaded from local cache
                    import os
                    os.environ['TRANSFORMERS_CACHE'] = os.path.expanduser(
                        '~/.cache/huggingface/hub')
                    os.environ['HF_HOME'] = os.path.expanduser(
                        '~/.cache/huggingface')
                    os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.path.expanduser(
                        '~/.cache/sentence_transformers')
                    # Force offline mode - don't check for updates
                    os.environ['HF_HUB_OFFLINE'] = '1'

                    init_start = time.time()
                    if debug:
                        logger.debug(
                            "[BGE-TIMING] Starting BGE initialization...")

                    _BGE_CROSS_ENCODER_INSTANCE = BGERerankerClient()

                except Exception as bge_error:
                    if debug:
                        logger.error(
                            f"BGE cross-encoder instantiation failed: {bge_error}")
                    # Return disabled cross-encoder to prevent unauthorized OpenAI fallback
                    return create_disabled_cross_encoder()

            cross_encoder = _BGE_CROSS_ENCODER_INSTANCE

        elif cross_encoder_provider == 'gemini' or cross_encoder_provider == 'google' or cross_encoder_provider == 'google-ai':
            if debug:
                logger.debug(
                    "[CROSS-ENCODER-DEBUG] Creating Gemini cross-encoder")
            # Gemini Cross-Encoder/Reranker
            if not GEMINI_CROSS_ENCODER_AVAILABLE or GeminiRerankerClient is None:
                if debug:
                    logger.warning(
                        "[CROSS-ENCODER-DEBUG] Gemini cross-encoder requested but not available (requires google-genai), using disabled cross-encoder for privacy")
                return create_disabled_cross_encoder()

            model_name = cross_encoder_model or 'gemini-2.5-flash-lite-preview-06-17'

            cross_encoder = GeminiRerankerClient(
                config=LLMConfig(
                    api_key=cross_encoder_api_key or 'dummy-key',
                    model=model_name
                )
            )
            if debug:
                logger.debug(
                    f"Gemini cross-encoder created with model: {model_name}")

        else:
            # Unsupported cross-encoder provider
            if debug:
                logger.warning(
                    f"[CROSS-ENCODER-DEBUG] Unsupported cross-encoder provider '{cross_encoder_provider}', using disabled cross-encoder for privacy")
            return create_disabled_cross_encoder()

        if debug:
            logger.debug(
                f"[CROSS-ENCODER-DEBUG] Successfully created cross-encoder: {type(cross_encoder).__name__}")
        return cross_encoder

    except Exception as e:
        if debug:
            logger.warning(
                f"[CROSS-ENCODER-DEBUG] Failed to create cross-encoder ({cross_encoder_provider}): {e}")
            logger.debug(
                "[CROSS-ENCODER-DEBUG] Cross-encoder creation failed, using disabled cross-encoder to prevent unauthorized fallbacks")
        return create_disabled_cross_encoder()


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

            # @@vessel-protocol:Heimdall governs:validation context:OpenAI model compatibility for reasoning parameters (Graphiti 0.19.0+ fix)
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

            llm_client = OpenAIClient(**client_params)

            # Create cross-encoder using unified helper function
            cross_encoder = create_cross_encoder(config, debug)

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
            llm_client = GeminiClient(config=llm_config)
            if debug:
                logger.info(
                    f"Google AI LLM client instantiated with model: {config.llm_model}")

            # Create cross-encoder using unified helper function
            if debug:
                logger.debug(
                    "[INIT-DEBUG] About to call create_cross_encoder() for Google AI provider")
            cross_encoder = create_cross_encoder(config, debug)
            if debug and cross_encoder:
                logger.debug(
                    "[INIT-DEBUG] Google AI cross-encoder successfully created")
            elif debug and cross_encoder is None:
                logger.debug(
                    "[INIT-DEBUG] Google AI cross-encoder disabled or unavailable")

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
            llm_client = AnthropicClient(config=llm_config)
            if debug:
                logger.info(
                    f"Anthropic LLM client instantiated with model: {config.llm_model}")

            # Create cross-encoder using unified helper function
            if debug:
                logger.debug(
                    "[INIT-DEBUG] About to call create_cross_encoder() for Anthropic provider")
            cross_encoder = create_cross_encoder(config, debug)
            if debug and cross_encoder:
                logger.debug(
                    "[INIT-DEBUG] Anthropic cross-encoder successfully created")
            elif debug and cross_encoder is None:
                logger.debug(
                    "[INIT-DEBUG] Anthropic cross-encoder disabled or unavailable")

        elif config.llm_provider == "ollama":
            # ===== OLLAMA PROVIDER =====
            # @@vessel-protocol:Bifrost governs:integration context:Ollama LLM client configuration using OpenAI-compatible endpoint
            if debug:
                logger.info(
                    f"Initializing Ollama provider - LLM: {config.llm_model}, Embedder: {config.embedder_provider} {config.embedding_model}")

            # Create Ollama LLM client using OpenAIGenericClient per Graphiti docs
            ollama_base_url = _get_ollama_base_url(
                getattr(config, 'ollama_base_url', None))
            # For Ollama, ignore llm_small_model to improve structured JSON reliability
            ollama_small = None
            if debug and getattr(config, 'llm_small_model', None):
                logger.debug(
                    "Ollama provider: ignoring llm_small_model for structured JSON reliability")
            llm_config = LLMConfig(
                api_key="ollama",
                model=config.llm_model,
                small_model=ollama_small,
                base_url=ollama_base_url
            )
            llm_client = OpenAIGenericClient(config=llm_config)
            if debug:
                logger.info(
                    f"Ollama LLM client instantiated with model: {config.llm_model}")

            # Create cross-encoder using unified helper function
            if debug:
                logger.debug(
                    "[INIT-DEBUG] About to call create_cross_encoder() for Ollama provider")
            cross_encoder = create_cross_encoder(config, debug)
            if debug and cross_encoder:
                logger.debug(
                    "[INIT-DEBUG] Ollama cross-encoder successfully created")
            elif debug and cross_encoder is None:
                logger.debug(
                    "[INIT-DEBUG] Ollama cross-encoder disabled or unavailable")

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
            llm_client = OpenAIGenericClient(config=llm_config)
            if debug:
                logger.info(
                    f"Venice.ai LLM client instantiated with model: {config.llm_model} (base_url={venice_base})")

            # Create cross-encoder using unified helper function
            if debug:
                logger.debug(
                    "[INIT-DEBUG] About to call create_cross_encoder() for Venice provider")
            cross_encoder = create_cross_encoder(config, debug)
            if debug and cross_encoder:
                logger.debug(
                    "[INIT-DEBUG] Venice cross-encoder successfully created")
            elif debug and cross_encoder is None:
                logger.debug(
                    "[INIT-DEBUG] Venice cross-encoder disabled or unavailable")

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
            llm_client = OpenRouterClient(config=llm_config)
            if debug:
                logger.info("Using custom OpenRouter client for proper structured output support")
            if debug:
                logger.info(
                    f"OpenRouter LLM client instantiated with model: {processed_model} (base_url={openrouter_base})")

            # Create cross-encoder using unified helper function
            if debug:
                logger.debug(
                    "[INIT-DEBUG] About to call create_cross_encoder() for OpenRouter provider")
            cross_encoder = create_cross_encoder(config, debug)
            if debug and cross_encoder:
                logger.debug(
                    "[INIT-DEBUG] OpenRouter cross-encoder successfully created")
            elif debug and cross_encoder is None:
                logger.debug(
                    "[INIT-DEBUG] OpenRouter cross-encoder disabled or unavailable")

        else:
            # ===== UNSUPPORTED PROVIDER =====
            raise NotImplementedError(
                f"LLM provider '{config.llm_provider}' is not yet supported. Supported providers: openai, google, anthropic, ollama, venice, openrouter")

        # Create database driver (v0.17.0+ pattern) - supports both Neo4j and FalkorDB

        db_type = getattr(config, 'database_type', 'neo4j').lower()

        if db_type == 'falkordb':
            # ===== FALKORDB DRIVER =====
            if not FALKORDB_AVAILABLE or FalkorDriver is None:
                raise NotImplementedError(
                    f"FalkorDB driver requested but not available. Install with: pip install graphiti-core[falkordb]")

            # Parse redis URL format (redis://host:port)
            import re
            match = re.match(r'redis://([^:]+):(\d+)', config.database_url)
            if match:
                host, port = match.groups()
            else:
                # Default fallback
                host, port = 'localhost', '6379'

            if debug:
                logger.info(
                    f"Creating FalkorDB driver: {host}:{port} database={getattr(config, 'database_name', 'graphiti')}")

            driver = FalkorDriver(
                host=host,
                port=int(port),
                username=config.database_username or None,
                password=config.database_password or None,
                database=getattr(config, 'database_name',
                                 'default_db') or 'default_db'
            )
        else:
            # ===== NEO4J DRIVER (DEFAULT) =====

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
    Extract episode UUID from Graphiti result
    """
    if not graphiti_result:
        return None

    episode_uuid = None

    # Try to extract episode UUID from various possible locations
    if hasattr(graphiti_result, 'episode') and graphiti_result.episode:
        episode_obj = graphiti_result.episode
        if hasattr(episode_obj, 'uuid'):
            episode_uuid = str(episode_obj.uuid)
        elif hasattr(episode_obj, 'id'):
            episode_uuid = str(episode_obj.id)
        elif hasattr(episode_obj, '__dict__'):
            # Look for UUID fields in episode object
            for key, value in episode_obj.__dict__.items():
                if 'uuid' in key.lower() or 'id' in key.lower():
                    if value:
                        episode_uuid = str(value)
                        if debug_mode:
                            logger.debug(
                                f"Found episode UUID in episode.{key}: {episode_uuid}")
                        break
    elif hasattr(graphiti_result, 'episode_uuid'):
        episode_uuid = str(graphiti_result.episode_uuid)
    elif hasattr(graphiti_result, 'uuid'):
        episode_uuid = str(graphiti_result.uuid)
    elif hasattr(graphiti_result, 'id'):
        episode_uuid = str(graphiti_result.id)

    if not episode_uuid:
        # Debug: log available attributes to help find UUID
        if debug_mode:
            available_attrs = [attr for attr in dir(
                graphiti_result) if not attr.startswith('_')]
            logger.debug(
                f"No UUID found in result. Available attributes: {available_attrs}")

        # Look for UUID in nested objects
        if hasattr(graphiti_result, '__dict__'):
            for key, value in graphiti_result.__dict__.items():
                if 'uuid' in key.lower() or 'id' in key.lower():
                    if debug_mode:
                        logger.debug(
                            f"Found potential UUID field: {key} = {value}")
                    if not episode_uuid and value:
                        episode_uuid = str(value)

    return episode_uuid


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
            sync_records = _load_sync_records(getattr(config, 'vault_path', None), debug_mode, logger)
            saga_previous_uuid = lookup_saga_previous_uuid(saga_name, sync_records)
            if debug_mode:
                logger.debug(f"Saga: name='{saga_name}', previous_uuid='{saga_previous_uuid}'")

        # Choose episode creation strategy based on ontology setting
        if config.use_custom_ontology:
            # Use custom entity episodes with Pydantic models
            graphiti_result = await create_custom_entity_episode(
                graphiti, note_name, clean_text, reference_time, group_id, metadata, logger, database_type, config, debug_mode, custom_extraction_instructions,
                saga_name=saga_name, saga_previous_uuid=saga_previous_uuid
            )
        else:
            # Use generic text episodes
            graphiti_result = await create_generic_text_episode(
                graphiti, note_name, clean_text, reference_time, group_id, logger, database_type, config, debug_mode, metadata, custom_extraction_instructions,
                saga_name=saga_name, saga_previous_uuid=saga_previous_uuid
            )

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

            # Use the dedicated helper to extract the episode UUID
            episode_uuid = extract_episode_uuid_from_result(
                graphiti_result, debug_mode, logger)

            # DON'T include the full graphiti result - it's MASSIVE and breaks the pipe
            # Just include essential info
            clean_graphiti_data = {
                'episode_uuid': episode_uuid,
                'entities_count': entities_count,
                'relationships_count': relationships_count
            }

            # Graphiti result structure logging removed (not useful in production)

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

        # Enhanced rate limiting detection with reset time parsing
        error_message = str(e).lower()
        original_error = str(e)  # Keep original case for parsing
        if 'http/1.1 400 bad request' in error_message or 'rate limit' in error_message or 'too many requests' in error_message or 'usage limits' in error_message:
            if debug_mode:
                logger.error(
                    f"API rate limit detected for note {note_path}: {e}")

            # Parse Anthropic-specific reset time: "You will regain access on 2025-10-01 at 00:00 UTC"
            import re

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
            logger.error(f"Failed to process note {note_path}: {e}")
        # Re-raise to be caught by the calling main function
        raise


def serialize_graphiti_result(result) -> Dict[str, Any]:
    """
    Convert Graphiti result to JSON-serializable format, removing embeddings
    """
    if not result:
        return {}

    serialized = {}

    # Handle different result types
    if hasattr(result, '__dict__'):
        for key, value in result.__dict__.items():
            serialized[key] = serialize_value(value)

    return serialized


# REDUCED to prevent massive output
def serialize_value(value, seen=None, depth=0, max_depth=3):
    """
    Recursively serialize a value to JSON-serializable format with circular reference protection.
    """
    from datetime import datetime, date

    if seen is None:
        seen = set()

    # Prevent infinite recursion while ensuring sufficient depth for expected output
    if depth > max_depth:
        return f"[max_depth_exceeded_{type(value).__name__}]"

    # Handle circular references
    if hasattr(value, '__dict__') and id(value) in seen:
        return f"[circular_reference_{type(value).__name__}]"

    if value is None:
        return None
    elif isinstance(value, (datetime, date)):
        return value.isoformat()
    elif isinstance(value, str):
        return value
    elif isinstance(value, (int, float, bool)):
        return value
    elif isinstance(value, list):
        return [serialize_value(item, seen, depth + 1, max_depth) for item in value]
    elif isinstance(value, dict):
        return {k: serialize_value(v, seen, depth + 1, max_depth) for k, v in value.items()}
    elif hasattr(value, '__dict__'):
        # Add to seen set to detect circular references
        seen.add(id(value))

        # Handle object with attributes
        result = {}
        obj_dict = value.__dict__

        for key, val in obj_dict.items():
            if key.endswith('_embedding'):
                # Replace embeddings with placeholder
                result[key] = f"[embedding_vector_length_{len(val) if isinstance(val, list) else 'unknown'}]"
            elif key.startswith('_'):
                # Skip truly private/internal attributes to reduce noise
                if key not in ['_driver', '_session', '_llm_client', '_embedder', '_cross_encoder', '_graph_driver']:
                    result[key] = serialize_value(
                        val, seen.copy(), depth + 1, max_depth)
            else:
                result[key] = serialize_value(
                    val, seen.copy(), depth + 1, max_depth)

        return result
    else:
        # For any other type, convert to string (limit string length if it can be huge)
        string_representation = str(value)
        return string_representation[:2000] if len(string_representation) > 2000 else string_representation


async def create_generic_text_episode(graphiti, note_name: str, clean_text: str,
                                      reference_time: datetime, group_id: str, logger, database_type: str = 'neo4j', config=None, debug_mode: bool = False, metadata: Optional[Dict[str, Any]] = None, custom_extraction_instructions: Optional[str] = None,
                                      saga_name: Optional[str] = None, saga_previous_uuid: Optional[str] = None):
    """Create a generic text episode using EpisodeType.text"""

    try:
        # FALKORDB FIX: Use timezone-aware datetime and handle group_id compatibility
        if isinstance(reference_time, datetime):
            # Convert to timezone-aware datetime for FalkorDB compatibility
            if reference_time.tzinfo is None:
                formatted_reference_time = reference_time.replace(
                    tzinfo=timezone.utc)
            else:
                formatted_reference_time = reference_time
        else:
            formatted_reference_time = reference_time

        # Use source description from frontmatter.type if present, else fallback to config/default
        frontmatter_type = None
        if metadata and isinstance(metadata, dict):
            frontmatter_type = metadata.get('type')
        if frontmatter_type:
            source_description = str(frontmatter_type)
        else:
            source_description = getattr(
                config, 'source_description', 'obsidian_mm_default') if config else 'obsidian_mm_fallback'

        # Merge frontmatter into the body if metadata is provided; otherwise use body as-is
        merged_body = clean_text
        if isinstance(metadata, dict) and metadata:
            frontmatter_lines = ["---"]
            for k, v in metadata.items():
                if isinstance(v, (dict, list)):
                    val = json.dumps(v)
                else:
                    val = str(v)
                frontmatter_lines.append(f"{k}: {val}")
            frontmatter_lines.append("---")
            frontmatter_block = "\n".join(frontmatter_lines)
            merged_body = f"{frontmatter_block}\n{clean_text}"
            if debug_mode:
                logger.debug(
                    f"Frontmatter: {len(metadata)} fields attached to body")
        episode_kwargs = {
            'name': note_name,
            'episode_body': merged_body,
            'source': EpisodeType.text,
            'source_description': source_description,
            'reference_time': formatted_reference_time
        }
        # Do not attach separate frontmatter field anymore; frontmatter is merged into body
        if database_type.lower() == 'neo4j':
            episode_kwargs['group_id'] = group_id

        # Forward previous_episode_uuids from config when present (non-empty)
        prev_uuids = getattr(config, 'previous_episode_uuids', None)
        if prev_uuids:
            episode_kwargs['previous_episode_uuids'] = prev_uuids
            if debug_mode:
                logger.debug(
                    f"Received previous_episode_uuids from config: {prev_uuids}")

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

        # Force transaction commit if available
        if hasattr(graphiti, '_driver') and graphiti._driver:
            # Graphiti should handle commits internally, but let's verify
            try:
                # Check if there's a session or transaction we can explicitly commit
                if hasattr(graphiti, '_session') and graphiti._session:
                    await graphiti._session.commit()
            except Exception:
                pass  # Silent - no explicit commit needed or available

        return result

    except Exception as e:
        # Only log if in a debug context - for now, just re-raise
        raise


async def create_custom_entity_episode(graphiti, note_name: str, clean_text: str,
                                       reference_time: datetime, group_id: str,
                                       metadata: Dict[str, Any], logger, database_type: str = 'neo4j', config=None, debug_mode: bool = False, custom_extraction_instructions: Optional[str] = None,
                                       saga_name: Optional[str] = None, saga_previous_uuid: Optional[str] = None):
    """Create a custom entity episode using Graphiti Custom Entities API"""

    try:
        # FALKORDB FIX: Use timezone-aware datetime and handle group_id compatibility
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

        # No custom entity types available, fall back to generic episode
        if not entity_types:
            return await create_generic_text_episode(graphiti, note_name, clean_text, reference_time, group_id, logger, database_type, config, custom_extraction_instructions=custom_extraction_instructions, saga_name=saga_name, saga_previous_uuid=saga_previous_uuid)

        # Use source description from frontmatter type if available, else fallback to config/default
        frontmatter_type = None
        if metadata and isinstance(metadata, dict):
            frontmatter_type = metadata.get('type')
        if frontmatter_type:
            source_description = str(frontmatter_type)
        else:
            source_description = getattr(
                config, 'source_description', 'obsidian_mm_default') if config else 'obsidian_mm_fallback'

        # Merge frontmatter into the body
        merged_body = clean_text
        if isinstance(metadata, dict) and metadata:
            frontmatter_lines = ["---"]
            for k, v in metadata.items():
                if isinstance(v, (dict, list)):
                    val = json.dumps(v)
                else:
                    val = str(v)
                frontmatter_lines.append(f"{k}: {val}")
            frontmatter_lines.append("---")
            frontmatter_block = "\n".join(frontmatter_lines)
            merged_body = f"{frontmatter_block}\n{clean_text}"
            if debug_mode:
                logger.debug(
                    f"Frontmatter: {len(metadata)} fields attached to body")
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

        # Add group_id only for Neo4j (FalkorDB doesn't support it)
        if database_type.lower() == 'neo4j':
            episode_kwargs['group_id'] = group_id

        # Forward previous_episode_uuids from config when present (non-empty)
        prev_uuids = getattr(config, 'previous_episode_uuids', None)
        if prev_uuids:
            episode_kwargs['previous_episode_uuids'] = prev_uuids
            if debug_mode:
                logger.debug(
                    f"Received previous_episode_uuids from config: {prev_uuids}")

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

    except Exception as e:
        import traceback

        if hasattr(logger, 'warning'):
            logger.warning(
                f"Custom entity episode creation failed: {e}, falling back to generic episode")

        return await create_generic_text_episode(graphiti, note_name, clean_text, reference_time, group_id, logger, database_type, config, custom_extraction_instructions=custom_extraction_instructions, saga_name=saga_name, saga_previous_uuid=saga_previous_uuid)


def resolve_namespace(note_path: str, metadata: Dict[str, Any], config: BridgeConfig, logger) -> str:
    """
    Resolve the namespace (group_id) for an episode based on priority order:
    1. Property namespacing (highest priority): g_group_id in frontmatter
    2. Folder namespacing: Custom folder mappings from folderNamespaceMappings
    3. Namespace strategy: vault name or defaultNamespace
    """
    debug_mode = getattr(config, 'debug', False)

    try:
        # 1. Property namespacing (highest priority)
        if config.enable_property_namespacing and metadata and 'g_group_id' in metadata:
            namespace = str(metadata['g_group_id']).strip()
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
            # Extract vault name from note path or use default
            vault_name = _extract_vault_name_from_path(
                note_path, config.default_namespace, debug_mode, logger)
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

    except Exception as e:
        if debug_mode:
            logger.warning(f"Error resolving namespace for {note_path}: {e}")
            logger.debug(
                f"Falling back to default namespace: {config.default_namespace}")
        return config.default_namespace


def _extract_vault_name_from_path(note_path: str, default_namespace: str, debug_mode: bool, logger) -> str:
    """
    Extract vault name from note path or return default namespace.
    For vault strategy, we want just the vault name, not the full path.
    """
    try:
        # For vault strategy, use the provided default_namespace directly
        # This should be the vault name from settings
        return default_namespace
    except Exception as e:
        if debug_mode:
            logger.warning(f"Error extracting vault name: {e}")
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
    """Find the most recent episode UUID in a saga from existing sync records."""
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


def _load_sync_records(vault_path: Optional[str], debug_mode: bool, logger) -> list:
    """Load sync records from sync.json for saga chain lookups."""
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
            # FALKORDB FIX: Always use timezone-aware datetime for FalkorDB
            reference_time = datetime.now(timezone.utc)
        else:
            reference_time = datetime.now()
    else:
        # FALKORDB FIX: Ensure timezone-aware datetime for FalkorDB compatibility
        if database_type == 'falkordb' and hasattr(reference_time, 'tzinfo') and reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

    return reference_time


if __name__ == "__main__":
    asyncio.run(main())
