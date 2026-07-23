"""
Ollama-specific LLM client that bounds context window size and call duration.

@purpose: Fix two confirmed upstream graphiti_core gaps (Day78.04 / GitHub Issue #20)
          for the local Ollama provider branch only.
@depends: graphiti_core.llm_client.openai_generic_client.OpenAIGenericClient (base class),
          openai.AsyncOpenAI, httpx.Timeout
@results: LLM calls have a bounded HTTP timeout. Context-window bounding for real
          Ollama servers is NOT achieved by this client alone — see Day78.04b note
          below and `ensure_bounded_ollama_model()` for the mechanism that actually
          works against Ollama.

Background (confirmed via direct inspection of graphiti_core v0.29.2 and v0.30.0pre5 —
identical in both, no upstream fix available):
1. graphiti_core.llm_client.config.LLMConfig has no num_ctx/context-length field, and
   OpenAIGenericClient._generate_response passes no extra_body to
   chat.completions.create() — so a local Ollama model loads at its provider default
   context window regardless of what the model actually needs. Originally observed:
   ~22GB reserved for a 2.5GB qwen3:4b model at its native max context, vs ~3.9GB
   when manually bounded to num_ctx=8192.
2. LLMConfig also has no timeout field, so LLM calls have no bounded duration.
   OpenAIGenericClient.__init__ accepts an optional pre-built `client` instance,
   completely independent of LLMConfig — the same injection point graphiti_bridge's
   own OpenRouterClient already uses (see openrouter_client.py) to set
   httpx.Timeout(...) directly on the AsyncOpenAI client.

Day78.04b correction (live-verified 2026-07 against a real Ollama 0.32.1 install,
model qwen2.5:3b — see tests/manual/day78_04b_ollama_numctx_live_check.py):
`extra_body={'options': {'num_ctx': ...}}` on `chat.completions.create()` is NOT
honored by Ollama's OpenAI-compatible `/v1/chat/completions` endpoint on this
version — the model always loads at its native max context regardless of the
requested num_ctx (confirmed reproducible via the OpenAI client, and via raw HTTP
requests with both a nested `options.num_ctx` and a flattened top-level `num_ctx`
key). Ollama's *native* `/api/chat` endpoint DOES honor the identical
`options.num_ctx` payload. This is a known, still-open upstream gap in Ollama's
OpenAI compatibility layer (ollama/ollama#5356, ollama/ollama#6544) — not something
graphiti_bridge can fix by changing the request shape.

The extra_body passthrough below is kept (not removed) because other OpenAI-
compatible local servers users may point this client at (e.g. vLLM) DO honor
`extra_body` for engine-specific options. For real Ollama servers, the context
window is instead bounded by `ensure_bounded_ollama_model()` (see below), which
pre-creates a derivative model with `num_ctx` baked into its own manifest via
Ollama's native `/api/create` — Ollama then loads that model at the bounded
context regardless of which endpoint serves the actual chat request, since the
bound now lives in the model definition instead of a per-request option.

This subclass follows the OpenRouterClient precedent already established in this
package: keep LLMConfig untouched (upstream-shaped), and inject provider-specific
behavior (extra_body passthrough, bounded timeout) at the client-construction and
_generate_response level instead.
"""

import json
import logging
import typing
from pathlib import Path
from typing import Optional

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.prompts.models import Message

logger = logging.getLogger('graphiti_bridge.sync')

DEFAULT_MODEL = 'llama3.1'
DEFAULT_NUM_CTX = 8192
DEFAULT_TIMEOUT_SECONDS = 30.0
DERIVATIVE_MODEL_TAG = 'mm'
DERIVATIVE_STATE_FILENAME = '.ollama_derivative_models.json'


