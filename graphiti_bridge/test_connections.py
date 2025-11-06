#!/usr/bin/env python3
"""
Connection testing utilities for Graphiti Bridge

Tests database and provider connections with graceful import handling.
Validates that provider clients can be instantiated successfully.
"""

import sys
import json
import argparse
import time
import asyncio
import logging
import os
from typing import Dict, Any, Tuple

# Import local modules with fallback for direct execution (exact pattern from sync.py)
try:
    # Try relative imports first (when run as part of package)
    from .config import BridgeConfig, setup_environment_variables
    from .utils import (
        setup_logging,
        print_json_response
    )
    from .sync import create_embedder_client as sync_create_embedder_client, _get_ollama_base_url
except ImportError:
    # Fall back to absolute imports (when run directly)
    # Add parent directory to sys.path for module resolution when running from plugin directory
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    from graphiti_bridge.config import BridgeConfig, setup_environment_variables
    from graphiti_bridge.utils import (
        setup_logging,
        print_json_response
    )
    from graphiti_bridge.sync import create_embedder_client as sync_create_embedder_client, _get_ollama_base_url

# Core Graphiti imports
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

# Provider availability flags and graceful imports
# Import LLM client creation function from graphiti_core
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.gemini_client import GeminiClient

GEMINI_EMBEDDER_AVAILABLE = False
GeminiEmbedder = None
GeminiEmbedderConfig = None
try:
    from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
    GEMINI_EMBEDDER_AVAILABLE = True
except ImportError:
    pass

VOYAGE_EMBEDDER_AVAILABLE = False
VoyageAIEmbedder = None
VoyageAIEmbedderConfig = None
try:
    from graphiti_core.embedder.voyage import VoyageAIEmbedder, VoyageAIEmbedderConfig
    VOYAGE_EMBEDDER_AVAILABLE = True
except ImportError:
    pass

AZURE_EMBEDDER_AVAILABLE = False
AzureOpenAIEmbedderClient = None
try:
    from graphiti_core.embedder.azure_openai import AzureOpenAIEmbedderClient
    AZURE_EMBEDDER_AVAILABLE = True
except ImportError:
    pass


def get_latency_ms(start_time: float) -> int:
    """Calculate latency in milliseconds from start time"""
    return int((time.time() - start_time) * 1000)


def validate_config(config: BridgeConfig, test_type: str) -> list:
    """Validate configuration based on test type"""
    errors = []

    if test_type in ['database', 'schema-init']:
        if not config.database_type:
            errors.append("Database type is required")
        if not config.database_url:
            errors.append("Database URL is required")
        if config.database_type == 'neo4j':
            if not config.database_username:
                errors.append("Database username required for Neo4j")
            if not config.database_password:
                errors.append("Database password required for Neo4j")
        if not config.database_name:
            errors.append("Database name is required")

    if test_type in ['llm', 'combination', 'combination-test', 'combination-pipeline', 'schema-init']:
        if not config.llm_provider:
            errors.append("LLM provider is required")
        if not config.llm_model:
            errors.append("LLM model is required")
        if config.llm_provider != 'ollama':
            if not hasattr(config, 'api_keys') or not config.api_keys:
                errors.append("API keys configuration is missing")
            elif not config.api_keys.get(config.llm_provider):
                errors.append(
                    f"API key for {config.llm_provider} provider is required")

    if test_type in ['embedding', 'embedding-test', 'combination', 'combination-test', 'combination-pipeline']:
        if not config.embedder_provider:
            errors.append("Embedder provider is required")
        if not config.embedding_model:
            errors.append("Embedding model is required")
        if config.embedder_provider != 'ollama':
            if not hasattr(config, 'api_keys') or not config.api_keys:
                errors.append("API keys configuration is missing")
            elif not config.api_keys.get(config.embedder_provider):
                errors.append(
                    f"API key for {config.embedder_provider} provider is required")

    # Cross-encoder validation for combined/pipeline operations
    if test_type in ['combination', 'combination-test', 'combination-pipeline', 'schema-init']:
        ce_provider = getattr(config, 'cross_encoder_client', 'none')
        if ce_provider and ce_provider != 'none':
            # Normalize Google/Gemini aliases for API key lookup
            key_provider = 'google' if ce_provider in (
                'gemini', 'google', 'google-ai') else ce_provider
            if key_provider in ('openai', 'google'):
                if not hasattr(config, 'api_keys') or not config.api_keys:
                    errors.append(
                        "API keys configuration is missing for cross-encoder")
                elif not config.api_keys.get(key_provider):
                    errors.append(
                        f"API key for cross-encoder provider '{ce_provider}' is required")
            elif ce_provider == 'bge':
                # Local reranker; no API key required
                pass
            else:
                errors.append(
                    f"Unsupported cross-encoder provider: {ce_provider}")

    return errors


