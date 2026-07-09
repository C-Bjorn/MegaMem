import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse


def parse_obsidian_uri(path: str) -> tuple[str, Optional[str]]:
    """
    Parse an `obsidian://` URI into (file_path, vault_name).

    Supports the two common forms:
      - obsidian://open?vault=NAME&file=PATH
      - obsidian://advanced-uri?vault=NAME&filepath=PATH

    Plain (non-URI) input, or a malformed/unrecognized obsidian:// URI,
    passes through unchanged as (path, None) — callers should only apply
    the vault override when one is actually returned.

    Examples:
      'obsidian://open?vault=test-vault&file=Folder%2FNote'
        → ('Folder/Note', 'test-vault')
      'Folder/Note' (plain path) → ('Folder/Note', None)
    """
    if not path or not path.startswith("obsidian://"):
        return path, None
    try:
        params = parse_qs(urlparse(path).query)
        vault = params.get("vault", [None])[0]
        file_param = params.get("file", params.get("filepath", [None]))[0]
        if file_param is None:
            return path, None
        return unquote(file_param), vault
    except Exception:
        return path, None


class VaultResolver:
    """
    Resolves the correct namespace (group_id) based on Obsidian plugin settings.
    """

    def get_active_namespace(self, obsidian_config: Dict[str, Any]) -> str:
        """
        Determines the group_id based on the namespaceStrategy.
        - "vault": Uses the vault's name.
        - "custom": Uses the custom defaultNamespace setting.
        """
        strategy = obsidian_config.get("namespaceStrategy", "vault")

        if strategy == "custom":
            return obsidian_config.get("defaultNamespace", "obsidian-vault")

        if strategy == "vault":
            # The vault name is expected to be in the config from the plugin
            vault_name = obsidian_config.get("vaultName")
            if vault_name:
                return vault_name

        # Fallback to default namespace
        return obsidian_config.get("defaultNamespace", "obsidian-vault")
