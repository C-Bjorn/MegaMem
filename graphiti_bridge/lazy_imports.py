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

# Only import these when ACTUALLY creating the clients


def get_bge_reranker_client():
    """Load BGE reranker only when needed"""
    try:
        from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
        return BGERerankerClient
    except ImportError:
        return None


def get_gemini_reranker_client():
    """Load Gemini reranker only when needed"""
    try:
        from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
        return GeminiRerankerClient
    except ImportError:
        return None


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