def create_embedder_client(config: BridgeConfig, start_time: float):
    """Delegate to sync.create_embedder_client to ensure parity with sync.py"""
    return sync_create_embedder_client(config, debug=False)


def test_database_connection(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test database connection"""
    start_time = time.time()

    try:
        if config.database_type == 'neo4j':
            return test_neo4j_connection(config, start_time)
        elif config.database_type == 'falkordb':
            return test_falkordb_connection(config, start_time)
        else:
            return False, f"Unsupported database type: {config.database_type}", 0
    except Exception as e:
        return False, f"Database connection failed: {str(e)}", get_latency_ms(start_time)


def test_neo4j_connection(config: BridgeConfig, start_time: float) -> Tuple[bool, str, int]:
    """Test Neo4j database connection"""
    try:
        from neo4j import GraphDatabase

        # Handle optional credentials for Neo4j auth
        auth_tuple = None
        if config.database_username and config.database_password:
            auth_tuple = (config.database_username, config.database_password)
        
        driver = GraphDatabase.driver(
            config.database_url,
            auth=auth_tuple
        )

        with driver.session(database=config.database_name) as session:
            result = session.run("RETURN 1 as test")
            single_result = result.single()
            test_value = single_result["test"] if single_result else None

        driver.close()
        latency = get_latency_ms(start_time)

        if test_value == 1:
            return True, f"Neo4j connection successful to database '{config.database_name}'", latency
        else:
            return False, "Neo4j test query returned unexpected result", latency

    except ImportError:
        return False, "Neo4j driver not installed. Run: pip install neo4j", get_latency_ms(start_time)
    except Exception as e:
        latency = get_latency_ms(start_time)
        error_msg = str(e).lower()

        if "authentication" in error_msg or "unauthorized" in error_msg:
            return False, "Authentication failed. Check username and password.", latency
        elif "connection refused" in error_msg:
            return False, "Connection refused. Check if Neo4j is running and URL is correct.", latency
        elif "database does not exist" in error_msg:
            return False, f"Database '{config.database_name}' does not exist.", latency
        else:
            return False, f"Neo4j connection error: {str(e)}", latency


def test_falkordb_connection(config: BridgeConfig, start_time: float) -> Tuple[bool, str, int]:
    """Test FalkorDB database connection"""
    try:
        import redis  # type: ignore[import-not-found]
        from urllib.parse import urlparse

        parsed = urlparse(config.database_url)
        client = redis.Redis(
            host=parsed.hostname or 'localhost',
            port=parsed.port or 6379,
            username=config.database_username or None,
            password=config.database_password or None,
            decode_responses=True
        )

        client.ping()

        # Test graph query (optional, graph might not exist yet)
        try:
            client.execute_command(
                "GRAPH.QUERY", config.database_name, "RETURN 1 as test")
        except Exception:
            pass  # Graph creation not required for connection test

        latency = get_latency_ms(start_time)
        return True, f"FalkorDB connection successful to database '{config.database_name}'", latency

    except ImportError:
        return False, "Redis driver not installed. Run: pip install redis", get_latency_ms(start_time)
    except Exception as e:
        latency = get_latency_ms(start_time)
        error_msg = str(e).lower()

        if "connection refused" in error_msg:
            return False, "Connection refused. Check if FalkorDB/Redis is running and URL is correct.", latency
        elif "authentication" in error_msg:
            return False, "Authentication failed. Check username and password.", latency
        else:
            return False, f"FalkorDB connection error: {str(e)}", latency


async def test_llm_connection(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test LLM provider connection by validating client instantiation (parity with sync.py)"""
    start_time = time.time()

    try:
        setup_environment_variables(config)
        llm_api_key = config.get_effective_llm_api_key()

        if config.llm_provider == "openai":
            is_reasoning_model = any(config.llm_model.startswith(
                p) for p in ('o1-', 'o1_', 'o3-', 'o3_'))
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            client_params = {
                'config': llm_config,
                'cache': False
            }
            if is_reasoning_model:
                client_params['reasoning'] = getattr(
                    config, 'reasoning_effort', 'medium')
                client_params['verbosity'] = getattr(
                    config, 'verbosity_level', 'low')
            else:
                client_params['reasoning'] = None
                client_params['verbosity'] = None
            llm_client = OpenAIClient(**client_params)

        elif config.llm_provider == "google" or config.llm_provider == "google-ai":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            llm_client = GeminiClient(config=llm_config)

        elif config.llm_provider == "anthropic" or config.llm_provider == "claude":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            llm_client = AnthropicClient(config=llm_config)

        elif config.llm_provider == "ollama":
            ollama_base_url = _get_ollama_base_url(
                getattr(config, 'ollama_base_url', None))
            llm_config = LLMConfig(
                api_key="ollama",
                model=config.llm_model,
                small_model=None,
                base_url=ollama_base_url
            )
            llm_client = OpenAIGenericClient(config=llm_config)

        elif config.llm_provider == "venice":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url="https://api.venice.ai/api/v1"
            )
            llm_client = OpenAIGenericClient(config=llm_config)
        elif config.llm_provider == "openrouter":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url="https://openrouter.ai/api/v1"
            )
            llm_client = OpenAIGenericClient(config=llm_config)
        else:
            return False, f"Unsupported LLM provider: {config.llm_provider}", get_latency_ms(start_time)

        if llm_client:
            message = f"LLM connection successful (provider: {config.llm_provider}, model: {config.llm_model}) - client instantiated"
            return True, message, get_latency_ms(start_time)
        else:
            return False, f"LLM client instantiation failed for {config.llm_provider}", get_latency_ms(start_time)

    except ImportError as e:
        return False, f"Provider not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        return False, f"LLM connection failed: {str(e)}", get_latency_ms(start_time)


