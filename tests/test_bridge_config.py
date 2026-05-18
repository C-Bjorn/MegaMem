from graphiti_bridge.config import BridgeConfig


def test_from_dict_uses_neo4j_database_config_credentials():
    config = BridgeConfig.from_dict(
        {
            "databaseType": "neo4j",
            "databaseConfigs": {
                "neo4j": {
                    "uri": "bolt://db.example:7687",
                    "username": "configured-user",
                    "password": "configured-pass",
                    "database": "configured-db",
                }
            },
            "llmProvider": "ollama",
            "llmModel": "llama3",
            "embedderProvider": "ollama",
            "embeddingModel": "nomic-embed-text",
        }
    )

    assert config.database_url == "bolt://db.example:7687"
    assert config.database_username == "configured-user"
    assert config.database_password == "configured-pass"
    assert config.database_name == "configured-db"


def test_from_dict_uses_primary_database_entry_when_legacy_config_is_empty():
    config = BridgeConfig.from_dict(
        {
            "databaseType": "neo4j",
            "databaseConfigs": {},
            "databases": [
                {
                    "id": "primary",
                    "type": "neo4j",
                    "category": "primary",
                    "enabled": True,
                    "uri": "bolt://primary.example:7687",
                    "username": "primary-user",
                    "password": "primary-pass",
                    "database": "primary-db",
                }
            ],
            "llmProvider": "ollama",
            "llmModel": "llama3",
            "embedderProvider": "ollama",
            "embeddingModel": "nomic-embed-text",
        }
    )

    assert config.database_url == "bolt://primary.example:7687"
    assert config.database_username == "primary-user"
    assert config.database_password == "primary-pass"
    assert config.database_name == "primary-db"


def test_from_dict_prefers_primary_database_entry_over_stale_legacy_config():
    config = BridgeConfig.from_dict(
        {
            "databaseType": "neo4j",
            "databaseConfigs": {
                "neo4j": {
                    "uri": "bolt://stale.example:7687",
                    "username": "stale-user",
                    "password": "stale-pass",
                    "database": "stale-db",
                }
            },
            "databases": [
                {
                    "id": "primary",
                    "type": "neo4j",
                    "category": "local",
                    "enabled": True,
                    "uri": "bolt://primary.example:7687",
                    "username": "primary-user",
                    "password": "primary-pass",
                    "database": "primary-db",
                }
            ],
            "llmProvider": "ollama",
            "llmModel": "llama3",
            "embedderProvider": "ollama",
            "embeddingModel": "nomic-embed-text",
        }
    )

    assert config.database_url == "bolt://primary.example:7687"
    assert config.database_username == "primary-user"
    assert config.database_password == "primary-pass"
    assert config.database_name == "primary-db"


def test_from_dict_accepts_camel_case_api_keys():
    config = BridgeConfig.from_dict(
        {
            "databaseType": "neo4j",
            "apiKeys": {
                "openai": "openai-key",
            },
            "llmProvider": "openai",
            "llmModel": "gpt-4o",
            "embedderProvider": "openai",
            "embeddingModel": "text-embedding-3-small",
        }
    )

    assert config.api_keys == {"openai": "openai-key"}
    assert config.get_effective_llm_api_key() == "openai-key"
    assert config.get_effective_embedder_api_key() == "openai-key"
