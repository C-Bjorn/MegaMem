"""
Endogon Pro service client: entitlement validation (validate-api-key) + the
ask_bjorn agent-turn tool (ask-bjorn endpoint).

@purpose: Single reusable auth/timeout/retry/error-translation core for calling
Endogon's Pro-gated services. Today this backs only `ask_bjorn`; Day85.02's
`second_opinion` (metered) is expected to reuse this same core rather than
duplicating auth-header construction, timeout handling, retry logic, or error
translation. Do not add second_opinion-specific behavior here yet.
@depends: httpx (async HTTP client) — already a transitive dependency of this
package via openai/graphiti-core, and already imported the same way by
graphiti_bridge/openrouter_client.py and graphiti_bridge/ollama_client.py.
@results: mcp-server/megamem_mcp_server.py can gate/register/call ask_bjorn
without any Endogon-specific HTTP, retry, or error-message logic living in the
server file itself. Every documented error `code` from the ask-bjorn/validate-
api-key contract is raised as a distinguishable, named exception carrying a
plain-English, user-facing message — callers must never surface a raw HTTP
status or upstream error body.
"""

import hashlib
import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger('graphiti_bridge.endogon')

# --- Endpoints ---
VALIDATE_KEY_URL = "https://scvfligtdujbsqhuieye.supabase.co/functions/v1/validate-api-key"
ASK_BJORN_URL = "https://endogon.com/api/tokens/ask-bjorn"

# --- Timeouts / retry / cache tuning ---
# Client-side timeout is intentionally longer than the server's own 20s+5-step
# agent budget, so the client never times out before the server can return a
# truncated:true partial response.
ASK_BJORN_TIMEOUT_SECONDS = 30.0
VALIDATE_KEY_TIMEOUT_SECONDS = 10.0
VALIDATE_KEY_CACHE_TTL_SECONDS = 300  # 5 minutes
# Exactly one retry, and only for a genuine transport failure (connection error/
# timeout) — never for an ambiguous HTTP 4xx/5xx response, which risks a
# duplicate agent turn on the server side.
MAX_TRANSIENT_RETRIES = 1

# Capability string the entitlement gate checks for in validate-api-key's
# `capabilities` array.
ASK_BJORN_CAPABILITY = "service.ask_bjorn"


def mask_key(key: str) -> str:
    """Never log a raw Endogon key. Mirrors the masking style already used in
    src/settings/ProSettingsTab.ts (`key.slice(0,8) + '****' + key.slice(-4)`)."""
    if not key:
        return ""
    if len(key) > 12:
        return f"{key[:8]}****{key[-4:]}"
    return "****"


# ---------------------------------------------------------------------------
# Named exceptions — one per documented error `code`, plus two for conditions
# outside the documented table (genuine network failure, undocumented code).
# Every instance carries a plain-English `.message` — the only thing a caller
# should ever surface to a user. `.code` lets a caller distinguish conditions
# programmatically (e.g. to decide whether to invalidate the validate_key
# cache) without string-matching the message.
# ---------------------------------------------------------------------------