async def test_embedding_connection(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test embedding provider connection by validating client instantiation"""
    start_time = time.time()

    try:
        setup_environment_variables(config)
        embedder_client = create_embedder_client(config, start_time)

        if embedder_client:
            message = f"Embedding connection successful (provider: {config.embedder_provider}, model: {config.embedding_model}) - client instantiated"
            return True, message, get_latency_ms(start_time)
        else:
            return False, f"Embedder client instantiation failed for {config.embedder_provider}", get_latency_ms(start_time)

    except ImportError as e:
        return False, f"Provider not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        return False, f"Embedding connection failed: {str(e)}", get_latency_ms(start_time)


async def test_embedding_with_dimensions(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test embedding provider by actually running an embedding and returning dimensions"""
    start_time = time.time()

    try:
        setup_environment_variables(config)
        embedder_client = create_embedder_client(config, start_time)

        if not embedder_client:
            return False, f"Embedder client instantiation failed for {config.embedder_provider}", get_latency_ms(start_time)

        # Test with a sample episode text
        test_episode = "This is a test episode for Graphiti knowledge graph embedding. It contains sample text to verify the embedding model works correctly and returns the expected dimensions."

        # Run the actual embedding
        try:
            if hasattr(embedder_client, 'create'):
                # Standard Graphiti embedder method
                embedding_vector = await embedder_client.create(test_episode)
                dimensions = len(embedding_vector) if isinstance(embedding_vector, list) else 0
                if dimensions > 0:
                    # This code path is now handled above in the create() method block
                    return False, "Embedding test path error", get_latency_ms(start_time)
                else:
                    return False, "No valid embedding returned from provider", get_latency_ms(start_time)
            else:
                # No compatible embedding method found
                return False, f"Embedding client for {config.embedder_provider} does not support create method", get_latency_ms(start_time)
        except Exception as embed_error:
            return False, f"Failed to create embedding: {str(embed_error)}", get_latency_ms(start_time)

        latency = get_latency_ms(start_time)
        message = f"Embedding test successful (provider: {config.embedder_provider}, model: {config.embedding_model}, dimensions: {dimensions})"
        return True, message, latency

    except ImportError as e:
        return False, f"Provider not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        return False, f"Embedding test failed: {str(e)}", get_latency_ms(start_time)


async def test_provider_combination(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test both LLM and embedding providers working together"""
    start_time = time.time()

    try:
        setup_environment_variables(config)

        llm_api_key = config.get_effective_llm_api_key()
        if config.llm_provider == "openai":
            is_reasoning_model = any(config.llm_model.startswith(
                p) for p in ('o1-', 'o1_', 'o3-', 'o3_'))
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            client_params = {
                'config': llm_config,
                'cache': False
            }
            if is_reasoning_model:
                client_params['reasoning'] = getattr(
                    config, 'reasoning_effort', 'medium')
                client_params['verbosity'] = getattr(
                    config, 'verbosity_level', 'low')
            else:
                client_params['reasoning'] = None
                client_params['verbosity'] = None
            llm_client = OpenAIClient(**client_params)
        elif config.llm_provider == "google" or config.llm_provider == "google-ai":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            llm_client = GeminiClient(config=llm_config)
        elif config.llm_provider == "anthropic" or config.llm_provider == "claude":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url=getattr(config, 'llm_base_url', None)
            )
            llm_client = AnthropicClient(config=llm_config)
        elif config.llm_provider == "ollama":
            ollama_base_url = _get_ollama_base_url(
                getattr(config, 'ollama_base_url', None))
            llm_config = LLMConfig(
                api_key="ollama",
                model=config.llm_model,
                small_model=None,
                base_url=ollama_base_url
            )
            llm_client = OpenAIGenericClient(config=llm_config)

        elif config.llm_provider == "venice":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url="https://api.venice.ai/api/v1"
            )
            llm_client = OpenAIGenericClient(config=llm_config)
        elif config.llm_provider == "openrouter":
            llm_config = LLMConfig(
                api_key=llm_api_key,
                model=config.llm_model,
                small_model=getattr(config, 'llm_small_model', None),
                base_url="https://openrouter.ai/api/v1"
            )
            try:
                from .openrouter_client import OpenRouterClient
                llm_client = OpenRouterClient(config=llm_config)
            except ImportError:
                llm_client = OpenAIGenericClient(config=llm_config)
        else:
            return False, f"Unsupported LLM provider: {config.llm_provider}", get_latency_ms(start_time)
        embedder_client = create_embedder_client(config, start_time)

        if llm_client and embedder_client:
            message = f"Provider combination successful (LLM: {config.llm_provider}/{config.llm_model}, Embedding: {config.embedder_provider}/{config.embedding_model}) - both clients instantiated"
            return True, message, get_latency_ms(start_time)
        elif not llm_client:
            return False, f"LLM client instantiation failed for {config.llm_provider}", get_latency_ms(start_time)
        elif not embedder_client:
            return False, f"Embedder client instantiation failed for {config.embedder_provider}", get_latency_ms(start_time)
        else:
            return False, "Unknown provider combination failure", get_latency_ms(start_time)

    except ImportError as e:
        return False, f"Provider not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        return False, f"Provider combination test failed: {str(e)}", get_latency_ms(start_time)


async def test_combination_with_pipeline(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test full LLM + embedding pipeline using the same episode creation path as sync.py"""
    start_time = time.time()

    try:
        from .sync import initialize_graphiti
        from graphiti_core.nodes import EpisodeType
        from datetime import datetime, timezone

        setup_environment_variables(config)

        # Initialize Graphiti using the same path as sync.py
        graphiti = await initialize_graphiti(config, debug=False)
        if not graphiti:
            return False, f"Failed to initialize Graphiti for pipeline test", get_latency_ms(start_time)

        # Create episode using the same parameters as sync.py's create_generic_text_episode
        note_name = "pipeline-test-episode"
        episode_body = "This is a pipeline test episode to verify LLM and embedding integration. Knowledge graphs represent structured information as interconnected entities and relationships."
        source_description = "combination-pipeline-test"
        reference_time = datetime.now(timezone.utc)
        group_id = getattr(config, 'default_namespace', 'pipeline-test')

        episode_kwargs = {
            'name': note_name,
            'episode_body': episode_body,
            'source': EpisodeType.text,
            'source_description': source_description,
            'reference_time': reference_time
        }

        # Add group_id only for Neo4j (match sync.py exactly)
        if getattr(config, 'database_type', 'neo4j').lower() == 'neo4j':
            episode_kwargs['group_id'] = group_id

        try:
            # Call add_episode which internally uses both LLM and embedder
            result = await graphiti.add_episode(**episode_kwargs)

            # Extract episode info from result
            episode_uuid = None
            if hasattr(result, 'episode') and result.episode and hasattr(result.episode, 'uuid'):
                episode_uuid = str(result.episode.uuid)

            entities_count = len(result.nodes) if hasattr(
                result, 'nodes') else 0
            relationships_count = len(result.edges) if hasattr(
                result, 'edges') else 0

            # Build structured cross-encoder info for machine parsing (provider/model/status)
            cross_encoder_info = {
                "provider": getattr(config, 'cross_encoder_client', 'none'),
                "model": getattr(config, 'cross_encoder_model', None),
                "status": "none",
                "active": False,
                "details": {}
            }

            try:
                # Graphiti may expose cross-encoder as .cross_encoder or ._cross_encoder depending on version
                cross_encoder_instance = None
                if hasattr(graphiti, 'cross_encoder') and getattr(graphiti, 'cross_encoder') is not None:
                    cross_encoder_instance = getattr(graphiti, 'cross_encoder')
                    cross_encoder_info['status'] = 'loaded'
                    cross_encoder_info['active'] = True
                elif hasattr(graphiti, '_cross_encoder') and getattr(graphiti, '_cross_encoder') is not None:
                    cross_encoder_instance = getattr(
                        graphiti, '_cross_encoder')
                    cross_encoder_info['status'] = 'loaded'
                    cross_encoder_info['active'] = True
                else:
                    if cross_encoder_info['provider'] and cross_encoder_info['provider'] != 'none':
                        cross_encoder_info['status'] = 'failed'
                    else:
                        cross_encoder_info['status'] = 'none'

                # Extract cross-encoder details if available
                if cross_encoder_instance:
                    try:
                        # Get class name and config details
                        cross_encoder_info['details']['class_name'] = cross_encoder_instance.__class__.__name__

                        # Try to get model info from config if available
                        if hasattr(cross_encoder_instance, 'config'):
                            config_obj = cross_encoder_instance.config
                            if hasattr(config_obj, 'model'):
                                cross_encoder_info['details']['actual_model'] = config_obj.model
                            if hasattr(config_obj, 'api_key') and config_obj.api_key:
                                cross_encoder_info['details']['has_api_key'] = True

                        # For BGE, show it's using local model
                        if 'BGE' in cross_encoder_instance.__class__.__name__:
                            cross_encoder_info['details']['type'] = 'local'
                            cross_encoder_info['details']['note'] = 'BGE uses local model, ignores model parameter'
                        else:
                            cross_encoder_info['details']['type'] = 'api'

                    except Exception as detail_error:
                        cross_encoder_info['details']['extraction_error'] = str(
                            detail_error)

            except Exception as e:
                cross_encoder_info['status'] = 'unknown'
                cross_encoder_info['details']['error'] = str(e)

            # Legacy message format for backward compatibility
            cross_encoder_status = "none"
            if cross_encoder_info['status'] == 'loaded':
                cross_encoder_status = f"{cross_encoder_info['provider']}/{cross_encoder_info['model'] or 'default'}"
            elif cross_encoder_info['status'] == 'failed':
                cross_encoder_status = f"{cross_encoder_info['provider']} (failed to load)"

        except Exception as episode_error:
            return False, f"Episode creation failed: {str(episode_error)}", get_latency_ms(start_time)
        finally:
            # Close connection
            if hasattr(graphiti, 'close'):
                try:
                    await graphiti.close()
                except Exception:
                    pass

        # Pipeline success - episode created with LLM, embedding, and cross-encoder operations
        latency = get_latency_ms(start_time)
        message = f"Full pipeline test successful - LLM: {config.llm_provider}/{config.llm_model}, Embedding: {config.embedder_provider}/{config.embedding_model}, Cross-encoder: {cross_encoder_status}, Episode: {episode_uuid}, Entities: {entities_count}, Relationships: {relationships_count}"

        # Return tuple format to match function signature
        return True, message, latency

    except ImportError as e:
        return False, f"Required modules not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        return False, f"Pipeline test failed: {str(e)}", get_latency_ms(start_time)


async def test_schema_initialization(config: BridgeConfig) -> Tuple[bool, str, int]:
    """Test schema initialization by creating Graphiti instance and initializing schema"""
    start_time = time.time()

    try:
        # Import Graphiti initialization from sync module
        from .sync import initialize_graphiti

        setup_environment_variables(config)

        # Initialize Graphiti instance
        graphiti = await initialize_graphiti(config, debug=True)
        if not graphiti:
            return False, "Failed to initialize Graphiti instance", get_latency_ms(start_time)

        # Initialize schema (build indices and constraints)
        await graphiti.build_indices_and_constraints()

        # Close connection
        if hasattr(graphiti, 'close'):
            await graphiti.close()

        latency = get_latency_ms(start_time)
        return True, f"Schema initialization successful for {config.database_type} database '{config.database_name}'", latency

    except ImportError as e:
        return False, f"Required modules not available: {str(e)}", get_latency_ms(start_time)
    except Exception as e:
        latency = get_latency_ms(start_time)
        error_msg = str(e).lower()

        if "connection refused" in error_msg:
            return False, "Database connection refused. Check if database is running.", latency
        elif "authentication" in error_msg:
            return False, "Database authentication failed. Check credentials.", latency
        else:
            return False, f"Schema initialization failed: {str(e)}", latency


def main():
    """Main entry point for connection testing"""
    parser = argparse.ArgumentParser(
        description='Test connections for Graphiti Bridge')
    parser.add_argument('--test-type', choices=['database', 'llm', 'embedding', 'embedding-test', 'combination', 'combination-pipeline', 'episode-test', 'schema-init'], required=True,
                        help='Type of connection to test')
    parser.add_argument('--config', type=str, help='JSON configuration string')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')

    args = parser.parse_args()
    # Mirror sync.py: suppress all non-JSON output in non-debug mode
    original_stderr = sys.stderr
    if not args.debug:
        try:
            sys.stderr = open(os.devnull, 'w')
            logging.disable(logging.CRITICAL)
            for logger_name in ['', 'root', 'graphiti', 'graphiti_core', 'graphiti_bridge', 'openai', 'httpx', 'neo4j', 'asyncio', 'urllib3', 'httpcore']:
                logger_obj = logging.getLogger(logger_name)
                logger_obj.disabled = True
                logger_obj.setLevel(logging.CRITICAL + 1)
                logger_obj.handlers.clear()
        except Exception:
            pass
    logger = setup_logging(args.debug)

    try:
        # Parse configuration
        if args.config:
            config_dict = json.loads(args.config)
        else:
            config_dict = json.loads(sys.stdin.read())

        config = BridgeConfig.from_dict(config_dict)
        setup_environment_variables(config)

        # Validate configuration
        validation_errors = validate_config(config, args.test_type)
        if validation_errors:
            print_json_response({
                'success': False,
                'message': f'Configuration validation failed: {"; ".join(validation_errors)}'
            })
            return

        # Execute the appropriate test
        if args.test_type == 'database':
            success, message, latency = test_database_connection(config)
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})
        elif args.test_type == 'llm':
            success, message, latency = asyncio.run(
                test_llm_connection(config))
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})
        elif args.test_type == 'embedding':
            success, message, latency = asyncio.run(
                test_embedding_connection(config))
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})
        elif args.test_type == 'embedding-test':
            success, message, latency = asyncio.run(
                test_embedding_with_dimensions(config))
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})
        elif args.test_type == 'combination':
            success, message, latency = asyncio.run(
                test_provider_combination(config))
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})
        elif args.test_type == 'combination-pipeline':
            # Run the heavier end-to-end pipeline test: actual LLM completion + embedding creation
            try:
                result = asyncio.run(test_combination_with_pipeline(config))
                if isinstance(result, dict):
                    # New structured format with cross_encoder info
                    print_json_response(result)
                else:
                    # Legacy tuple format (fallback)
                    success, message, latency = result
                    print_json_response(
                        {'success': success, 'message': message, 'latency': latency})
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print_json_response({
                    'success': False,
                    'message': f'Combination pipeline test failed: {str(e)}',
                    'traceback': tb,
                    'latency': 0
                })
        elif args.test_type == 'episode-test':
            # @purpose: run a safe, small episode creation to verify end-to-end sync path
            # @depends: initialize_graphiti from sync.py to mirror production flow
            # @output: prints JSON with 'episode_uuid' on success
            try:
                # Import initialize_graphiti and helper from sync to ensure identical initialization path
                from .sync import initialize_graphiti, extract_episode_uuid_from_result
                setup_environment_variables(config)
                # Initialize Graphiti (debug=True to surface errors in structured output)
                graphiti = asyncio.run(initialize_graphiti(config, debug=True))
                if not graphiti:
                    print_json_response(
                        {'success': False, 'message': 'Failed to initialize Graphiti for episode-test', 'latency': 0})
                else:
                    # Build episode payload matching sync.py's create_generic_text_episode exactly
                    from graphiti_core.nodes import EpisodeType
                    from datetime import datetime, timezone

                    note_name = "episode-test-automated"
                    episode_body = "This is a small test episode created by episode-test to verify pipeline."
                    source_description = "episode-test"
                    reference_time = datetime.now(timezone.utc)
                    group_id = getattr(
                        config, 'default_namespace', 'test-namespace')

                    episode_kwargs = {
                        'name': note_name,
                        'episode_body': episode_body,
                        'source': EpisodeType.text,
                        'source_description': source_description,
                        'reference_time': reference_time
                    }

                    # Add group_id only for Neo4j (match sync.py exactly)
                    if getattr(config, 'database_type', 'neo4j').lower() == 'neo4j':
                        episode_kwargs['group_id'] = group_id

                    try:
                        # add_episode is async in current Graphiti versions
                        result = asyncio.run(
                            graphiti.add_episode(**episode_kwargs))
                        # Attempt to extract episode UUID from result
                        episode_uuid = extract_episode_uuid_from_result(
                            result, debug_mode=True, logger=None)
                        latency = get_latency_ms(time.time())
                        print_json_response(
                            {'success': True, 'message': 'Episode created', 'latency': latency, 'episode_uuid': episode_uuid})
                    except Exception as ep_err:
                        latency = get_latency_ms(time.time())
                        print_json_response(
                            {'success': False, 'message': f'Episode creation failed: {str(ep_err)}', 'latency': latency})
                    finally:
                        # Close graphiti if possible
                        if hasattr(graphiti, 'close'):
                            try:
                                # Simple cleanup without async complexity
                                if hasattr(graphiti, 'close'):
                                    pass  # Cleanup handled elsewhere in async context
                            except Exception:
                                pass
            except ImportError as e:
                print_json_response(
                    {'success': False, 'message': f'Modules required for episode-test not available: {str(e)}', 'latency': 0})
            except Exception as e:
                print_json_response(
                    {'success': False, 'message': f'episode-test failed: {str(e)}', 'latency': 0})
        elif args.test_type == 'schema-init':
            success, message, latency = asyncio.run(
                test_schema_initialization(config))
            print_json_response(
                {'success': success, 'message': message, 'latency': latency})

    except json.JSONDecodeError as e:
        import traceback
        tb = traceback.format_exc()
        print_json_response({
            'success': False,
            'message': f'Invalid JSON configuration: {str(e)}',
            'traceback': tb
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Connection test failed: {e}")
        logger.debug(f"Full traceback: {tb}")
        print_json_response({
            'success': False,
            'message': f'Connection test failed: {str(e)}',
            'traceback': tb
        })


if __name__ == '__main__':
    main()
