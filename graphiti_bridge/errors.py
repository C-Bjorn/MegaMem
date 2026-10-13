"""
Lightweight, dependency-free exception types shared across graphiti_bridge modules.

@purpose: InfrastructureError is caught in a top-level `except` clause in
sync.py's process_note() that must be reachable regardless of which LLM provider
branch actually ran. Defining it here (stdlib only, no graphiti_core/openai/httpx)
lets sync.py import it eagerly and cheaply, while OpenRouterClient itself (and the
rest of openrouter_client.py's heavy import chain) is deferred to on-first-use via
graphiti_bridge/lazy_imports.py. See Day85.03.
@depends: nothing (stdlib only)
@results: sync.py's `except InfrastructureError` works without eagerly importing
openrouter_client.py on every daemon/MCP-server launch.
"""


class InfrastructureError(Exception):
    """Raised when the service provider has infrastructure issues."""
    pass
