"""
Token-scoped access control for the MegaMem MCP HTTP transport.

Kept dependency-free (stdlib only) so TokenProfile / current_token_profile /
check_cross_vault_permission can be unit-tested without importing the full
megamem_mcp_server module, which pulls in graphiti-core and other heavy deps.

@purpose: Per-token vault/tool/database allowlisting + cross-vault permission gating
@depends: nothing beyond stdlib (dataclasses, contextvars)
@results: Shared TokenProfile model + ContextVar used by megamem_mcp_server's
          BearerAuthMiddleware, list_tools/call_tool gating, and the Day75.05
          cross-vault copy_to_vault/move_to_vault permission check.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional


@dataclass
class TokenProfile:
    """Per-token access policy for the Streamable HTTP transport.
    @purpose: Allowlist-based tool gating per bearer token @depends: httpTokenProfiles in data.json @results: Server-side MCP access control
    """
    id: str = ''
    label: str = ''
    token: str = ''
    # Empty lists = no restriction (admin). Non-empty = strict allowlist.
    allowed_tools: List[str] = dc_field(default_factory=list)
    allowed_group_ids: List[str] = dc_field(default_factory=list)
    allowed_databases: List[str] = dc_field(default_factory=list)
    allowed_vaults: List[str] = dc_field(default_factory=list)


# Set by BearerAuthMiddleware on each HTTP request; read by list_tools / call_tool.
# Default None = stdio mode (no profile → full access).
current_token_profile: ContextVar[Optional[TokenProfile]] = ContextVar('current_token_profile', default=None)


def check_cross_vault_permission(
    source_vault_id: Optional[str], target_vault_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Combined read(source) + write(target) permission check for cross-vault
    note operations (Day75.05: copy_to_vault / move_to_vault).

    Reuses the existing allowed_vaults allowlist — a token with no vault
    restriction (empty allowed_vaults, e.g. admin/stdio) passes unconditionally.
    Fails fast, naming which side (source or target) was denied.
    """
    profile = current_token_profile.get()
    if not profile or not profile.allowed_vaults:
        return None
    if source_vault_id and source_vault_id not in profile.allowed_vaults:
        return {
            "success": False,
            "error": f"Read access to source vault '{source_vault_id}' is not permitted for this token",
            "error_code": "VAULT_NOT_PERMITTED",
        }
    if target_vault_id and target_vault_id not in profile.allowed_vaults:
        return {
            "success": False,
            "error": f"Write access to target vault '{target_vault_id}' is not permitted for this token",
            "error_code": "VAULT_NOT_PERMITTED",
        }
    return None
