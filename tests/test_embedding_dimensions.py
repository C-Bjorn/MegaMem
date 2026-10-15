"""Keep explicit legacy vector sizes consistent across bridge entry points."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from openai.types import CreateEmbeddingResponse

from graphiti_bridge.config import BridgeConfig
from graphiti_bridge.sync import create_embedder_client


pytestmark = pytest.mark.unit


def config_payload():
    return {
        "llmProvider": "openai",
        "llmModel": "gpt-4o-mini",
        "apiKeys": {"openai": "test-key"},
        "databaseType": "neo4j",
        "databases": [
            {
                "id": "primary",
                "type": "neo4j",
                "uri": "bolt://localhost:7687",
                "database": "neo4j",
                "embedderProvider": "openai",
                "embeddingModel": "text-embedding-3-small",
            },
            {
                "id": "secondary",
                "type": "neo4j",
                "uri": "bolt://localhost:7688",
                "database": "other",
                "embedderProvider": "openai",
                "embeddingModel": "text-embedding-3-small",
                "embeddingDimensions": 512,
            },
        ],
    }


async def returned_vectors(config):
    """Replace only the network request; exercise the real SDK response and embedder."""
    embedder = create_embedder_client(config)
    native = [float(i) for i in range(1536)]
    response = CreateEmbeddingResponse(
        data=[{"embedding": native, "index": 0, "object": "embedding"}],
        model="text-embedding-3-small",
        object="list",
        usage={"prompt_tokens": 1, "total_tokens": 1},
    )
    embedder.client.embeddings.create = AsyncMock(return_value=response)
    try:
        single = await embedder.create("synthetic query")
        batch = await embedder.create_batch(["synthetic query"])
        return single, batch
    finally:
        await embedder.client.close()


def test_explicit_legacy_dimensions_preserve_single_and_batch_vectors():
    payload = config_payload()
    payload["databases"][0]["embeddingDimensions"] = 1024
    single, batch = asyncio.run(returned_vectors(BridgeConfig.from_dict(payload)))
    expected = [float(i) for i in range(1024)]
    assert single == expected
    assert batch == [expected]


def test_unset_dimensions_preserve_native_output():
    single, batch = asyncio.run(returned_vectors(BridgeConfig.from_dict(config_payload())))
    expected = [float(i) for i in range(1536)]
    assert single == expected
    assert batch == [expected]


def test_named_database_uses_its_own_dimensions():
    payload = config_payload()
    payload["databases"][0]["embeddingDimensions"] = 1024
    config = BridgeConfig.from_dict(payload, db_entry=payload["databases"][1])
    single, _ = asyncio.run(returned_vectors(config))
    assert len(single) == 512


def test_sync_payload_dimensions_override_database_defaults():
    payload = config_payload()
    payload["databases"][0]["embeddingDimensions"] = 1024
    payload["embedding_dimensions"] = 256
    single, _ = asyncio.run(returned_vectors(BridgeConfig.from_dict(payload)))
    assert len(single) == 256


@pytest.mark.parametrize("dimensions", [0, -1, True, "1024", 1.5])
def test_invalid_dimensions_fail_before_any_api_request(dimensions):
    payload = config_payload()
    payload["embedding_dimensions"] = dimensions
    with pytest.raises(ValueError, match="embedding.*dimensions"):
        create_embedder_client(BridgeConfig.from_dict(payload))