class EndogonError(Exception):
    """Base for every named Endogon API error condition."""
    code: str = "unknown_error"

    def __init__(
        self,
        message: str,
        *,
        balance_microusd: Optional[float] = None,
        topup_url: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.balance_microusd = balance_microusd
        self.topup_url = topup_url


class InvalidKeyError(EndogonError):
    """401 invalid_key — no key configured, or key malformed/revoked."""
    code = "invalid_key"


class KeyNotFoundError(EndogonError):
    """401 key_not_found — same remedy as InvalidKeyError, distinct code."""
    code = "key_not_found"


class MissingCapabilityError(EndogonError):
    """403 missing_capability — membership doesn't include this service."""
    code = "missing_capability"


class FrozenAccountError(EndogonError):
    """403 frozen — account frozen; direct the user to contact support."""
    code = "frozen"


class InvalidConversationError(EndogonError):
    """403 invalid_conversation — conversation_id is stale/invalid. Recoverable:
    callers should drop the conversation_id and retry as a first message rather
    than surfacing this as a hard failure to the model."""
    code = "invalid_conversation"


class RateLimitedError(EndogonError):
    """429 rate_limited — fair-use limit hit (20/min). Do not auto-retry."""
    code = "rate_limited"


class ServiceDisabledError(EndogonError):
    """503 service_disabled / service_disabled_by_member — service currently
    disabled, either site-wide or by the member's own toggle."""
    code = "service_disabled"


class ServiceConfigUnavailableError(EndogonError):
    """500 service_config_unavailable — transient internal Endogon lookup
    failure."""
    code = "service_config_unavailable"


class ServiceUnavailableError(EndogonError):
    """502 service_unavailable — the upstream agent itself failed. Never
    surface the raw upstream error/stack to the user."""
    code = "service_unavailable"


class EndogonNetworkError(EndogonError):
    """Genuine transport/connection failure (not a documented HTTP error
    response) after the single bounded retry was exhausted."""
    code = "network_error"


class EndogonUnknownError(EndogonError):
    """Fallback for an undocumented error `code` or unexpected HTTP status.
    Still translated to a plain-English message — never a raw stringified
    exception."""
    code = "unknown_error"


# code -> (exception class, default user-facing message)
_ERROR_CODE_MAP = {
    "invalid_key": (
        InvalidKeyError,
        "Your Endogon Pro key is missing or invalid. Check and re-paste your key in Pro settings.",
    ),
    "key_not_found": (
        KeyNotFoundError,
        "Your Endogon Pro key is missing or invalid. Check and re-paste your key in Pro settings.",
    ),
    "missing_capability": (
        MissingCapabilityError,
        "Your Endogon membership doesn't include Ask Bjorn. Upgrade at endogon.com/stewards.",
    ),
    "frozen": (
        FrozenAccountError,
        "Your Endogon account is frozen. Contact Endogon support to resolve this.",
    ),
    "invalid_conversation": (
        InvalidConversationError,
        "Your Ask Bjorn conversation has expired; starting a new one.",
    ),
    "rate_limited": (
        RateLimitedError,
        "You've hit the Ask Bjorn fair-use rate limit (20/min). Wait a minute and try again.",
    ),
    "service_disabled": (
        ServiceDisabledError,
        "Ask Bjorn is currently disabled. Please try again later.",
    ),
    "service_disabled_by_member": (
        ServiceDisabledError,
        "You have disabled Ask Bjorn in your Endogon account settings.",
    ),
    "service_config_unavailable": (
        ServiceConfigUnavailableError,
        "Endogon's service configuration is temporarily unavailable. Try again shortly.",
    ),
    "service_unavailable": (
        ServiceUnavailableError,
        "Ask Bjorn is temporarily unavailable. Try again shortly.",
    ),
}

# Error codes that mean the currently-cached validate_key result is stale and
# must be invalidated immediately (revoked/rotated key, downgraded membership).
_CACHE_INVALIDATING_CODES = frozenset({"invalid_key", "key_not_found", "missing_capability"})


def _translate_error_response(body: Dict[str, Any]) -> EndogonError:
    """Map a documented error JSON body {error, code, balance_microusd?, topup_url?}
    to a named exception with a plain-English message. Falls back to
    EndogonUnknownError (still a plain-English message) for any undocumented code
    — never returns the raw body/status to the caller."""
    code = body.get("code") or ""
    exc_cls, default_message = _ERROR_CODE_MAP.get(
        code, (EndogonUnknownError, "Ask Bjorn is temporarily unavailable. Try again shortly.")
    )
    return exc_cls(
        default_message,
        balance_microusd=body.get("balance_microusd"),
        topup_url=body.get("topup_url"),
    )


class EndogonClient:
    """
    Client for Endogon's Pro-gated services: key validation (the entitlement
    gate megamem_mcp_server.py uses to decide whether to register ask_bjorn at
    all) and the ask_bjorn agent tool itself.

    Deliberately scoped to only what ask_bjorn + the entitlement gate need.
    The auth-header construction, timeout constants, retry helper, and error-
    translation function above are structured to be reused as-is by a future
    sibling method (Day85.02 second_opinion) — do not add anything second-
    opinion-specific to this class yet.
    """

    def __init__(self):
        # Keyed by sha256(key) -> {"result": dict, "expires_at": float (time.monotonic)}
        # The plaintext key is never used as a dict key or logged — only its hash.
        self._validate_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _auth_header(key: str) -> Dict[str, str]:
        bearer = key if key.startswith("Bearer ") else f"Bearer {key}"
        return {"Authorization": bearer}

    def invalidate_cache(self, key: str) -> None:
        """Force the next validate_key() call for this key to hit the network
        instead of returning a cached result. Called automatically by ask_bjorn()
        whenever a live call returns invalid_key/key_not_found/missing_capability,
        so a revoked/rotated key or a downgraded membership is caught quickly even
        inside the 5-minute TTL window."""
        self._validate_cache.pop(self._hash_key(key), None)

    async def validate_key(self, key: str) -> Dict[str, Any]:
        """Calls validate-api-key and returns the parsed JSON body as-is:
        {"valid": bool, "plan": str, "expires_at": str|None,
         "entitlements": [...], "content_packages": [...], "capabilities": [...]}.

        This endpoint always returns HTTP 200, even for an invalid key — a
        `valid: false` body is a normal return value, not an exception. Raises
        EndogonNetworkError only on a genuine network/transport failure.

        Result is cached in-memory for VALIDATE_KEY_CACHE_TTL_SECONDS, keyed by
        a SHA-256 hash of the key (the plaintext key is never stored or logged).
        """
        cache_key = self._hash_key(key)
        now = time.monotonic()
        cached = self._validate_cache.get(cache_key)
        if cached and cached["expires_at"] > now:
            return cached["result"]

        try:
            async with httpx.AsyncClient(timeout=VALIDATE_KEY_TIMEOUT_SECONDS) as client:
                resp = await client.post(VALIDATE_KEY_URL, json={"key": key})
                resp.raise_for_status()
                result = resp.json()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.error(f"validate-api-key network failure for key {mask_key(key)}: {e}")
            raise EndogonNetworkError(
                "Could not reach Endogon to validate your key. Check your connection and try again."
            ) from e
        except httpx.HTTPStatusError as e:
            # Documented contract says this endpoint always returns 200 — an
            # unexpected status here is treated as a transient failure, not one
            # of the documented ask-bjorn error codes.
            logger.error(
                f"validate-api-key returned unexpected HTTP {e.response.status_code} "
                f"for key {mask_key(key)}"
            )
            raise EndogonNetworkError(
                "Endogon key validation failed unexpectedly. Try again shortly."
            ) from e

        self._validate_cache[cache_key] = {
            "result": result,
            "expires_at": now + VALIDATE_KEY_CACHE_TTL_SECONDS,
        }
        return result

    async def ask_bjorn(
        self,
        key: str,
        question: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POSTs to the ask-bjorn endpoint per the documented contract.

        - 30s client-side timeout (headroom over the server's 20s+5-step budget).
        - Exactly one retry, and only on a transient network failure (connection
          error/timeout) — never on any HTTP 4xx/5xx response.
        - On success (HTTP 200), returns the parsed JSON body as-is, INCLUDING
          truncated:true — that is a soft-degraded success, not an error.
        - On any documented error `code`, raises the corresponding named
          EndogonError subclass with a plain-English message. Also invalidates
          the validate_key cache for this key when the code indicates the key/
          entitlement itself is no longer good (invalid_key, key_not_found,
          missing_capability).
        """
        payload: Dict[str, Any] = {"question": question}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        headers = self._auth_header(key)
        last_network_error: Optional[Exception] = None

        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=ASK_BJORN_TIMEOUT_SECONDS) as client:
                    resp = await client.post(ASK_BJORN_URL, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_network_error = e
                if attempt < MAX_TRANSIENT_RETRIES:
                    logger.info(
                        f"ask_bjorn transient network failure (attempt {attempt + 1}), retrying once"
                    )
                    continue
                logger.error(f"ask_bjorn network failure after retry for key {mask_key(key)}: {e}")
                raise EndogonNetworkError(
                    "Could not reach Ask Bjorn. Check your connection and try again."
                ) from e

            # A real HTTP response was received — never retry from here on,
            # regardless of status code (avoids duplicate agent turns).
            if resp.status_code == 200:
                return resp.json()

            try:
                body = resp.json()
            except ValueError:
                body = {}

            error = _translate_error_response(body)
            if error.code in _CACHE_INVALIDATING_CODES:
                self.invalidate_cache(key)
            logger.info(
                f"ask_bjorn returned {error.code} (HTTP {resp.status_code}) for key {mask_key(key)}"
            )
            raise error

        # Unreachable in practice (the loop above always returns or raises),
        # kept only so static analysis sees an exhaustive return.
        raise EndogonNetworkError("Could not reach Ask Bjorn.") from last_network_error
