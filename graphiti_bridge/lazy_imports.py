"""
Lazy import wrapper for heavy dependencies.
Only loads modules when they're actually used.
"""
import sys
import time


class LazyModule:
    """Lazy loader for expensive modules"""

    def __init__(self, module_name):
        self.module_name = module_name
        self._module = None

    def __getattr__(self, attr):
        if self._module is None:
            start = time.time()
            print(
                f"[LAZY-LOAD] Loading {self.module_name} on first use...", file=sys.stderr)
            self._module = __import__(self.module_name, fromlist=[''])
            print(
                f"[LAZY-LOAD] {self.module_name} loaded in {time.time() - start:.2f}s", file=sys.stderr)
        return getattr(self._module, attr)

def get_gemini_embedder():
    """Load Gemini embedder only when needed"""
    try:
        from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
        return GeminiEmbedder, GeminiEmbedderConfig
    except ImportError:
        return None, None


def get_voyage_embedder():
    """Load Voyage embedder only when needed"""
    try:
        from graphiti_core.embedder.voyage import VoyageAIEmbedder, VoyageAIEmbedderConfig
        return VoyageAIEmbedder, VoyageAIEmbedderConfig
    except ImportError:
        return None, None


def get_azure_embedder():
    """Load Azure embedder only when needed"""
    try:
        from graphiti_core.embedder.azure_openai import AzureOpenAIEmbedderClient
        return AzureOpenAIEmbedderClient
    except ImportError:
        return None


# --- Day85.03: provider LLM clients / drivers ---
# @purpose: sync.py previously imported every graphiti_core provider client (OpenAI,
# Anthropic, Gemini, Neo4j, FalkorDB) at module scope, unconditionally, on every daemon
# and MCP-server process launch. Measured cost on a real client machine: 57s for a
# single `from . import sync` line (see Day85.03 DevDoc PERF-TIMING data). A given
# vault's BridgeConfig only ever names one LLM provider and one driver at sync time, so
# eagerly importing all five provider families pays 100% of the import weight to use
# ~20% of it. These accessors defer each import to first actual use, following the same
# pattern already established above for Gemini/Voyage/Azure embedders.
# @depends: graphiti_core (only imports the specific submodule needed, not the full
# provider matrix)
# @results: A vault configured for e.g. OpenAI+Neo4j only ever imports those two client
# families, regardless of which other providers this codebase supports.

def get_openai_client():
    """Load graphiti_core's OpenAIClient only when the openai LLM provider is selected."""
    from graphiti_core.llm_client.openai_client import OpenAIClient
    return OpenAIClient


def get_openai_generic_client():
    """Load graphiti_core's OpenAIGenericClient only when an OpenAI-compatible provider
    (venice, or the base class used by ollama_client.py/openrouter_client.py) is selected."""
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    return OpenAIGenericClient


def get_anthropic_client():
    """Load graphiti_core's AnthropicClient only when the anthropic LLM provider is selected."""
    from graphiti_core.llm_client.anthropic_client import AnthropicClient
    return AnthropicClient


def get_gemini_client():
    """Load graphiti_core's GeminiClient only when the google/google-ai LLM provider is selected."""
    from graphiti_core.llm_client.gemini_client import GeminiClient
    return GeminiClient


def get_neo4j_driver():
    """Load graphiti_core's Neo4jDriver only when database_type is neo4j (the default)."""
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    return Neo4jDriver


# Day86.02: graphiti-core re-clones the FalkorDB driver to database=group_id at two
# independent call sites -- Graphiti.add_episode/add_episode_bulk (graphiti_core/
# graphiti.py) and inside every FalkorDB ops file's get_by_group_ids() read path (8
# files: entity_node_ops, entity_edge_ops, episode_node_ops, episodic_edge_ops,
# community_node_ops, community_edge_ops, saga_node_ops, has_episode_edge_ops,
# next_episode_edge_ops). Both call sites invoke driver.clone(database=...) on
# whatever driver instance graphiti-core is holding, so overriding this one method
# neutralizes both without touching graphiti-core. group_id remains a logical
# property filtered in Cypher inside the single pinned graph, exactly as it already
# behaves on Neo4j (whose driver.clone() is a no-op inherited from the base class --
# confirmed unaffected, not touched here).
_PINNED_FALKOR_DRIVER = None


def get_falkor_driver():
    """Load graphiti_core's FalkorDriver only when database_type is falkordb.
    Preserves the original graceful-fallback semantics: returns (None, False) if the
    falkordb extra isn't installed, instead of raising ImportError.

    Day86.02: returns PinnedGraphFalkorDriver (a FalkorDriver subclass), not the raw
    graphiti-core class. Its clone() ignores the database argument entirely and
    returns self, so no FalkorDB write or read path can silently repoint the driver
    at a different physical graph than the one the user configured. See module
    comment above for why one method override is sufficient."""
    global _PINNED_FALKOR_DRIVER
    try:
        from graphiti_core.driver.falkordb_driver import FalkorDriver
    except ImportError:
        return None, False

    if _PINNED_FALKOR_DRIVER is None:
        class PinnedGraphFalkorDriver(FalkorDriver):
            """FalkorDriver whose clone() never repoints the driver at a different
            physical graph than the one it was constructed with (Day86.02)."""

            def clone(self, database: str) -> 'FalkorDriver':  # noqa: ARG002 - database intentionally ignored
                return self

        _PINNED_FALKOR_DRIVER = PinnedGraphFalkorDriver

    return _PINNED_FALKOR_DRIVER, True


def get_falkordb_client():
    """Load falkordb-py's raw async FalkorDB client (Day86.01).
    graphiti_core's FalkorDriver has no ssl kwarg of its own -- the only way to enable
    TLS is to pre-construct this client with ssl=True and hand it to FalkorDriver via
    its falkor_db= escape hatch (see sync.py build_falkor_connection() usage). Only
    imported when a FalkorDB connection actually requests TLS."""
    from falkordb.asyncio import FalkorDB
    return FalkorDB


def get_openai_reranker_client():
    """Load graphiti_core's OpenAIRerankerClient only when constructing the no-op cross
    encoder stub (needed on every sync regardless of LLM provider, but cheap on its own)."""
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    return OpenAIRerankerClient


def get_openai_embedder():
    """Load graphiti_core's OpenAIEmbedder/OpenAIEmbedderConfig only when the embedder
    provider is openai, ollama, or openrouter (all three reuse this same OpenAI-compatible
    embedder class with a different base_url)."""
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    return OpenAIEmbedder, OpenAIEmbedderConfig


def get_openrouter_client():
    """Load graphiti_bridge's own OpenRouterClient (and its openai/httpx/graphiti_core
    import chain) only when the openrouter LLM provider is selected. InfrastructureError
    lives separately in graphiti_bridge/errors.py (stdlib-only) so sync.py's top-level
    `except InfrastructureError` clause works without eagerly importing this module."""
    from .openrouter_client import OpenRouterClient
    return OpenRouterClient


def get_ollama_client():
    """Load graphiti_bridge's own OllamaGenericClient (and its openai/httpx/graphiti_core
    import chain) only when the ollama LLM provider is selected."""
    from .ollama_client import OllamaGenericClient, ensure_bounded_ollama_model, DERIVATIVE_STATE_FILENAME
    return OllamaGenericClient, ensure_bounded_ollama_model, DERIVATIVE_STATE_FILENAME
