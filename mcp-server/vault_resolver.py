import json
from typing import Dict, Any


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