class OllamaGenericClient(OpenAIGenericClient):
    """
    Thin subclass of OpenAIGenericClient scoped to Ollama's OpenAI-compatible
    endpoint. Adds num_ctx passthrough (via extra_body) and a bounded HTTP
    timeout, neither of which LLMConfig can carry.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: typing.Any = None,
        num_ctx: int = DEFAULT_NUM_CTX,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if cache:
            raise NotImplementedError('Caching is not implemented for Ollama')

        if config is None:
            config = LLMConfig()

        self.num_ctx = num_ctx

        # Build our own AsyncOpenAI client with a bounded timeout when the
        # caller hasn't supplied one — mirrors OpenRouterClient's pattern.
        # Read gets the long end of the budget (model inference); connect/write/
        # pool stay short since those never take as long as generation does.
        if client is None:
            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=10.0),
            )

        super().__init__(config=config, cache=cache, client=client)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})
        try:
            response = await self.client.chat.completions.create(
                model=self.model or DEFAULT_MODEL,
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={'type': 'json_object'},
                # extra_body.options is the OpenAI-compat convention several local
                # servers (vLLM, etc.) use to accept engine-specific options such as
                # num_ctx. Live-verified NOT honored by Ollama 0.32.1's own
                # /v1/chat/completions endpoint (ollama/ollama#5356, #6544) — for real
                # Ollama servers the context bound comes from ensure_bounded_ollama_model()
                # instead (see module docstring). Kept here for non-Ollama OpenAI-compat
                # backends that do respect it.
                extra_body={'options': {'num_ctx': self.num_ctx}},
            )
            result = response.choices[0].message.content or ''
            return json.loads(result)
        except openai.RateLimitError as e:
            raise RateLimitError from e
        except Exception as e:
            logger.error(f'Error in generating LLM response: {e}')
            raise


def _derivative_model_name(base_model: str, num_ctx: int) -> str:
    """Build a deterministic derivative model name for a bounded-context clone of
    an Ollama model. Ollama model names are `name[:tag]` — append `-mm<ctx>` to
    the tag (or to the bare name if untagged) so the derivative is unambiguous
    and can't collide with a tag the user pulled themselves."""
    if ':' in base_model:
        name, tag = base_model.split(':', 1)
        return f'{name}:{tag}-{DERIVATIVE_MODEL_TAG}{num_ctx}'
    return f'{base_model}-{DERIVATIVE_MODEL_TAG}{num_ctx}'


async def _get_model_digest(client: httpx.AsyncClient, model: str) -> Optional[str]:
    """Look up a model's manifest digest via Ollama's native /api/tags list
    (the OpenAI-compat surface has no equivalent)."""
    resp = await client.get('/api/tags')
    resp.raise_for_status()
    for entry in resp.json().get('models', []):
        if entry.get('name') == model:
            return entry.get('digest')
    return None


def _load_derivative_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_derivative_state(state_path: Path, state: dict) -> None:
    try:
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except Exception:
        logger.warning(f'[Day78.04b] Could not persist Ollama derivative-model state to {state_path}')


async def ensure_bounded_ollama_model(
    ollama_base_url: str,
    base_model: str,
    num_ctx: int,
    state_path: Path,
    timeout: float = 60.0,
) -> str:
    """
    Day78.04b (Issue #20) — the mechanism that actually bounds real Ollama memory.

    Ollama's OpenAI-compat endpoint does not honor extra_body.num_ctx (see module
    docstring), so instead of a per-request option this pre-creates a derivative
    model (`<base>-mm<num_ctx>`) via Ollama's native `/api/create`, with `num_ctx`
    baked into the derivative's own manifest via `parameters`. `/api/create` with a
    `from:` reference does not re-download or duplicate blobs — the derivative
    shares the base model's weights and only adds a new manifest layer. Ollama then
    loads the derivative at the bounded context regardless of which endpoint
    (native or OpenAI-compat) serves the actual chat request.

    The derivative is only (re)created when the base model's digest changes (i.e.
    the user re-pulled/updated it) or `num_ctx` changes, tracked via a small JSON
    state file at `state_path` — avoids rebuilding the manifest on every sync.

    @param ollama_base_url: the OpenAI-compat base URL (e.g. 'http://localhost:11434/v1');
           the native API root is derived by stripping the '/v1' suffix.
    @returns: the model name to use in place of `base_model` when constructing
              LLMConfig for OllamaGenericClient. Falls back to `base_model` itself
              (unbounded) if the native API call fails for any reason — callers
              should treat that as a soft-fail, not a sync-blocking error.
    """
    derivative = _derivative_model_name(base_model, num_ctx)
    native_base_url = ollama_base_url.rsplit('/v1', 1)[0] or 'http://localhost:11434'

    async with httpx.AsyncClient(base_url=native_base_url, timeout=timeout) as client:
        base_digest = await _get_model_digest(client, base_model)
        if base_digest is None:
            logger.warning(f"[Day78.04b] Base Ollama model '{base_model}' not found via /api/tags — "
                            f"skipping bounded-context derivative, using base model unbounded")
            return base_model

        state = _load_derivative_state(state_path)
        cached = state.get(derivative)
        derivative_digest = await _get_model_digest(client, derivative)

        if (cached and cached.get('base_digest') == base_digest
                and cached.get('num_ctx') == num_ctx and derivative_digest is not None):
            return derivative

        logger.info(f"[Day78.04b] Creating/updating bounded-context Ollama model '{derivative}' "
                    f"(base='{base_model}', num_ctx={num_ctx}) — MegaMem manages this derivative "
                    f"model automatically so real syncs don't load '{base_model}' at its unbounded "
                    f"native context window.")
        resp = await client.post('/api/create', json={
            'model': derivative,
            'from': base_model,
            'parameters': {'num_ctx': num_ctx},
            'stream': False,
        })
        resp.raise_for_status()

        state[derivative] = {'base_digest': base_digest, 'num_ctx': num_ctx}
        _save_derivative_state(state_path, state)
        return derivative
