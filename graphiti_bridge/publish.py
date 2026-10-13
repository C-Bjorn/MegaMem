#!/usr/bin/env python3
"""
Graphiti Bridge Publish Script

CONTEXT: Replicates selected group_id namespaces from a source Graphiti graph to a
destination Graphiti graph. Day79.01 Task 2 (local Neo4j -> local Neo4j only; Aura is
Task 1, the Svelte UI is Task 3, the automated pytest canary suite is Task 4 - all
separate subtasks). See DevDoc: "Day79.01 - Graph Publishing - Scoped Replica to
Neo4j Aura" for full architecture rationale.

PURPOSE: group_id is the ONLY selection predicate for publishing - do not add a
per-note or per-episode publish flag anywhere in this module (entities/edges are
deduped WITHIN a group_id, so any finer-grained flag would be structurally unsafe).

Mirrors sync.py's CLI-module entrypoint shape (`python -m graphiti_bridge.publish`)
and its stdin-JSON-in / line-by-line-JSON-progress-on-stdout protocol, so
GraphitiService.ts can eventually spawn this the same way it spawns sync.py.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# UTF-8 stdout/stdin encoding for Windows environments (mirrors sync.py)
try:
    if hasattr(sys, 'stdout') and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys, 'stdin') and hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
except Exception:
    pass

from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.edges import EntityEdge, EpisodicEdge, HasEpisodeEdge, NextEpisodeEdge
from graphiti_core.embedder import EmbedderClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.nodes import CommunityNode, EntityNode, EpisodicNode, SagaNode
from graphiti_core.utils.bulk_utils import add_nodes_and_edges_bulk

from .config import BridgeConfig
from .utils import print_json_response, print_final_json_response

logger = logging.getLogger('graphiti_bridge.publish')

# @purpose: named constants, not magic numbers (DevDoc hard requirement 3 / 7)
# CHUNK_SIZE bounds every add_nodes_and_edges_bulk()/save_bulk() call so a multi-thousand-
# record scoped set never lands in a single write transaction against a memory-limited
# destination (e.g. Aura Free). One transaction per chunk; a failed chunk re-runs cleanly
# because every write in this module is a MERGE-by-uuid upsert (naturally idempotent).
CHUNK_SIZE = 250

# Step 3/4 (Day79.01 subtask, 2026-08-10) - derived publish-mode constants. Defined here
# (rather than alongside resolve_publish_mode() further down) because fetch_scoped_records()
# below uses PUBLISH_MODE_COPY as a default argument value, and default argument values are
# evaluated at module-import time, before later module-level code runs.
PUBLISH_MODE_COPY = 'copy'
PUBLISH_MODE_RE_EMBED = 're_embed'
PUBLISH_MODE_COPY_NO_DEST_EMBEDDER = 'copy_no_dest_embedder'
# PAGE_SIZE bounds cursor-paginated reads from the source graph (EntityNode.get_by_group_ids
# etc. all support uuid_cursor pagination) so list_source_group_ids()/publish() never issue
# one unbounded MATCH against a large production graph.
PAGE_SIZE = 500

METADATA_NODE_LABEL = 'PublishMetadata'
METADATA_SINGLETON_ID = 'singleton'
# Ruling 3 (Day79.01 Phase A correction, 2026-08-09): per-group_id publish records live
# on a SEPARATE node label from the destination-wide singleton. See write_publish_metadata()/
# read_publish_group_metadata() docstrings for the full rationale - the prior singleton-only
# design made last_publish_at report the WRONG answer for any group_id except the most
# recently published one.
METADATA_GROUP_NODE_LABEL = 'PublishMetadataGroup'

# Ruling 4 (Day79.01 Phase A correction, 2026-08-09): explicit, obviously-fake sentinel for
# BridgeConfig's placeholder vault_path, replacing os.getcwd(). publish.py never touches
# vault/note-processing code, so vault_path is structurally meaningless here - but cwd()
# looked like a real value and would silently point at an arbitrary directory once this
# runs headless via MCP (the caller's cwd at spawn time, not anything vault-related). A
# sentinel that is obviously not a path fails loudly/visibly if anything ever tries to
# treat it as one, instead of quietly resolving to "wherever the process happened to start".
PUBLISH_JOB_VAULT_PATH_SENTINEL = '__publish_job_no_vault__'


# ---------------------------------------------------------------------------
# Raising embedder guard (hard requirement 2)
# ---------------------------------------------------------------------------

class RaisingEmbedder(EmbedderClient):
    """
    PURPOSE: belt-and-braces guard against add_nodes_and_edges_bulk_tx()'s per-record
    re-embed gate (`if node.name_embedding is None: await node.generate_name_embedding(embedder)`,
    `if edge.fact_embedding is None: await edge.generate_embedding(embedder)` -
    graphiti_core/utils/bulk_utils.py:168-169,193-194, verified against the installed
    0.29.3 source at ../graphiti/graphiti_core/utils/bulk_utils.py).

    That check is per-record. If the read stage in this module has a bug that loads
    embeddings for most-but-not-all records, a real embedder passed to the destination
    would silently regenerate the stragglers using a different model than the source
    used - producing a graph with mixed-provenance vectors that looks completely healthy.

    Passing this stub as the destination's embedder (and, belt-and-braces, the source's
    embedder too, since publish.py never legitimately calls .create() on either side)
    turns any such gap into a stack trace instead of a silent inconsistency. Combined
    with the explicit non-None assertions in fetch_scoped_*() below, an embedding gap
    can never reach the bulk write call unnoticed.

    Satisfies graphiti_core.embedder.client.EmbedderClient (verified 2026-08-09 against
    ../graphiti/graphiti_core/embedder/client.py): abstract `create()` plus `create_batch()`
    (which already raises NotImplementedError by default - overridden here anyway for an
    explicit, publish.py-specific error message).
    """

    async def create(self, input_data):
        raise RuntimeError(
            'RaisingEmbedder.create() was invoked. publish.py must never generate new '
            'embeddings - this means the read stage failed to load an embedding for at '
            'least one record before handing it to the bulk write call. Failing loudly '
            'per the no-fallback rule; do not catch this and continue.'
        )

    async def create_batch(self, input_data_list):
        raise RuntimeError(
            'RaisingEmbedder.create_batch() was invoked. publish.py must never generate '
            'new embeddings - see RaisingEmbedder.create() docstring.'
        )


def _make_noop_cross_encoder() -> OpenAIRerankerClient:
    """
    Minimal stub satisfying Graphiti's cross_encoder constructor requirement, mirroring
    the exact pattern already used in graphiti_bridge/sync.py's _make_noop_cross_encoder().
    Inlined here (rather than `from .sync import _make_noop_cross_encoder`) because
    sync.py's module-level imports pull in every optional LLM provider client
    (GeminiClient, VoyageAIEmbedder, etc.), some of which raise ImportError at import
    time in environments that haven't installed those optional extras - publish.py has
    no need for that dependency surface at all, so it defines its own copy instead of
    inheriting sync.py's heavier import chain.
    """
    noop = OpenAIRerankerClient(config=LLMConfig(api_key='noop', model='noop'))

    async def rank(query: str, passages: list, top_k=None):
        return [(p, 0.0) for p in passages]

    noop.rank = rank
    return noop


def _noop_llm_client() -> OpenAIClient:
    """
    PURPOSE: publish.py never calls add_episode/LLM extraction on either side - it only
    moves already-extracted Graphiti model instances. Graphiti's constructor still
    requires an llm_client (defaults to a real OpenAIClient() needing OPENAI_API_KEY if
    none is passed). Mirrors sync.py's _make_noop_cross_encoder() pattern: a real client
    class instantiated with a placeholder key that is never actually called over the
    network in this module.
    """
    return OpenAIClient(config=LLMConfig(api_key='noop', model='noop'), cache=False)


# ---------------------------------------------------------------------------
# group_id routing (hard requirement 8)
# ---------------------------------------------------------------------------

def resolve_dest_group_id(source_group_id: str) -> str:
    """
    PURPOSE: single choke point for group_id on the write path. No per-tenant remap is
    implemented yet (deliberately deferred per DevDoc Architecture Notes - "Route
    group_id through one function"), but every write in this module routes the
    destination group_id through this function rather than reading node.group_id /
    edge.group_id inline in multiple places. When a remap is eventually needed, this
    is the one line that changes.

    NOTE: once a remap exists here, the orphan sweep must scope by the *destination*
    group_id (this function's output), not the source group_id - see Architecture Notes
    "Consequence to record now".
    """
    return source_group_id


# ---------------------------------------------------------------------------
# Graphiti instance construction (reuses sync.py's driver-construction pattern)
# ---------------------------------------------------------------------------

async def _build_graphiti(config: BridgeConfig) -> Graphiti:
    """
    Build a Graphiti instance for one side (source or destination) of a publish run.

    Reuses the exact Neo4jDriver construction pattern from sync.py's
    initialize_graphiti() (verified against graphiti_bridge/sync.py:995-1000) rather than
    inventing a new one. Always wires RaisingEmbedder (hard requirement 2) plus noop
    LLM/cross-encoder clients, since publish.py never legitimately performs inference or
    embedding generation on either side.
    """
    driver = Neo4jDriver(
        uri=config.database_url,
        user=config.database_username,
        password=config.database_password,
        database=config.database_name or 'neo4j',
    )
    graphiti = Graphiti(
        graph_driver=driver,
        llm_client=_noop_llm_client(),
        embedder=RaisingEmbedder(),
        cross_encoder=_make_noop_cross_encoder(),
        store_raw_episode_content=True,
    )
    # Idempotent (MERGE/IF NOT EXISTS-based) - also self-heals "destination schema
    # missing" since Neo4jDriver.__init__ only schedules this on a running loop, which
    # may not have existed yet depending on call context.
    await graphiti.build_indices_and_constraints()
    return graphiti


async def _close_graphiti(graphiti: Optional[Graphiti]) -> None:
    if graphiti is None:
        return
    try:
        await graphiti.driver.close()
    except Exception as e:
        logger.warning(f'Error closing driver: {e}')


def _database_identifier(config: BridgeConfig) -> str:
    """Human-readable, non-secret identifier for a database side (used in logs/metadata)."""
    return f"{config.database_url}/{config.database_name or 'neo4j'}"


# ---------------------------------------------------------------------------
# list_source_group_ids
# ---------------------------------------------------------------------------

async def list_source_group_ids(source_config: BridgeConfig) -> List[Dict[str, Any]]:
    """
    Enumerate group_ids present in the source graph with node/edge/episode counts, for
    the (future, Task 3) UI group_id selector.

    One aggregation query per Graphiti record type, merged by group_id in Python. Keeps
    each query simple and correct rather than one large UNION query; this runs rarely
    (UI selector population), not on the write hot path.
    """
    graphiti = await _build_graphiti(source_config)
    driver = graphiti.driver
    counts: Dict[str, Dict[str, int]] = {}

    queries = [
        ('entity_count', 'MATCH (n:Entity) WHERE n.group_id IS NOT NULL RETURN n.group_id AS group_id, count(n) AS c'),
        ('episode_count', 'MATCH (n:Episodic) WHERE n.group_id IS NOT NULL RETURN n.group_id AS group_id, count(n) AS c'),
        ('saga_count', 'MATCH (n:Saga) WHERE n.group_id IS NOT NULL RETURN n.group_id AS group_id, count(n) AS c'),
        ('entity_edge_count', 'MATCH ()-[r:RELATES_TO]->() WHERE r.group_id IS NOT NULL RETURN r.group_id AS group_id, count(r) AS c'),
        ('episodic_edge_count', 'MATCH ()-[r:MENTIONS]->() WHERE r.group_id IS NOT NULL RETURN r.group_id AS group_id, count(r) AS c'),
        ('has_episode_edge_count', 'MATCH ()-[r:HAS_EPISODE]->() WHERE r.group_id IS NOT NULL RETURN r.group_id AS group_id, count(r) AS c'),
        ('next_episode_edge_count', 'MATCH ()-[r:NEXT_EPISODE]->() WHERE r.group_id IS NOT NULL RETURN r.group_id AS group_id, count(r) AS c'),
    ]

    try:
        for field, cypher in queries:
            records, _, _ = await driver.execute_query(cypher, routing_='r')
            for record in records:
                gid = record['group_id']
                counts.setdefault(gid, {}).setdefault(field, 0)
                counts[gid][field] = record['c']
    finally:
        await _close_graphiti(graphiti)

    result = []
    for gid, field_counts in sorted(counts.items()):
        row = {'group_id': gid}
        for field, _ in queries:
            row[field] = field_counts.get(field, 0)
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# Community count (hard requirement 5 - exclude entirely, but signal it)
# ---------------------------------------------------------------------------

async def count_communities_in_scope(driver, group_ids: List[str]) -> int:
    """
    One query counting CommunityNode instances in the scoped source group_ids.
    Expected to be zero (this codebase never sets update_communities=True - verified
    against graphiti_bridge/sync.py's add_episode() calls and graphiti_core's
    Graphiti.add_episode() default of update_communities=False). Communities are
    excluded from publish entirely; this function exists purely to make that exclusion
    a structured, surfaced signal rather than a comment that can rot.
    """
    communities = await CommunityNode.get_by_group_ids(driver, group_ids)
    return len(communities)


# ---------------------------------------------------------------------------
# Scoped reads with pagination + embedding loading (hard requirement 1)
# ---------------------------------------------------------------------------

async def _paginate(fetch_page, group_ids: List[str]) -> list:
    """Generic cursor-pagination helper for the *.get_by_group_ids(driver, group_ids, limit, cursor) family."""
    items: list = []
    cursor: Optional[str] = None
    while True:
        page = await fetch_page(group_ids, PAGE_SIZE, cursor)
        if not page:
            break
        items.extend(page)
        if len(page) < PAGE_SIZE:
            break
        cursor = page[-1].uuid
    return items


async def fetch_scoped_records(
    graphiti: Graphiti, group_ids: List[str], mode: str = PUBLISH_MODE_COPY
) -> Dict[str, list]:
    """
    Read every Graphiti-model record in scope from the source graph.

    COPY / COPY_NO_DEST_EMBEDDER mode (default, UNCHANGED behavior) - hard requirement 1:
    explicitly load embeddings before returning, since name_embedding/fact_embedding are
    excluded from Graphiti's default return queries (verified against
    ../graphiti/graphiti_core/models/nodes/node_db_queries.py and the Neo4j
    load_embeddings_bulk() implementations at
    ../graphiti/graphiti_core/driver/neo4j/operations/entity_{node,edge}_ops.py:223-254).
    Asserts non-None embeddings on every entity node / entity edge before returning - fails
    loudly (no silent skip) if any record is missing its embedding, per the "no fallback
    paths" project rule.

    RE_EMBED mode (Step 3, Day79.01 subtask 2026-08-10) - the INVERSE of the above,
    deliberately: do NOT call load_embeddings_bulk() and do NOT assert non-None for entity
    nodes/edges. name_embedding/fact_embedding are left exactly as EntityNode.get_by_group_ids()/
    EntityEdge.get_by_group_ids() already returned them - None, per the same
    node_db_queries.py exclusion cited above (embeddings are never part of the default
    return projection in the first place; COPY mode's load_embeddings_bulk() call is what
    backfills them). add_nodes_and_edges_bulk_tx()'s own per-record gate
    (`if node.name_embedding is None: await node.generate_name_embedding(embedder)` -
    ../graphiti/graphiti_core/utils/bulk_utils.py:167-169, :192-194) then calls whatever
    REAL embedder publish() passes it (see _build_real_dest_embedder()) to regenerate a
    fresh vector from `node.name`/`edge.fact` - strings already present on these records,
    already read from source. This is NOT the ingestion pipeline: no LLM extraction, no
    dedup, no temporal invalidation happens here or anywhere else in this module - only
    vector regeneration from a string that already exists on an already-extracted record.

    Sagas are unaffected by `mode` entirely - SagaNode has no name_embedding/fact_embedding
    field at all (verified: SagaNode.model_fields has no embedding-related key), so there
    is no embedding concept to load, skip, or regenerate for it in either mode.

    Returns a dict of lists keyed by record type.
    """
    driver = graphiti.driver

    entity_nodes: List[EntityNode] = await _paginate(
        lambda gids, limit, cursor: EntityNode.get_by_group_ids(driver, gids, limit, cursor),
        group_ids,
    )
    episodic_nodes: List[EpisodicNode] = await _paginate(
        lambda gids, limit, cursor: EpisodicNode.get_by_group_ids(driver, gids, limit, cursor),
        group_ids,
    )
    saga_nodes: List[SagaNode] = await _paginate(
        lambda gids, limit, cursor: SagaNode.get_by_group_ids(driver, gids, limit, cursor),
        group_ids,
    )

    entity_edges: List[EntityEdge] = []
    try:
        entity_edges = await _paginate(
            lambda gids, limit, cursor: EntityEdge.get_by_group_ids(driver, gids, limit, cursor),
            group_ids,
        )
    except Exception as e:
        # GroupsEdgesNotFoundError is raised (not returned empty) when zero edges match -
        # treat that specific case as "no edges in scope", re-raise anything else.
        if 'GroupsEdgesNotFoundError' not in type(e).__name__:
            raise

    episodic_edges: List[EpisodicEdge] = []
    try:
        episodic_edges = await _paginate(
            lambda gids, limit, cursor: EpisodicEdge.get_by_group_ids(driver, gids, limit, cursor),
            group_ids,
        )
    except Exception as e:
        if 'GroupsEdgesNotFoundError' not in type(e).__name__:
            raise

    has_episode_edges: List[HasEpisodeEdge] = await _paginate(
        lambda gids, limit, cursor: HasEpisodeEdge.get_by_group_ids(driver, gids, limit, cursor),
        group_ids,
    )
    next_episode_edges: List[NextEpisodeEdge] = await _paginate(
        lambda gids, limit, cursor: NextEpisodeEdge.get_by_group_ids(driver, gids, limit, cursor),
        group_ids,
    )

    if mode == PUBLISH_MODE_RE_EMBED:
        # Step 3: deliberately do NOT load embeddings and do NOT assert non-None here -
        # see this function's docstring. name_embedding/fact_embedding stay None exactly as
        # returned by get_by_group_ids(), so add_nodes_and_edges_bulk_tx()'s own per-record
        # gate regenerates them using the REAL destination embedder publish() passes in.
        pass
    else:
        # Hard requirement 1 (COPY / COPY_NO_DEST_EMBEDDER, UNCHANGED): explicitly load
        # embeddings, then assert non-None on every record.
        if entity_nodes:
            await graphiti.nodes.entity.load_embeddings_bulk(entity_nodes, batch_size=PAGE_SIZE)
        if entity_edges:
            await graphiti.edges.entity.load_embeddings_bulk(entity_edges, batch_size=PAGE_SIZE)

        missing_name_embeddings = [n.uuid for n in entity_nodes if n.name_embedding is None]
        if missing_name_embeddings:
            raise RuntimeError(
                f'{len(missing_name_embeddings)} entity node(s) have no name_embedding after '
                f'load_embeddings_bulk() - refusing to publish. Example uuids: '
                f'{missing_name_embeddings[:5]}'
            )
        missing_fact_embeddings = [e.uuid for e in entity_edges if e.fact_embedding is None]
        if missing_fact_embeddings:
            raise RuntimeError(
                f'{len(missing_fact_embeddings)} entity edge(s) have no fact_embedding after '
                f'load_embeddings_bulk() - refusing to publish. Example uuids: '
                f'{missing_fact_embeddings[:5]}'
            )

    # Hard requirement 8: route group_id through the single choke point before any write.
    for record in (*entity_nodes, *episodic_nodes, *saga_nodes, *entity_edges,
                   *episodic_edges, *has_episode_edges, *next_episode_edges):
        record.group_id = resolve_dest_group_id(record.group_id)

    return {
        'entity_nodes': entity_nodes,
        'episodic_nodes': episodic_nodes,
        'saga_nodes': saga_nodes,
        'entity_edges': entity_edges,
        'episodic_edges': episodic_edges,
        'has_episode_edges': has_episode_edges,
        'next_episode_edges': next_episode_edges,
    }


def _sample_source_embedding_dim(scoped: Dict[str, list]) -> Optional[int]:
    """
    NOTE (Day79.01 subtask, 2026-08-10): despite the name, this is also reused AFTER a
    RE-EMBED write pass completes (see publish()) - EntityNode.generate_name_embedding()/
    EntityEdge.generate_embedding() (../graphiti/graphiti_core/nodes.py,
    ../graphiti/graphiti_core/edges.py) mutate `self.name_embedding`/`self.fact_embedding`
    IN PLACE, and `scoped['entity_nodes']`/`scoped['entity_edges']` hold references to the
    exact same objects add_nodes_and_edges_bulk() was called with - so after a RE-EMBED
    write, this function correctly samples the DESTINATION's real written dimension, not
    the source's. Verified by reading generate_name_embedding()/generate_embedding()
    source directly.
    """
    for node in scoped['entity_nodes']:
        if node.name_embedding is not None:
            return len(node.name_embedding)
    for edge in scoped['entity_edges']:
        if edge.fact_embedding is not None:
            return len(edge.fact_embedding)
    return None


# ---------------------------------------------------------------------------
# Step 2 (Day79.01 subtask, 2026-08-10 - "destination == query embedder" correction):
# preflight WARNING when the source's stored (measured) vectors disagree with what the
# source's OWN CONFIGURED embedder implies. Non-blocking, distinct from a refusal - see
# preflight()'s embedder_dimension_mismatch/embedder_model_mismatch refusals below, which
# are unaffected by this addition and continue to fire on destination-vs-source disagreement.
# ---------------------------------------------------------------------------

# Best-effort IDENTITY HINT ONLY - mirrors src/settings/LLMDefaults.ts's embeddingDefaults
# tables (kept intentionally small: only entries actually used anywhere in this project's
# settings UI). NEVER authoritative: nothing downstream of the Step 2 warning below reads
# this table, and a stale/missing entry can only mean the warning silently doesn't fire for
# that model - it can never cause a wrong refusal, a wrong write, or a wrong publish mode
# (mode derivation in resolve_publish_mode() below deliberately does NOT use this table -
# see that function's docstring for why dimension alone is not a safe identity proxy).
KNOWN_EMBEDDER_DIMS: Dict[str, Dict[str, int]] = {
    'openai': {
        'text-embedding-3-small': 1536,
        'text-embedding-3-large': 3072,
        'text-embedding-ada-002': 1536,
    },
    'openrouter': {
        'openai/text-embedding-3-small': 1536,
        'openai/text-embedding-3-large': 3072,
        'openai/text-embedding-ada-002': 1536,
        'qwen/qwen3-embedding-8b': 4096,
        'qwen/qwen3-embedding-4b': 2048,
        'qwen/qwen3-embedding-0.6b': 1024,
        'google/gemini-embedding-001': 3072,
        'mistralai/mistral-embed-2312': 1024,
        'baai/bge-large-en-v1.5': 1024,
        'baai/bge-base-en-v1.5': 768,
        'baai/bge-m3': 1024,
    },
    'google': {
        'text-embedding-005': 768,
        'text-embedding-004': 768,
        'text-multilingual-embedding-002': 768,
    },
    'voyage': {
        'voyage-3': 1024,
        'voyage-3-lite': 512,
        'voyage-large-2-instruct': 1024,
        'voyage-code-2': 1536,
        'voyage-finance-2': 1024,
        'voyage-law-2': 1024,
        'voyage-multilingual-2': 1024,
    },
    'ollama': {
        'nomic-embed-text:latest': 768,
        'nomic-embed-text': 768,
        'mxbai-embed-large': 1024,
        'snowflake-arctic-embed': 1024,
        'all-minilm': 384,
        'e5-mistral-7b': 4096,
    },
}


def _expected_source_embedder_dim(source_config: BridgeConfig) -> Optional[int]:
    """
    Best-effort identity hint for what the source's CONFIGURED embedder ought to produce -
    NOT what its vectors were actually measured to be (that is
    _sample_source_embedding_dim()/preflight()'s live query, which is always the ground
    truth). Returns None when the (provider, model) pair is not in KNOWN_EMBEDDER_DIMS -
    that simply means no warning fires for it (never a refusal, never a block).
    """
    provider_table = KNOWN_EMBEDDER_DIMS.get(source_config.embedder_provider)
    if not provider_table:
        return None
    return provider_table.get(source_config.embedding_model)


# ---------------------------------------------------------------------------
# Step 3 + Step 4 (Day79.01 subtask, 2026-08-10): derived embedder MODE. Never a UI
# selector or a second independently-settable fact - see resolve_publish_mode() docstring.
# PUBLISH_MODE_COPY / PUBLISH_MODE_RE_EMBED / PUBLISH_MODE_COPY_NO_DEST_EMBEDDER are
# defined near CHUNK_SIZE at the top of this file (fetch_scoped_records() needs
# PUBLISH_MODE_COPY as a default argument value, evaluated at module-import time).
# ---------------------------------------------------------------------------


def resolve_publish_mode(
    source_config: BridgeConfig,
    dest_config: BridgeConfig,
    dest_existing_metadata: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """
    Derives the publish mode (COPY / RE-EMBED / COPY-no-dest-embedder-configured) from
    facts that already live in exactly one place each - source_config's and dest_config's
    embedder_provider/embedding_model (already configured in MegaMem DB settings) plus the
    destination's own PublishMetadata singleton (already written by every prior successful
    publish). NEVER an argument a caller passes and NEVER exposed as a UI selector -
    corrected parity rule requires derivation, not a second copy of the same fact that can
    drift out of sync with reality exactly like the old "source == destination" rule did.

    "Same embedder" (COPY-eligible) is decided by (embedder_provider, embedding_model)
    IDENTITY, never by comparing raw dimensions. Two unrelated models can coincidentally
    share a dimension (e.g. nomic-embed-text and bge-base-en-v1.5 are both 768D - see
    KNOWN_EMBEDDER_DIMS above), so dimension equality alone is not a safe proxy for "these
    vectors are semantically compatible" - that was exactly the kind of proxy-instead-of-
    fact reasoning that produced the original wrong rule this subtask corrects. Dimension
    IS still used, but only for two narrower, existing purposes that are unaffected by this
    function: Step 2's measured-vs-configured advisory warning above, and the pre-existing
    embedder_dimension_mismatch/embedder_model_mismatch HARD REFUSALS in preflight() (which
    fire independently of what mode this function returns).

    Three cases, in priority order:

    1. Destination has no embedder configured at all (dest_config.embedder_provider/
       embedding_model empty) -> COPY_NO_DEST_EMBEDDER. Unchanged fallback behavior: COPY
       proceeds, and the existing embedder_dimension_mismatch refusal in preflight() still
       protects against a silent mismatch. Nothing in this subtask alters this path.

    2. Step 4 - destination-embedder-CHANGE detection, checked BEFORE the source/destination
       comparison and independent of it: if PublishMetadata's singleton (from the most
       recent prior publish to this destination) recorded a DIFFERENT embedder_provider/
       embedder_model than dest_config's CURRENT configuration, the destination currently
       holds vectors from a stale model. Force RE-EMBED even if source's embedder happens
       to equal the destination's NEW configuration - the danger being guarded against is
       two incompatible vector spaces coexisting on one destination, and that risk comes
       entirely from the DESTINATION's own history, not from source/destination agreement.
       Every publish() call in this codebase already processes the FULL scoped set on every
       run (fetch_scoped_records() has no incremental/changed-only path anywhere in this
       module) - so returning RE-EMBED here automatically satisfies "force a full re-embed
       of the entire scoped set, not incremental" with no separate code path required.

    3. Otherwise: COPY if source_config and dest_config agree on (embedder_provider,
       embedding_model); RE-EMBED if they disagree.

    Returns (mode, info) where info carries a human-readable 'reason' plus whatever extra
    fields are relevant to that reason, for preflight()'s disclosure payload / progress
    events - never swallowed, always surfaced to the caller per the "disclose, don't ask"
    UI requirement.
    """
    dest_has_embedder = bool(dest_config.embedder_provider) and bool(dest_config.embedding_model)
    if not dest_has_embedder:
        return PUBLISH_MODE_COPY_NO_DEST_EMBEDDER, {'reason': 'no_destination_embedder_configured'}

    if dest_existing_metadata:
        prior_provider = dest_existing_metadata.get('embedder_provider')
        prior_model = dest_existing_metadata.get('embedder_model')
        if prior_provider and prior_model and (
            prior_provider != dest_config.embedder_provider or prior_model != dest_config.embedding_model
        ):
            return PUBLISH_MODE_RE_EMBED, {
                'reason': 'destination_embedder_changed',
                'prior_embedder': f'{prior_provider}/{prior_model}',
                'new_embedder': f'{dest_config.embedder_provider}/{dest_config.embedding_model}',
            }

    same_embedder = (
        source_config.embedder_provider == dest_config.embedder_provider
        and source_config.embedding_model == dest_config.embedding_model
    )
    if same_embedder:
        return PUBLISH_MODE_COPY, {'reason': 'same_embedder'}
    return PUBLISH_MODE_RE_EMBED, {
        'reason': 'different_embedder',
        'source_embedder': f'{source_config.embedder_provider}/{source_config.embedding_model}',
        'dest_embedder': f'{dest_config.embedder_provider}/{dest_config.embedding_model}',
    }


# Rough per-record cost estimate for RE-EMBED mode disclosure (Step 3 UI requirement -
# "disclose, don't ask"). Deliberately approximate and clearly labeled as such: entity
# names and edge facts vary widely in token length. Assumes ~6 tokens/entity name,
# ~20 tokens/edge fact (short factual sentences), OpenAI text-embedding-3-small pricing
# ($0.02 / 1M tokens as of this writing) as the reference rate - the DevDoc's cited
# "~$0.0004 per full publish at Public's current scale (1,026 embeddings)" figure is
# reproduced by this exact arithmetic: (399*6 + 627*20) tokens = 14,934 tokens * $0.02/1e6
# = $0.0003 (same order of magnitude - "roughly", per the DevDoc's own hedge).
EST_TOKENS_PER_ENTITY_NAME = 6
EST_TOKENS_PER_EDGE_FACT = 20
EST_USD_PER_MILLION_TOKENS = 0.02


def _estimate_reembed_cost_usd(entity_node_count: int, entity_edge_count: int) -> float:
    tokens = entity_node_count * EST_TOKENS_PER_ENTITY_NAME + entity_edge_count * EST_TOKENS_PER_EDGE_FACT
    return round(tokens * EST_USD_PER_MILLION_TOKENS / 1_000_000, 6)


def _build_real_dest_embedder(dest_config: BridgeConfig):
    """
    RE-EMBED mode only (Step 3). Constructs the destination's REAL, functioning embedder
    client from its already-configured provider/model, reusing sync.py's
    create_embedder_client() - the existing, single construction path this bridge already
    has for every embedder provider it supports - rather than duplicating that logic here
    (per the DevDoc's explicit instruction).

    Deliberately a LAZY, function-local import rather than a module-level one:
    graphiti_bridge/sync.py imports GeminiClient/AnthropicClient unconditionally at module
    scope (sync.py:11-12, no try/except), so importing sync.py AT ALL requires those
    optional LLM-provider packages to be installed, regardless of which embedder provider
    is actually configured. COPY mode (the default, unchanged path) and preflight() must
    never pay that cost or carry that import-time failure risk - only this function does,
    and only at the moment RE-EMBED mode is actually about to run.
    """
    from .sync import create_embedder_client
    return create_embedder_client(dest_config, debug=False)


# ---------------------------------------------------------------------------
# Destination-embedder LIVENESS check (Day79.01 subtask, 2026-08-10)
# ---------------------------------------------------------------------------
#
# REAL PRODUCTION INCIDENT THIS FIXES: preflight() previously validated CONFIGURATION
# (embedder identity/dimension agreement, schema presence, reachability of the Neo4j
# driver itself) but never validated CAPABILITY - whether the destination's configured
# embedder could actually be called. A destination whose embedder credential was never
# wired through at all (see the dbConfigToPublishSection() fix, GraphitiService.ts) still
# returned preflight ok:true, because nothing in preflight() ever tried to USE the
# embedder - only Neo4jDriver connectivity was probed. The user got a green light, waited
# through a real 399-record source read, and only THEN hit a real OpenRouter 401
# ("No cookie auth credentials found") from inside add_nodes_and_edges_bulk_tx()'s
# per-record re-embed gate. This function is the fix: embed one short test string with the
# resolved destination embedder client, at preflight time, before any real read/write
# happens.
async def _probe_dest_embedder_liveness(dest_config: BridgeConfig) -> Optional[Dict[str, str]]:
    """
    RE-EMBED mode only - never called from COPY / COPY_NO_DEST_EMBEDDER mode (see call
    site in preflight(), gated on `publish_mode == PUBLISH_MODE_RE_EMBED`). In those other
    two modes the destination's real embedder is never actually invoked (RaisingEmbedder
    guards the write path - hard requirement 2), so there is nothing real to probe and
    probing would just be an unconditional extra network call/cost on every preflight
    regardless of mode.

    Negligible cost by design: one embedding call on a single short string, using the
    SAME construction path (_build_real_dest_embedder(), reusing sync.py's
    create_embedder_client()) that publish() itself will use for the real run - so a
    passing probe here is a genuine guarantee the real run's embedder construction and
    first call will also succeed, not a separate code path that could itself drift out of
    sync with the real one.

    Returns None on success. Returns a structured refusal dict
    ({'code': ..., 'message': ...}) on ANY failure - auth error, network error, wrong/
    empty dimension - carrying the provider's ACTUAL error message (never a generic one),
    per the DevDoc's explicit requirement. Never raises - a probe failure is data for
    preflight() to add to its own `refusals` list, exactly like every other preflight
    check in this module.

    Two distinct refusal codes, chosen so a caller/UI can tell "your credential is wrong"
    (embedder_auth_failed) apart from "we couldn't reach/use the embedder for some other
    reason" (embedder_unreachable) - best-effort string match on the provider's own
    exception message/type, since different provider SDKs raise different exception
    shapes for a 401 (there is no single common exception base across OpenAI-compatible,
    Voyage, Gemini, and Azure clients that graphiti_core wraps).
    """
    try:
        embedder = _build_real_dest_embedder(dest_config)
    except Exception as e:
        return {
            'code': 'embedder_unreachable',
            'message': (
                f'Could not construct destination embedder client '
                f'({dest_config.embedder_provider}/{dest_config.embedding_model}): {e}'
            ),
        }

    try:
        vector = await embedder.create(['preflight embedder liveness probe'])
    except Exception as e:
        msg = str(e)
        is_auth_failure = '401' in msg or 'auth' in msg.lower() or 'api key' in msg.lower() or 'api_key' in msg.lower()
        code = 'embedder_auth_failed' if is_auth_failure else 'embedder_unreachable'
        return {
            'code': code,
            'message': (
                f'Destination embedder ({dest_config.embedder_provider}/'
                f'{dest_config.embedding_model}) liveness probe failed: {msg}'
            ),
        }

    if not vector:
        return {
            'code': 'embedder_unreachable',
            'message': (
                f'Destination embedder ({dest_config.embedder_provider}/'
                f'{dest_config.embedding_model}) liveness probe returned an empty vector.'
            ),
        }

    expected_dim = KNOWN_EMBEDDER_DIMS.get(dest_config.embedder_provider, {}).get(dest_config.embedding_model)
    if expected_dim is not None and len(vector) != expected_dim:
        return {
            'code': 'embedder_unreachable',
            'message': (
                f'Destination embedder ({dest_config.embedder_provider}/'
                f'{dest_config.embedding_model}) liveness probe returned a {len(vector)}D '
                f'vector, expected {expected_dim}D.'
            ),
        }

    return None


# ---------------------------------------------------------------------------
# Orphan sweep (hard requirements 6 + 7 - isolated, property-keyed, never label-keyed)
# ---------------------------------------------------------------------------

async def orphan_sweep_neo4j(
    dest_driver, dest_group_ids: List[str], kept_node_uuids: Set[str], kept_edge_uuids: Set[str],
    dry_run: bool,
) -> Dict[str, int]:
    """
    PURPOSE: delete destination nodes/edges whose group_id is in the published scope but
    whose uuid is not in the current scoped source set (i.e. deleted at source since the
    last publish). Isolated behind its own function - per DevDoc Architecture Notes,
    this is the piece most likely to need a FalkorDB-specific variant later (FalkorDB
    maps group_id to a separate graph per driver.clone(database=group_id), so its sweep
    will look structurally different); keeping it separate means a future FalkorDB
    variant is a new function, not a refactor of this one.

    Hard requirement 6: every predicate below matches on the `group_id` PROPERTY, never
    on labels. Some legacy nodes in production carry `Entity_<group_id>` suffixed labels
    from a September 2025 code path that no longer exists (DevDoc Rev 4 finding #2,
    measured 2026-08-09: 799 legacy nodes across three namespaces). A label-based sweep
    would behave inconsistently across namespaces and across node vintages within the
    same namespace; property-based scoping is the only predicate that is consistent.

    Edges are swept independently of nodes (not just via node DETACH DELETE cascade),
    because a source-side edge can be invalidated/removed between two entities that both
    still exist - the entities are unaffected but the specific edge instance is gone.
    Node sweep still runs afterward and DETACH DELETEs any remaining edges on removed
    nodes as a backstop.

    Returns counts actually deleted (or, when dry_run=True, counts that WOULD be
    deleted - dry run performs the read-side count query only and issues no DELETE).
    """
    swept = {
        'entity_nodes': 0, 'episodic_nodes': 0, 'saga_nodes': 0,
        'entity_edges': 0, 'episodic_edges': 0, 'has_episode_edges': 0, 'next_episode_edges': 0,
    }

    edge_specs = [
        ('entity_edges', 'RELATES_TO'),
        ('episodic_edges', 'MENTIONS'),
        ('has_episode_edges', 'HAS_EPISODE'),
        ('next_episode_edges', 'NEXT_EPISODE'),
    ]
    for field, rel_type in edge_specs:
        count_q = (
            f'MATCH ()-[r:{rel_type}]->() '
            f'WHERE r.group_id IN $group_ids AND NOT r.uuid IN $kept_uuids '
            f'RETURN count(r) AS c'
        )
        records, _, _ = await dest_driver.execute_query(
            count_q, group_ids=dest_group_ids, kept_uuids=list(kept_edge_uuids), routing_='r'
        )
        swept[field] = records[0]['c'] if records else 0
        if not dry_run and swept[field] > 0:
            await dest_driver.execute_query(
                f'MATCH ()-[r:{rel_type}]->() '
                f'WHERE r.group_id IN $group_ids AND NOT r.uuid IN $kept_uuids '
                f'DELETE r',
                group_ids=dest_group_ids, kept_uuids=list(kept_edge_uuids),
            )

    node_specs = [
        ('entity_nodes', 'Entity'),
        ('episodic_nodes', 'Episodic'),
        ('saga_nodes', 'Saga'),
    ]
    for field, label in node_specs:
        count_q = (
            f'MATCH (n:{label}) '
            f'WHERE n.group_id IN $group_ids AND NOT n.uuid IN $kept_uuids '
            f'RETURN count(n) AS c'
        )
        records, _, _ = await dest_driver.execute_query(
            count_q, group_ids=dest_group_ids, kept_uuids=list(kept_node_uuids), routing_='r'
        )
        swept[field] = records[0]['c'] if records else 0
        if not dry_run and swept[field] > 0:
            await dest_driver.execute_query(
                f'MATCH (n:{label}) '
                f'WHERE n.group_id IN $group_ids AND NOT n.uuid IN $kept_uuids '
                f'DETACH DELETE n',
                group_ids=dest_group_ids, kept_uuids=list(kept_node_uuids),
            )

    return swept


# ---------------------------------------------------------------------------
# PublishMetadata (hard requirement 10, redesigned per Ruling 3 - Day79.01 Phase A)
# ---------------------------------------------------------------------------
#
# RULING 3 REDESIGN RATIONALE: the original design was a single singleton node holding
# ONE `last_publish_at` and an accumulating `published_group_ids` union list. That is
# WRONG for any consumer checking per-group freshness: publish group A today, group B in
# three weeks, and the singleton reports `last_publish_at` = three weeks ago for BOTH
# groups - a confidently incorrect answer for group A.
#
# Fix: split into two node kinds.
#   1. METADATA_NODE_LABEL (singleton, id='singleton') - DESTINATION-WIDE fields only:
#      embedder_provider, embedder_model, embedding_dim. These genuinely must be uniform
#      across the whole destination (the mismatch-refusal logic in preflight() enforces
#      exactly that), so a singleton is the correct shape for them.
#   2. METADATA_GROUP_NODE_LABEL (one per group_id, keyed on group_id) - PER-GROUP fields:
#      last_publish_at, source_identifier, counts. A consumer asking "when was group_id=X
#      last published?" now gets X's actual record, not some other group's.
#
# Neo4j node properties cannot hold nested maps, so `counts` is stored as a JSON string
# (`counts_json`) and decoded back into a `counts` dict by read_publish_group_metadata().
#
# KNOWN/ACCEPTABLE BEHAVIOR (Part B3, Day79.01 Task 4.5 sign-off, documented not fixed):
# a PublishMetadataGroup record is written/refreshed only for group_ids present in the
# CURRENT publish() call's group_ids argument. If a group_id is published today and then
# dropped entirely from the source (no longer selected in any future publish() call), its
# PublishMetadataGroup record is never touched again - it lingers on the destination
# forever with a `last_publish_at` that grows increasingly stale, even though the
# corresponding data may have long since been orphan-swept off the destination by other
# runs (orphan_sweep_neo4j() only sweeps Entity/Episodic/Saga nodes and their edges - see
# that function's docstring - it never touches PublishMetadata/PublishMetadataGroup, so
# there is no mechanism that would ever clean this up). This is NOT a bug: a lingering
# stale timestamp for a group_id nobody is publishing anymore is harmless, and inventing
# a "prune metadata for groups no longer published" step would require tracking historical
# publish targets that this module deliberately does not track. A future reader should not
# mistake this for something to fix.

async def write_publish_metadata(
    dest_driver, embedder_provider: str, embedder_model: str, embedding_dim: Optional[int],
    source_identifier: str, group_ids: List[str],
    reconciliation: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Write/refresh destination-wide embedder-parity fields on the singleton PublishMetadata
    node, then write/refresh a PER-GROUP PublishMetadataGroup record for every group_id in
    this run. Consumers (eventually Ask Bjorn) read the singleton to self-check embedder
    parity before querying, per DevDoc "Embedder parity is a correctness boundary" /
    handoff contract to ENDOGON-PMA; a consumer checking per-group freshness reads the
    per-group record instead of the singleton.

    Per-group `counts` are queried fresh from the destination (post-write, post-sweep) for
    that specific group_id rather than reused from the in-memory upsert/sweep totals -
    correct even when multiple group_ids are published in one call, since the upsert/sweep
    totals in that case are aggregated across all of them, not split per group_id.

    Task 2.1: `reconciliation`, when provided, is the (aggregate, across every group_id in
    this run - same reasoning as upserted/swept above) post-write reconciliation result
    computed by reconcile_destination(), embedded verbatim into every group's counts_json
    under a `reconciliation` key. This is the audit-trail requirement: a reader of
    PublishMetadataGroup must be able to see THAT reconciliation ran and passed, not just
    infer it from the absence of an exception. write_publish_metadata() is only ever
    called after publish() has confirmed reconciliation['ok'] is True (a failed
    reconciliation raises ReconciliationFailed before this function is reached), so every
    persisted record here reflects a CONFIRMED-matching destination state.
    """
    now = datetime.now(timezone.utc).isoformat()

    await dest_driver.execute_query(
        f"""
        MERGE (m:{METADATA_NODE_LABEL} {{id: $id}})
        SET m.embedder_provider = $embedder_provider,
            m.embedder_model = $embedder_model,
            m.embedding_dim = $embedding_dim
        """,
        id=METADATA_SINGLETON_ID,
        embedder_provider=embedder_provider,
        embedder_model=embedder_model,
        embedding_dim=embedding_dim,
    )

    for group_id in group_ids:
        counts = await _dest_group_counts(dest_driver, group_id)
        if reconciliation is not None:
            counts = {**counts, 'reconciliation': reconciliation}
        await dest_driver.execute_query(
            f"""
            MERGE (g:{METADATA_GROUP_NODE_LABEL} {{group_id: $group_id}})
            SET g.last_publish_at = $now,
                g.source_identifier = $source_identifier,
                g.counts_json = $counts_json
            """,
            group_id=group_id,
            now=now,
            source_identifier=source_identifier,
            counts_json=json.dumps(counts, separators=(',', ':')),
        )


async def _dest_group_counts(dest_driver, group_id: str) -> Dict[str, int]:
    """Fresh post-write record counts for one group_id, for that group_id's metadata record."""
    return {
        'entity_nodes': await _count_in_scope(dest_driver, 'Entity', [group_id]),
        'episodic_nodes': await _count_in_scope(dest_driver, 'Episodic', [group_id]),
        'saga_nodes': await _count_in_scope(dest_driver, 'Saga', [group_id]),
        'entity_edges': await _count_edges_in_scope(dest_driver, 'RELATES_TO', [group_id]),
        'episodic_edges': await _count_edges_in_scope(dest_driver, 'MENTIONS', [group_id]),
        'has_episode_edges': await _count_edges_in_scope(dest_driver, 'HAS_EPISODE', [group_id]),
        'next_episode_edges': await _count_edges_in_scope(dest_driver, 'NEXT_EPISODE', [group_id]),
    }


async def read_publish_metadata(dest_driver) -> Optional[Dict[str, Any]]:
    """Destination-wide fields only (embedder_provider, embedder_model, embedding_dim).
    Per-group freshness/counts are NOT here - use read_publish_group_metadata()."""
    records, _, _ = await dest_driver.execute_query(
        f'MATCH (m:{METADATA_NODE_LABEL} {{id: $id}}) RETURN m AS m',
        id=METADATA_SINGLETON_ID, routing_='r',
    )
    if not records:
        return None
    node = records[0]['m']
    return dict(node)


async def read_publish_group_metadata(dest_driver, group_id: str) -> Optional[Dict[str, Any]]:
    """Per-group_id publish record: {group_id, last_publish_at, source_identifier, counts}.
    Returns None if this group_id has never been published to this destination."""
    records, _, _ = await dest_driver.execute_query(
        f'MATCH (g:{METADATA_GROUP_NODE_LABEL} {{group_id: $group_id}}) RETURN g AS g',
        group_id=group_id, routing_='r',
    )
    if not records:
        return None
    node = dict(records[0]['g'])
    counts_json = node.pop('counts_json', None)
    node['counts'] = json.loads(counts_json) if counts_json else None
    return node


# ---------------------------------------------------------------------------
# preflight (hard requirement 11 - structured refusal, not boolean)
# ---------------------------------------------------------------------------

class PublishRefused(Exception):
    """Raised by publish() when preflight() returns blocking refusal reasons."""

    def __init__(self, reasons: List[Dict[str, str]]):
        self.reasons = reasons
        super().__init__('; '.join(r['message'] for r in reasons))


class ReconciliationFailed(Exception):
    """
    Task 2.1: raised by publish() when reconcile_destination() finds that the
    destination's post-write, post-sweep record counts (scoped to the published
    group_ids) do NOT match the counts of the source-side scoped set publish() intended
    to land. This is the "no fallback paths" requirement made concrete - a mismatch here
    can NEVER be logged as a warning and allowed to pass; publish() must raise instead of
    returning success, even though every individual write call up to this point completed
    without error (that is exactly the failure class this whole mechanism exists to catch
    - see Task 4.5's real-data dress rehearsal finding: publish() reported upserted=627
    while only 423 RELATES_TO edges actually existed on the destination).
    """

    def __init__(self, mismatches: List[Dict[str, Any]], reconciliation: Dict[str, Any]):
        self.mismatches = mismatches
        self.reconciliation = reconciliation
        detail = '; '.join(
            f"{m['type']}: expected={m['expected']} actual={m['actual']}" for m in mismatches
        )
        super().__init__(
            f'Post-write reconciliation FAILED - destination does not match the intended '
            f'source state after publish. Mismatches: {detail}'
        )


async def preflight(
    source_config: BridgeConfig, dest_config: BridgeConfig, group_ids: List[str],
) -> Dict[str, Any]:
    """
    Structured preflight result: {"ok": bool, "refusals": [...], "warnings": [...], ...}.
    Never just True/False (hard requirement 11). publish() calls this first and refuses
    to run (raises PublishRefused) on any blocking refusal - including on a dry run,
    since dry runs still exist to catch these correctness problems before a real run.
    """
    refusals: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    same_source_dest = (
        source_config.database_url == dest_config.database_url
        and (source_config.database_name or 'neo4j') == (dest_config.database_name or 'neo4j')
    )
    if same_source_dest:
        refusals.append({
            'code': 'same_source_destination',
            'message': 'Source and destination resolve to the same database - refusing to publish.',
        })
        # Nothing else is safe to check against an identical target; return early.
        return {'ok': False, 'refusals': refusals, 'warnings': warnings, 'estimate': {}}

    source_graphiti: Optional[Graphiti] = None
    dest_graphiti: Optional[Graphiti] = None
    estimate: Dict[str, int] = {}
    source_dims: Optional[int] = None
    dest_metadata: Optional[Dict[str, Any]] = None

    try:
        source_graphiti = await _build_graphiti(source_config)
    except Exception as e:
        refusals.append({'code': 'source_unreachable', 'message': f'Could not connect to source: {e}'})

    try:
        dest_graphiti = await _build_graphiti(dest_config)
    except Exception as e:
        refusals.append({'code': 'destination_unreachable', 'message': f'Could not connect to destination: {e}'})

    if dest_graphiti is not None:
        try:
            records, _, _ = await dest_graphiti.driver.execute_query('SHOW INDEXES', routing_='r')
            if len(records) == 0:
                refusals.append({
                    'code': 'destination_schema_missing',
                    'message': 'Destination has zero indexes even after build_indices_and_constraints() - schema initialization failed.',
                })
        except Exception as e:
            refusals.append({'code': 'destination_schema_missing', 'message': f'Could not verify destination schema: {e}'})

    if source_graphiti is not None:
        try:
            community_count = await count_communities_in_scope(source_graphiti.driver, group_ids)
            if community_count > 0:
                warnings.append({
                    'code': 'communities_present_not_published',
                    'message': f'{community_count} CommunityNode(s) exist in the scoped source group_ids and will NOT be published (communities are excluded by design).',
                })
        except Exception as e:
            warnings.append({'code': 'community_check_failed', 'message': f'Could not check for communities: {e}'})

        try:
            records, _, _ = await source_graphiti.driver.execute_query(
                'MATCH (n:Entity) WHERE n.group_id IN $group_ids AND n.name_embedding IS NOT NULL '
                'RETURN size(n.name_embedding) AS dims LIMIT 1',
                group_ids=group_ids, routing_='r',
            )
            if records:
                source_dims = records[0]['dims']
        except Exception as e:
            warnings.append({'code': 'dimension_probe_failed', 'message': f'Could not sample source embedding dimension: {e}'})

        # Step 2 (Day79.01 subtask, 2026-08-10): non-blocking WARNING when the source's
        # MEASURED vectors (source_dims, just queried above - this is the "costs one query"
        # the DevDoc refers to, since it is the same query, not an additional one) disagree
        # with what the source's OWN CONFIGURED embedder implies. This is exactly the check
        # that would have caught the test-vault incident at preflight time: config said
        # openrouter/text-embedding-3-small (implies 1536D per KNOWN_EMBEDDER_DIMS below),
        # but the source's actual stored vectors measured 768D (leftover nomic data from
        # prior testing in the same shared neo4j-dev container). Distinct from, and
        # independent of, the embedder_dimension_mismatch/embedder_model_mismatch HARD
        # REFUSALS further below - those compare source-vs-DESTINATION's prior metadata;
        # this compares source-vs-ITS OWN config, and never blocks anything by itself.
        if source_dims is not None:
            expected_source_dims = _expected_source_embedder_dim(source_config)
            if expected_source_dims is not None and expected_source_dims != source_dims:
                warnings.append({
                    'code': 'source_measured_dim_disagrees_with_configured_embedder',
                    'message': (
                        f'Source is configured for {source_config.embedder_provider}/'
                        f'{source_config.embedding_model} (expected {expected_source_dims}D), '
                        f'but the source\'s actual stored vectors measured {source_dims}D. '
                        f'The configured embedder is only an identity HINT, never authoritative - '
                        f'treat the measured value as ground truth. This usually means the '
                        f'source database\'s embedder configuration was changed after its '
                        f'existing vectors were written (e.g. a shared/reused dev database), '
                        f'and its vectors were never re-embedded to match.'
                    ),
                })

        try:
            estimate = {
                'entity_nodes': (await _count_in_scope(source_graphiti.driver, 'Entity', group_ids)),
                'episodic_nodes': (await _count_in_scope(source_graphiti.driver, 'Episodic', group_ids)),
                'saga_nodes': (await _count_in_scope(source_graphiti.driver, 'Saga', group_ids)),
                'entity_edges': (await _count_edges_in_scope(source_graphiti.driver, 'RELATES_TO', group_ids)),
                'episodic_edges': (await _count_edges_in_scope(source_graphiti.driver, 'MENTIONS', group_ids)),
                'has_episode_edges': (await _count_edges_in_scope(source_graphiti.driver, 'HAS_EPISODE', group_ids)),
                'next_episode_edges': (await _count_edges_in_scope(source_graphiti.driver, 'NEXT_EPISODE', group_ids)),
            }
        except Exception as e:
            warnings.append({'code': 'estimate_failed', 'message': f'Could not compute record estimate: {e}'})

    if dest_graphiti is not None:
        try:
            dest_metadata = await read_publish_metadata(dest_graphiti.driver)
        except Exception as e:
            warnings.append({'code': 'metadata_read_failed', 'message': f'Could not read existing destination metadata: {e}'})

    # Step 3/4 (Day79.01 subtask, 2026-08-10): derive the publish mode BEFORE the
    # embedder/dimension mismatch refusal checks below - this ordering is load-bearing,
    # not cosmetic. Those refusals predate this subtask and were written for a world where
    # ANY disagreement between dest_metadata (what a PRIOR publish wrote) and the CURRENT
    # config was unconditionally unsafe. That is no longer true: RE-EMBED mode exists
    # SPECIFICALLY to handle a destination embedder change safely (Step 4) - a disagreement
    # in this exact shape is what RE-EMBED mode is FOR, not an error condition. Deriving the
    # mode first lets the refusal checks below distinguish "this mismatch will be
    # copied-through incompatibly" (still refuse) from "this mismatch is why we're about to
    # RE-EMBED everything" (must NOT refuse, or the corrected design could never actually
    # run - this exact bug was caught by test_destination_embedder_change_forces_full_reembed).
    publish_mode, mode_info = resolve_publish_mode(source_config, dest_config, dest_metadata)

    # Destination-embedder LIVENESS check (Day79.01 subtask, 2026-08-10 - real production
    # incident fix). ONLY when RE-EMBED mode is resolved: COPY / COPY_NO_DEST_EMBEDDER mode
    # never actually calls a real destination embedder (RaisingEmbedder guards that path -
    # see hard requirement 2), so there is nothing real to probe and probing would just be
    # an unnecessary network call and cost on every single preflight. RE-EMBED mode is the
    # ONLY mode where publish() will hand a REAL embedder client to add_nodes_and_edges_bulk()
    # and expect it to succeed against a live provider - so this is exactly the mode where a
    # broken/unauthenticated/unreachable embedder must be caught HERE, before a real source
    # read and a real destination write are attempted, not discovered mid-publish.
    #
    # Real incident this fixes: preflight previously returned ok:true on a destination
    # config whose embedder credential was never wired through at all (see
    # dbConfigToPublishSection() fix, GraphitiService.ts) - the user got a green light,
    # waited through a real 399-record source read, and only THEN hit
    # "Error code: 401 - {'error': {'message': 'No cookie auth credentials found'}}" from
    # OpenRouter. This check converts that into an immediate, specific preflight refusal.
    if publish_mode == PUBLISH_MODE_RE_EMBED:
        liveness_refusal = await _probe_dest_embedder_liveness(dest_config)
        if liveness_refusal is not None:
            refusals.append(liveness_refusal)

    # Hard requirement 11: embedder/dimension mismatch is a correctness boundary - refuse,
    # don't warn - BUT ONLY WHEN THE MODE IS COPY-LIKE (COPY / COPY_NO_DEST_EMBEDDER). In
    # RE_EMBED mode, a disagreement between dest_metadata and the current config is the
    # EXPECTED, safely-handled case (see comment above) and must never block the publish.
    if publish_mode != PUBLISH_MODE_RE_EMBED and dest_metadata is not None and source_dims is not None:
        existing_dim = dest_metadata.get('embedding_dim')
        if existing_dim is not None and existing_dim != source_dims:
            refusals.append({
                'code': 'embedder_dimension_mismatch',
                'message': (
                    f'Destination PublishMetadata records embedding_dim={existing_dim} from a prior '
                    f'publish, but the source graph\'s current embeddings are {source_dims}D. '
                    f'Refusing - this would mix vectors from two different embedder models on the '
                    f'same destination.'
                ),
            })
        existing_model = dest_metadata.get('embedder_model')
        if existing_model and existing_model != dest_config.embedding_model:
            refusals.append({
                'code': 'embedder_model_mismatch',
                'message': (
                    f'Destination PublishMetadata records embedder_model="{existing_model}" from a '
                    f'prior publish, but this run declares embedder_model="{dest_config.embedding_model}". '
                    f'Refusing.'
                ),
            })

    await _close_graphiti(source_graphiti)
    await _close_graphiti(dest_graphiti)

    # UI DISCLOSURE payload (never a selector - see resolve_publish_mode() docstring).
    # PublishModal.svelte renders these fields the same way it already renders the
    # group_id-count safety affordance: something the user MUST see before pressing
    # Publish, never something they choose.
    source_embedder_label = f'{source_config.embedder_provider}/{source_config.embedding_model}'
    dest_embedder_label = f'{dest_config.embedder_provider}/{dest_config.embedding_model}' if (
        dest_config.embedder_provider and dest_config.embedding_model
    ) else None
    reembed_record_estimate = 0
    reembed_cost_estimate_usd = 0.0
    if publish_mode == PUBLISH_MODE_RE_EMBED and estimate:
        reembed_record_estimate = estimate.get('entity_nodes', 0) + estimate.get('entity_edges', 0)
        reembed_cost_estimate_usd = _estimate_reembed_cost_usd(
            estimate.get('entity_nodes', 0), estimate.get('entity_edges', 0)
        )
        # Step 4 disclosure: when the mode was forced by a destination embedder CHANGE
        # (not merely source/destination disagreeing), say so explicitly and distinctly -
        # this is the "warn about this in preflight so a full-scope re-embed is never a
        # surprise" requirement. Non-blocking (a warning, never a refusal) - the whole
        # point of RE-EMBED mode is that it is the CORRECT, safe response to this
        # situation, not an error condition.
        if mode_info.get('reason') == 'destination_embedder_changed':
            warnings.append({
                'code': 'destination_embedder_changed_forces_full_reembed',
                'message': (
                    f'Destination\'s configured embedder changed since the last publish '
                    f'(was {mode_info.get("prior_embedder")}, now {mode_info.get("new_embedder")}). '
                    f'Forcing a FULL re-embed of the entire scoped set ({reembed_record_estimate} '
                    f'entity nodes + edges, ~${reembed_cost_estimate_usd:.6f} estimated) so the '
                    f'destination never holds two incompatible vector spaces at once.'
                ),
            })
        elif mode_info.get('reason') == 'different_embedder':
            warnings.append({
                'code': 'source_dest_embedder_differ_will_reembed',
                'message': (
                    f'Source ({source_embedder_label}) and destination ({dest_embedder_label}) '
                    f'embedders differ - {reembed_record_estimate} record(s) will be RE-EMBEDDED '
                    f'with the destination\'s embedder (~${reembed_cost_estimate_usd:.6f} estimated), '
                    f'not copied through, so stored vectors stay query-compatible with the '
                    f'destination\'s configured embedder.'
                ),
            })

    return {
        'ok': len(refusals) == 0,
        'refusals': refusals,
        'warnings': warnings,
        'estimate': estimate,
        'source_embedding_dim': source_dims,
        'dest_existing_metadata': dest_metadata,
        # UI disclosure payload (Step 3/4) - informational only, never settable.
        'publish_mode': publish_mode,
        'mode_reason': mode_info.get('reason'),
        'source_embedder_label': source_embedder_label,
        'dest_embedder_label': dest_embedder_label,
        'reembed_record_estimate': reembed_record_estimate,
        'reembed_cost_estimate_usd': reembed_cost_estimate_usd,
    }


async def _count_in_scope(driver, label: str, group_ids: List[str]) -> int:
    records, _, _ = await driver.execute_query(
        f'MATCH (n:{label}) WHERE n.group_id IN $group_ids RETURN count(n) AS c',
        group_ids=group_ids, routing_='r',
    )
    return records[0]['c'] if records else 0


async def _count_edges_in_scope(driver, rel_type: str, group_ids: List[str]) -> int:
    records, _, _ = await driver.execute_query(
        f'MATCH ()-[r:{rel_type}]->() WHERE r.group_id IN $group_ids RETURN count(r) AS c',
        group_ids=group_ids, routing_='r',
    )
    return records[0]['c'] if records else 0


# ---------------------------------------------------------------------------
# Post-write reconciliation (Day79.01 Task 2.1)
# ---------------------------------------------------------------------------
#
# PURPOSE: Task 4.5's real-data dress rehearsal against production Bjorn -> neo4j-dev
# found that publish() counted what it SENT (upserted=627 RELATES_TO), not what
# actually ARRIVED (423 landed) - a silent-data-loss bug in the chunking loop (see
# ReconciliationFailed docstring). Every prior canary test passed throughout the
# incident because none of them exercise real volume with real cross-chunk references.
#
# This is deliberately a genuine post-hoc verification of DESTINATION STATE vs INTENT,
# not a check that only re-validates the two-pass ordering fix above. It counts records
# BY TYPE on the destination, scoped to the group_ids just published, and compares
# against the size of the source-side scoped set publish() intended to land (the exact
# counts already computed by fetch_scoped_records() via `scoped`). Any mismatch, in
# either direction, for ANY type, is a hard failure - this is what turns the entire
# class of silent-loss bugs into hard errors, including ones not yet discovered, per
# the "no fallback paths" project rule.
#
# Precondition: must run AFTER every write pass (nodes, edges, saga/has_episode/
# next_episode) AND the orphan sweep have both completed - reconciling before the sweep
# would spuriously flag legitimate soon-to-be-swept orphans as "extra" records.

RECONCILIATION_CHECKS: List[Tuple[str, str, bool]] = [
    # (scoped-dict key, Neo4j label or relationship type, is_edge)
    ('entity_nodes', 'Entity', False),
    ('episodic_nodes', 'Episodic', False),
    ('saga_nodes', 'Saga', False),
    ('entity_edges', 'RELATES_TO', True),
    ('episodic_edges', 'MENTIONS', True),
    ('has_episode_edges', 'HAS_EPISODE', True),
    ('next_episode_edges', 'NEXT_EPISODE', True),
]


# Step 5 (Day79.01 subtask, 2026-08-10): non-null EMBEDDING count checks, distinct from
# the record-COUNT checks in RECONCILIATION_CHECKS above. Only entity_nodes/entity_edges
# carry an embedding field at all (name_embedding/fact_embedding respectively) - episodic
# nodes/edges and sagas have none, so there is nothing to check for them here. Expected is
# ALWAYS the full scoped count for that type, in BOTH publish modes: COPY mode asserts
# non-None BEFORE the write even happens (fetch_scoped_records()'s existing hard
# requirement 1), so every record that reaches the destination already has one; RE-EMBED
# mode generates a fresh one for every entity node/edge unconditionally (never
# incremental/changed-only - see resolve_publish_mode() docstring), so the expected count
# is likewise the full scoped set. A mismatch here means a partial embedder failure (e.g.
# some destination-embedder batch calls failed or were rate-limited) that COUNT-only
# reconciliation would have missed entirely - the record landed, just without a vector.
EMBEDDING_RECONCILIATION_CHECKS: List[Tuple[str, str, str, bool]] = [
    # (scoped-dict key, Neo4j label or relationship type, embedding property, is_edge)
    ('entity_nodes', 'Entity', 'name_embedding', False),
    ('entity_edges', 'RELATES_TO', 'fact_embedding', True),
]


async def _count_non_null_prop_in_scope(driver, label: str, prop: str, group_ids: List[str]) -> int:
    records, _, _ = await driver.execute_query(
        f'MATCH (n:{label}) WHERE n.group_id IN $group_ids AND n.{prop} IS NOT NULL RETURN count(n) AS c',
        group_ids=group_ids, routing_='r',
    )
    return records[0]['c'] if records else 0


async def _count_non_null_prop_edges_in_scope(driver, rel_type: str, prop: str, group_ids: List[str]) -> int:
    records, _, _ = await driver.execute_query(
        f'MATCH ()-[r:{rel_type}]->() WHERE r.group_id IN $group_ids AND r.{prop} IS NOT NULL RETURN count(r) AS c',
        group_ids=group_ids, routing_='r',
    )
    return records[0]['c'] if records else 0


async def reconcile_destination(
    dest_driver, dest_group_ids: List[str], scoped: Dict[str, list],
) -> Dict[str, Any]:
    """
    Compare destination record counts (scoped to dest_group_ids, post-write, post-sweep)
    against the source-side scoped set's counts, per record type. Returns a structured
    result - never a bare bool - mirroring preflight()'s "structured refusal" convention:

        {
          'ok': bool,
          'per_type': {type: {'expected': int, 'actual': int, 'match': bool}, ...},
          'mismatches': [{'type': str, 'expected': int, 'actual': int}, ...],
        }

    Step 5 (2026-08-10) extends `per_type`/`mismatches` with two additional keys -
    'entity_nodes_embeddings' and 'entity_edges_embeddings' - asserting that the expected
    number of records ALSO have a non-null embedding, not merely that the record count
    matches. See EMBEDDING_RECONCILIATION_CHECKS above for the full rationale.

    Callers (publish()) MUST treat 'ok' is False as a hard failure (raise
    ReconciliationFailed) - there is no acceptable "log and continue" path here.
    """
    per_type: Dict[str, Dict[str, Any]] = {}
    mismatches: List[Dict[str, Any]] = []

    for key, label_or_rel, is_edge in RECONCILIATION_CHECKS:
        expected = len(scoped[key])
        actual = (
            await _count_edges_in_scope(dest_driver, label_or_rel, dest_group_ids)
            if is_edge
            else await _count_in_scope(dest_driver, label_or_rel, dest_group_ids)
        )
        match = expected == actual
        per_type[key] = {'expected': expected, 'actual': actual, 'match': match}
        if not match:
            mismatches.append({'type': key, 'expected': expected, 'actual': actual})

    for scoped_key, label_or_rel, prop, is_edge in EMBEDDING_RECONCILIATION_CHECKS:
        check_key = f'{scoped_key}_embeddings'
        expected = len(scoped[scoped_key])
        actual = (
            await _count_non_null_prop_edges_in_scope(dest_driver, label_or_rel, prop, dest_group_ids)
            if is_edge
            else await _count_non_null_prop_in_scope(dest_driver, label_or_rel, prop, dest_group_ids)
        )
        match = expected == actual
        per_type[check_key] = {'expected': expected, 'actual': actual, 'match': match}
        if not match:
            mismatches.append({'type': check_key, 'expected': expected, 'actual': actual})

    return {'ok': len(mismatches) == 0, 'per_type': per_type, 'mismatches': mismatches}


# ---------------------------------------------------------------------------
# publish (hard requirements 3, 4, 9, 12, 13, 14)
# ---------------------------------------------------------------------------

async def publish(
    source_config: BridgeConfig,
    dest_config: BridgeConfig,
    group_ids: List[str],
    dry_run: bool = False,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Upsert-plus-orphan-sweep replication of `group_ids` from source to destination.

    IDEMPOTENCY NOTE (hard requirement 12, documented per the DevDoc's own instruction to
    "be explicit and prepared to justify the choice"): every write in this module is a
    Cypher MERGE-by-uuid (verified against ../graphiti/graphiti_core/models/{nodes,edges}/
    *_db_queries.py - every save/save_bulk query is `MERGE (n {uuid: ...}) SET ...`, never
    CREATE). A second run with no source changes therefore still *issues* the same
    MERGE/SET operations, but produces zero NET CHANGE to the destination graph state -
    no new nodes or edges, no property deltas, and orphan_sweep_neo4j() deletes zero
    records because kept_uuids is unchanged. That is the sense in which this module is a
    "no-op": zero net graph mutation, not zero Cypher statements executed (the DevDoc's
    own chosen algorithm - "Upsert by uuid plus orphan sweep, not full overwrite, not
    naive diff" - deliberately does not track changes, so re-issuing identical upserts is
    the whole point of the design).

    The ONE deliberate exception is each group_id's PublishMetadataGroup record's
    `last_publish_at` field (see Ruling 3 redesign), which is refreshed on every
    successful non-dry-run publish regardless of whether any other data changed for that
    group_id - its entire purpose is "when did we last confirm this destination reflects
    the source for THIS group_id", which is itself new information on every run.

    DRY RUN GUARANTEE (Ruling 6 - measured, not assumed, 2026-08-09 against a
    schema-fresh destination stripped of every index/constraint via
    tests/manual/day79_01_ruling6_dry_run_schema_measurement.py):

        dry_run=True writes NO node/edge/metadata DATA - confirmed zero change to
        Entity/Episodic/PublishMetadata(Group) counts before vs. after. It DOES,
        however, create the destination's 30 Graphiti indices (0 constraints observed)
        as a side effect, because _build_graphiti() unconditionally calls
        graphiti.build_indices_and_constraints() for BOTH source and destination during
        Graphiti-instance construction, and that construction happens before this
        function's `if dry_run:` branch is ever reached - preflight() alone (called
        first, always) already triggers it for both sides. This is true even against a
        destination that has NEVER had build_indices_and_constraints() run before.
        Practical consequence: dry_run=True is not schema-neutral. It is data-neutral.
        A caller that wants to probe a destination without creating ANY schema must not
        call preflight() or publish() at all against it.

    DRY RUN IS EMBEDDER-FREE ON THE WRITE PATH (verified by direct code trace, Day79.01
    subtask 2026-08-10, following the real production 401 incident - see DevDoc Rev 6):

        Confirmed by reading this function directly: the `if dry_run:` branch (above the
        `else:` branch containing the real write passes) only calls orphan_sweep_neo4j(
        ..., dry_run=True) - a read-only COUNT query - and returns. `write_embedder`
        (the REAL destination embedder in RE-EMBED mode) is constructed and invoked ONLY
        inside the `else:` (non-dry-run) branch, via add_nodes_and_edges_bulk()'s
        per-record `if x.name_embedding is None: generate...` gate. dry_run=True never
        reaches that branch, so it makes ZERO calls to the real write-path embedder,
        exactly as originally documented - this part of the guarantee is unchanged.

        ONE NEW, NARROW EXCEPTION as of the destination-embedder liveness check added in
        this same subtask (see preflight()'s `_probe_dest_embedder_liveness()` call,
        gated on `publish_mode == PUBLISH_MODE_RE_EMBED`): preflight() itself is called
        UNCONDITIONALLY by this function, before the `dry_run` branch is even reached -
        it always ran before dry_run existed as a concept, and always will, since
        preflight is what dry_run and real runs both rely on for "refuse rather than
        half-do". As of this subtask, in RE-EMBED mode ONLY, preflight() now makes
        exactly ONE real embedder API call (a single short test string) to confirm the
        destination embedder is actually usable BEFORE either a dry run or a real run
        proceeds. This is intentional and is the entire point of the liveness check: the
        incident this fixes was discovered specifically because dry runs and preflight
        alike gave a false green light on a destination embedder that could not
        authenticate. A caller that requires an absolutely zero-embedder-call dry run in
        RE-EMBED mode must not call preflight() or publish() at all in that mode; COPY /
        COPY_NO_DEST_EMBEDDER mode is unaffected - the liveness check never runs for
        them, so dry_run remains fully embedder-free in both.
    """
    start_time = time.time()

    def _emit(event: str, **fields):
        payload = {'type': 'progress', 'event': event, **fields}
        if progress_cb:
            progress_cb(payload)
        print_json_response(payload)

    _emit('preflight_start', group_ids=group_ids)
    preflight_result = await preflight(source_config, dest_config, group_ids)
    _emit('preflight_done', ok=preflight_result['ok'], refusals=preflight_result['refusals'],
          warnings=preflight_result['warnings'])
    if not preflight_result['ok']:
        raise PublishRefused(preflight_result['refusals'])

    # Step 3/4 (Day79.01 subtask, 2026-08-10): derive the publish mode from the SAME facts
    # preflight() just used (reuses preflight_result['dest_existing_metadata'] - no second
    # query). Never re-derived differently here than what preflight() disclosed to the
    # caller - would defeat the entire "disclose, don't ask" requirement if publish()
    # could silently pick a different mode than what preflight() showed the user.
    publish_mode, mode_info = resolve_publish_mode(
        source_config, dest_config, preflight_result.get('dest_existing_metadata')
    )
    _emit('mode_resolved', mode=publish_mode, **mode_info)

    source_graphiti = await _build_graphiti(source_config)
    dest_graphiti = await _build_graphiti(dest_config)

    try:
        _emit('read_start', group_ids=group_ids, mode=publish_mode)
        scoped = await fetch_scoped_records(source_graphiti, group_ids, mode=publish_mode)
        _emit(
            'read_done',
            entity_nodes=len(scoped['entity_nodes']),
            episodic_nodes=len(scoped['episodic_nodes']),
            saga_nodes=len(scoped['saga_nodes']),
            entity_edges=len(scoped['entity_edges']),
            episodic_edges=len(scoped['episodic_edges']),
            has_episode_edges=len(scoped['has_episode_edges']),
            next_episode_edges=len(scoped['next_episode_edges']),
        )

        kept_node_uuids: Set[str] = {n.uuid for n in scoped['entity_nodes']} \
            | {n.uuid for n in scoped['episodic_nodes']} \
            | {n.uuid for n in scoped['saga_nodes']}
        kept_edge_uuids: Set[str] = {e.uuid for e in scoped['entity_edges']} \
            | {e.uuid for e in scoped['episodic_edges']} \
            | {e.uuid for e in scoped['has_episode_edges']} \
            | {e.uuid for e in scoped['next_episode_edges']}

        dest_group_ids = [resolve_dest_group_id(g) for g in group_ids]

        upserted = {
            'entity_nodes': 0, 'episodic_nodes': 0, 'saga_nodes': 0,
            'entity_edges': 0, 'episodic_edges': 0, 'has_episode_edges': 0, 'next_episode_edges': 0,
        }

        if dry_run:
            # Hard requirement 13: dry run reports accurate counts and writes nothing at all.
            for key in upserted:
                upserted[key] = len(scoped[key])
            swept = await orphan_sweep_neo4j(
                dest_graphiti.driver, dest_group_ids, kept_node_uuids, kept_edge_uuids, dry_run=True
            )
            _emit('dry_run_summary', upserted=upserted, swept=swept)
        else:
            entity_nodes = scoped['entity_nodes']
            episodic_nodes = scoped['episodic_nodes']
            entity_edges = scoped['entity_edges']
            episodic_edges = scoped['episodic_edges']

            # Step 3 (Day79.01 subtask, 2026-08-10): COPY mode (default, UNCHANGED) keeps
            # the RaisingEmbedder guard exactly as before - entity_nodes/entity_edges
            # already carry non-None embeddings (fetch_scoped_records() asserted this),
            # so any call to this embedder is by definition a bug, and RaisingEmbedder
            # turns it into a stack trace per the existing hard requirement 2. RE-EMBED
            # mode passes the REAL destination embedder instead - entity_nodes/entity_edges
            # deliberately carry None embeddings (fetch_scoped_records() skipped loading
            # them), so add_nodes_and_edges_bulk_tx()'s per-record gate WILL call this
            # embedder, intentionally, to regenerate a vector from node.name/edge.fact.
            # Episodic nodes/edges are unaffected either way - they have no embedding field
            # and bulk_utils.py never attempts to embed them regardless of which embedder
            # object is passed here.
            write_embedder = (
                _build_real_dest_embedder(dest_config)
                if publish_mode == PUBLISH_MODE_RE_EMBED
                else RaisingEmbedder()
            )

            # @purpose: measure RE-EMBED mode's real embedding+write cost, distinct from
            # saga_pass/sweep timing (existing) and from COPY mode (where this is skipped
            # entirely - COPY mode never calls a real embedder, so there is nothing extra
            # to measure beyond the plain write time already implicit in nodes_pass_done/
            # edges_pass_done's own timestamps). @depends: same _emit()/time.time()
            # convention as saga_pass_start/saga_pass_done. @results: a distinct
            # 'reembed_start'/'reembed_done' progress event pair wrapping the nodes-pass +
            # edges-pass write loops below (the only two passes where entity_nodes/
            # entity_edges - the only record types with an embedding field - actually get
            # embedded, via add_nodes_and_edges_bulk_tx()'s per-record `if x.name_embedding
            # is None: generate...` gate). KNOWN LIMITATION, documented rather than
            # papered over: this duration necessarily COMBINES real embedder API call time
            # AND Cypher write time - graphiti_core's add_nodes_and_edges_bulk() performs
            # both inside one call with no hook point to separate them, and this project
            # must never modify graphiti_core (project rule). A finer embedding-only/
            # write-only split is not obtainable without violating that rule; this event
            # gives the best honest decomposition available: "RE-EMBED mode's entity-bearing
            # write phase" as one measured number, distinct from the saga path and the
            # sweep, both already separately timed.
            reembed_start_time = time.time()
            if publish_mode == PUBLISH_MODE_RE_EMBED:
                _emit(
                    'reembed_start',
                    entity_nodes=len(entity_nodes), entity_edges=len(entity_edges),
                )

            # TASK 2.1 FIX - two-pass write, replacing the old single-pass loop that
            # sliced entity_nodes/entity_edges (and episodic_nodes/episodic_edges) by the
            # SAME positional index and handed each same-index quartet to
            # add_nodes_and_edges_bulk() together. That was UNSAFE: graphiti_core's
            # default-provider get_entity_edge_save_bulk_query() (verified installed
            # graphiti-core 0.29.3, venv/Lib/site-packages/graphiti_core/models/edges/
            # edge_db_queries.py:176-179) is
            #     UNWIND $entity_edges AS edge
            #     MATCH (source:Entity {uuid: edge.source_node_uuid})
            #     MATCH (target:Entity {uuid: edge.target_node_uuid})
            #     MERGE (source)-[e:RELATES_TO {uuid: edge.uuid}]->(target)
            # - MATCH, not MERGE, on the endpoints. If an edge's endpoint node fell in a
            # LATER positional chunk (no ordering guarantee ties node-chunk-N to
            # edge-chunk-N's endpoints - confirmed by the source read itself: get_by_
            # group_ids() returns rows `ORDER BY uuid DESC`, unrelated to any node/edge
            # pairing), that UNWIND row's MATCH failed and the edge was silently dropped:
            # no exception, no log line, and the old code still reported the full
            # intended count in `upserted`. This is exactly the Task 4.5 real-data dress
            # rehearsal finding (423/627 RELATES_TO, 902/1006 MENTIONS landed on pass 1).
            #
            # FIX: two passes, chunked independently.
            #   Pass 1 (nodes only): every add_nodes_and_edges_bulk() call in this pass
            #     is (episodic_nodes=chunk, episodic_edges=[], entity_nodes=chunk,
            #     entity_edges=[]) - proven safe to call with an empty edges list by
            #     tests/manual/day79_02_task21_empty_list_tolerance_probe.py (Case 2: node
            #     write with entity_edges=[] lands cleanly, zero errors).
            #   Pass 2 (edges only): every call is (episodic_nodes=[], episodic_edges=
            #     chunk, entity_nodes=[], entity_edges=chunk) - proven safe with an empty
            #     nodes list by the same probe script (Case 1: edge write with
            #     entity_nodes=[] against pre-existing endpoints lands cleanly).
            # By the time Pass 1 finishes, EVERY entity node and episodic node in this
            # publish's scope exists on the destination, unconditionally - Pass 2's edge
            # writes can never race a not-yet-written endpoint, regardless of chunk size,
            # chunk count, or source read order. This also still satisfies the pre-existing
            # write-ordering requirement below (episodic nodes must exist before the
            # saga/has_episode/next_episode pass): Pass 1 covers that too, and the saga
            # block runs after BOTH passes complete.
            node_chunk_count = 0
            max_node_len = max(len(entity_nodes), len(episodic_nodes), 1)
            for i in range(0, max_node_len, CHUNK_SIZE):
                en_chunk = entity_nodes[i:i + CHUNK_SIZE]
                ep_chunk = episodic_nodes[i:i + CHUNK_SIZE]
                if not (en_chunk or ep_chunk):
                    continue
                await add_nodes_and_edges_bulk(
                    dest_graphiti.driver, ep_chunk, [], en_chunk, [], write_embedder
                )
                upserted['entity_nodes'] += len(en_chunk)
                upserted['episodic_nodes'] += len(ep_chunk)
                node_chunk_count += 1
                _emit('chunk_written', kind='nodes_pass', offset=i,
                      entity_nodes=len(en_chunk), episodic_nodes=len(ep_chunk))
            _emit('nodes_pass_done', chunks=node_chunk_count,
                  entity_nodes=upserted['entity_nodes'], episodic_nodes=upserted['episodic_nodes'])

            edge_chunk_count = 0
            max_edge_len = max(len(entity_edges), len(episodic_edges), 1)
            for i in range(0, max_edge_len, CHUNK_SIZE):
                ee_chunk = entity_edges[i:i + CHUNK_SIZE]
                epe_chunk = episodic_edges[i:i + CHUNK_SIZE]
                if not (ee_chunk or epe_chunk):
                    continue
                await add_nodes_and_edges_bulk(
                    dest_graphiti.driver, [], epe_chunk, [], ee_chunk, write_embedder
                )
                upserted['entity_edges'] += len(ee_chunk)
                upserted['episodic_edges'] += len(epe_chunk)
                edge_chunk_count += 1
                _emit('chunk_written', kind='edges_pass', offset=i,
                      entity_edges=len(ee_chunk), episodic_edges=len(epe_chunk))
            _emit('edges_pass_done', chunks=edge_chunk_count,
                  entity_edges=upserted['entity_edges'], episodic_edges=upserted['episodic_edges'])

            if publish_mode == PUBLISH_MODE_RE_EMBED:
                reembed_duration = time.time() - reembed_start_time
                _emit(
                    'reembed_done',
                    entity_nodes=upserted['entity_nodes'], entity_edges=upserted['entity_edges'],
                    duration_seconds=reembed_duration,
                )

            # @purpose: isolate the saga/HAS_EPISODE/NEXT_EPISODE loop-wrapped write path's
            # own wall-clock duration from the two bulk passes above (nodes_pass_done/
            # edges_pass_done already time themselves via their own _emit calls and chunk
            # counts - this block had no equivalent). @depends: time.time(), the existing
            # _emit()/print_json_response() progress-event convention used by every other
            # phase in this function (preflight_start/done, read_start/done, nodes_pass_done,
            # edges_pass_done, sweep_start/done). @results: a distinct 'saga_pass_start' /
            # 'saga_pass_done' structured progress event pair, consistent with the existing
            # convention, so GraphitiService.ts could surface it the same way it would any
            # other phase. This is MEASUREMENT ONLY per the Day79.01 Architecture Notes
            # ruling below ("saga path instrumented but deliberately not optimized") - do
            # NOT rewrite this loop-wrapped path as UNWIND based on this instrumentation
            # without new instrumented data showing it is actually necessary.
            saga_pass_start_time = time.time()
            _emit(
                'saga_pass_start',
                saga_nodes=len(scoped['saga_nodes']),
                has_episode_edges=len(scoped['has_episode_edges']),
                next_episode_edges=len(scoped['next_episode_edges']),
            )

            # Hard requirement 4: sagas via the separate write path, sequenced strictly
            # after all episodic nodes above. NEXT_EPISODE is Episodic->Episodic (never
            # Saga->Episodic - verified ../graphiti/graphiti_core/edges.py:822
            # `class NextEpisodeEdge(Edge)` vs :689 `class HasEpisodeEdge(Edge)`, and
            # confirmed by HAS_EPISODE_EDGE_SAVE using saga_uuid/episode_uuid params
            # while NEXT_EPISODE_EDGE_SAVE uses source_episode_uuid/target_episode_uuid -
            # ../graphiti/graphiti_core/models/edges/edge_db_queries.py:305-331).
            #
            # NOTE: uses SagaNode.save(driver) / HasEpisodeEdge.save(driver) /
            # NextEpisodeEdge.save(driver) directly - the model-level .save() methods -
            # rather than the graphiti.nodes.saga.save_bulk() / graphiti.edges.has_episode
            # .save_bulk() namespace API. Discovered during manual verification (2026-08-09)
            # that Neo4jSagaNodeOperations.save() (installed graphiti-core 0.29.3,
            # ../graphiti/graphiti_core/driver/neo4j/operations/saga_node_ops.py:47-57)
            # only forwards uuid/name/group_id/created_at, while its own save query
            # (get_saga_node_save_query) requires summary/first_episode_uuid/
            # last_episode_uuid/last_summarized_at/last_summarized_episode_valid_at too -
            # an upstream graphiti_core bug that raises ParameterMissing on every call.
            # SagaNode.save(driver) (../graphiti/graphiti_core/nodes.py:878-900) builds the
            # correct full param set and falls through to it cleanly here because
            # Neo4jDriver.graph_operations_interface is None (Neo4jDriver exposes ops via
            # separate properties, not that interface) - confirmed against
            # ../graphiti/graphiti_core/driver/neo4j_driver.py. Same reasoning applies to
            # HasEpisodeEdge.save()/NextEpisodeEdge.save(), used here for consistency and
            # because they are unaffected either way. Flagged in the completion report as
            # an upstream bug workaround, not a design choice.
            #
            # OUTCOME (a) CONFIRMED on graphiti-core 0.29.0 too (Day79.01 Phase A
            # Correction 1, 2026-08-09) - this is NOT a 0.29.3-only defect. Static diff of
            # both installed venvs (repo venv/ = 0.29.3, test-vault's
            # %LOCALAPPDATA%\MegaMem\python\test-vault\venv = 0.29.0) shows
            # Neo4jSagaNodeOperations.save() is byte-identical across both versions - it
            # forwards the same 4-of-8-required params on 0.29.0 as on 0.29.3 (0.29.0's
            # save query requires one fewer field than 0.29.3's - no
            # last_summarized_episode_valid_at - but is otherwise the same bug). Live repro
            # against the 0.29.0 venv
            # (tests/manual/day79_01_saga_bug_repro_029.py) reproduced the identical
            # Neo.ClientError.Statement.ParameterMissing calling
            # Neo4jSagaNodeOperations.save() directly, and confirmed SagaNode.save(driver)
            # (this workaround) succeeds cleanly on 0.29.0. The workaround is therefore a
            # hard requirement on BOTH versions this project runs today, not a defensive
            # no-op on one of them - keep as-is on both.
            for i in range(0, len(scoped['saga_nodes']), CHUNK_SIZE):
                chunk = scoped['saga_nodes'][i:i + CHUNK_SIZE]
                for node in chunk:
                    await node.save(dest_graphiti.driver)
                upserted['saga_nodes'] += len(chunk)
                _emit('chunk_written', kind='saga_nodes', offset=i, count=len(chunk))

            for i in range(0, len(scoped['has_episode_edges']), CHUNK_SIZE):
                chunk = scoped['has_episode_edges'][i:i + CHUNK_SIZE]
                for edge in chunk:
                    await edge.save(dest_graphiti.driver)
                upserted['has_episode_edges'] += len(chunk)
                _emit('chunk_written', kind='has_episode_edges', offset=i, count=len(chunk))

            for i in range(0, len(scoped['next_episode_edges']), CHUNK_SIZE):
                chunk = scoped['next_episode_edges'][i:i + CHUNK_SIZE]
                for edge in chunk:
                    await edge.save(dest_graphiti.driver)
                upserted['next_episode_edges'] += len(chunk)
                _emit('chunk_written', kind='next_episode_edges', offset=i, count=len(chunk))

            # Distinct structured progress event closing the saga_pass_start above -
            # this is the real measured wall-clock cost of the loop-wrapped
            # saga/HAS_EPISODE/NEXT_EPISODE write path, separate from nodes_pass_done/
            # edges_pass_done's bulk-write timings. See saga_pass_start comment for the
            # "measure, do not optimize" ruling this event exists to support.
            saga_pass_duration = time.time() - saga_pass_start_time
            _emit(
                'saga_pass_done',
                saga_nodes=upserted['saga_nodes'],
                has_episode_edges=upserted['has_episode_edges'],
                next_episode_edges=upserted['next_episode_edges'],
                duration_seconds=saga_pass_duration,
            )

            _emit('sweep_start', group_ids=dest_group_ids)
            swept = await orphan_sweep_neo4j(
                dest_graphiti.driver, dest_group_ids, kept_node_uuids, kept_edge_uuids, dry_run=False
            )
            _emit('sweep_done', swept=swept)

            # TASK 2.1 - post-write reconciliation. MUST run after every write pass above
            # AND the orphan sweep (reconciling before the sweep would spuriously flag
            # legitimate soon-to-be-swept orphans as "extra"). Compares destination
            # counts, scoped to dest_group_ids, against the source-side scoped set's
            # counts - a genuine post-hoc verification of destination STATE vs INTENT,
            # not merely a re-check of the two-pass fix above. See reconcile_destination()
            # docstring and ReconciliationFailed for full rationale.
            reconciliation = await reconcile_destination(dest_graphiti.driver, dest_group_ids, scoped)
            _emit('reconciliation_done', ok=reconciliation['ok'], per_type=reconciliation['per_type'])
            if not reconciliation['ok']:
                # Hard requirement: no fallback path. A mismatch here can NEVER be logged
                # as a warning and allowed through - raise before write_publish_metadata()
                # is ever reached, so no PublishMetadataGroup record is written claiming a
                # publish that did not actually land in full.
                logger.error(
                    f'[PUBLISH] RECONCILIATION FAILED group_ids={group_ids} '
                    f'dest={_database_identifier(dest_config)} mismatches={reconciliation["mismatches"]}'
                )
                raise ReconciliationFailed(reconciliation['mismatches'], reconciliation)

            # Hard requirement 10 (redesigned per Ruling 3): destination-wide embedder
            # fields on the singleton, PER-GROUP last_publish_at/source_identifier/counts
            # on a PublishMetadataGroup record for every group_id in this run - written/
            # refreshed on every successful, non-dry-run publish. `reconciliation` is
            # embedded into every group's counts_json (Task 2.1 requirement 4) so the
            # audit trail itself proves reconciliation ran and passed - never inferred
            # merely from the absence of an exception.
            #
            # Step 3/4 (2026-08-10): _sample_source_embedding_dim(scoped) is reused
            # UNCHANGED here for both modes - in COPY mode it samples the source's
            # (copied-through) vectors as before; in RE-EMBED mode it samples the SAME
            # in-memory node/edge objects AFTER the write pass above, which
            # generate_name_embedding()/generate_embedding() mutated in place with the
            # destination's real, freshly-written vectors (see that function's docstring
            # for the verified mechanism). Either way, this always reflects what is
            # ACTUALLY now stored on the destination - never a value that could disagree
            # with reality.
            written_dims = _sample_source_embedding_dim(scoped)
            await write_publish_metadata(
                dest_graphiti.driver,
                embedder_provider=dest_config.embedder_provider,
                embedder_model=dest_config.embedding_model,
                embedding_dim=written_dims,
                source_identifier=_database_identifier(source_config),
                group_ids=dest_group_ids,
                reconciliation=reconciliation,
            )
            _emit('metadata_written', embedding_dim=written_dims, group_ids=dest_group_ids, mode=publish_mode)

        duration = time.time() - start_time
        # Hard requirement 14: structured logging per run.
        reconciliation_for_log = reconciliation if not dry_run else None
        logger.info(
            f'[PUBLISH] group_ids={group_ids} dest={_database_identifier(dest_config)} '
            f'mode={publish_mode} dry_run={dry_run} upserted={upserted} swept={swept} '
            f'reconciliation_ok={reconciliation_for_log["ok"] if reconciliation_for_log else "n/a"} '
            f'duration_s={duration:.2f}'
        )
        return {
            'success': True,
            'dry_run': dry_run,
            'group_ids': group_ids,
            'destination': _database_identifier(dest_config),
            'mode': publish_mode,
            'mode_reason': mode_info.get('reason'),
            'upserted': upserted,
            'swept': swept,
            'reconciliation': reconciliation_for_log,
            'duration_seconds': duration,
            'warnings': preflight_result['warnings'],
        }
    finally:
        await _close_graphiti(source_graphiti)
        await _close_graphiti(dest_graphiti)


# ---------------------------------------------------------------------------
# CLI entrypoint (mirrors sync.py's stdin-JSON-in / stdout-JSON-progress protocol)
# ---------------------------------------------------------------------------

def _build_config(section: Dict[str, Any]) -> BridgeConfig:
    """Reuses BridgeConfig.from_dict() - the existing config-loading plumbing - rather
    than opening a second, parallel config path (per DevDoc Task 2 instructions)."""
    # BridgeConfig requires notes/vault_path/models_path for its generic validate(); publish.py
    # doesn't sync notes, so supply harmless placeholders that satisfy from_dict()'s shape
    # without engaging any note-processing code path.
    #
    # Ruling 4 (Day79.01 Phase A correction, 2026-08-09): do NOT use os.getcwd() here.
    # When publish runs headless via MCP later, cwd() at spawn time is an arbitrary
    # directory that happens to look like a real, meaningful value - worse than an
    # obviously-fake one, because a bug that accidentally reads vault_path would fail
    # silently instead of loudly. PUBLISH_JOB_VAULT_PATH_SENTINEL is deliberately
    # unmistakable as a non-path.
    section = {**section}
    section.setdefault('notes', [])
    section.setdefault('vault_path', PUBLISH_JOB_VAULT_PATH_SENTINEL)
    return BridgeConfig.from_dict(section)


def _load_publish_request_from_stdin() -> Dict[str, Any]:
    raw = sys.stdin.read().strip()
    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError(f'Configuration must be a JSON object, got {type(data)}')
    return data


async def _run_command(command: str, request: Dict[str, Any]) -> Dict[str, Any]:
    if command == 'list_group_ids':
        source_config = _build_config(request['source'])
        rows = await list_source_group_ids(source_config)
        return {'success': True, 'group_ids': rows}

    source_config = _build_config(request['source'])
    dest_config = _build_config(request['dest'])
    group_ids = request['group_ids']

    if command == 'preflight':
        result = await preflight(source_config, dest_config, group_ids)
        return {'success': result['ok'], **result}

    if command == 'publish':
        dry_run = bool(request.get('dry_run', False))
        try:
            return await publish(source_config, dest_config, group_ids, dry_run=dry_run)
        except PublishRefused as e:
            return {'success': False, 'message': str(e), 'refusals': e.reasons}
        except ReconciliationFailed as e:
            return {'success': False, 'message': str(e), 'mismatches': e.mismatches, 'reconciliation': e.reconciliation}

    raise ValueError(f'Unknown command: {command}')


def main():
    """CLI entrypoint - mirrors sync.py's shape so GraphitiService.ts can eventually
    spawn this the same way: `python -m graphiti_bridge.publish --command publish`,
    JSON request on stdin, line-by-line JSON progress on stdout, final JSON result as
    the last stdout line."""
    parser = argparse.ArgumentParser(description='Graphiti Bridge Publish Script')
    parser.add_argument('--command', choices=['list_group_ids', 'preflight', 'publish'], required=True)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    original_stderr = sys.stderr
    if not args.debug:
        try:
            sys.stderr = open(os.devnull, 'w')
            for logger_name in ['openai', 'httpx', 'neo4j', 'asyncio', 'urllib3', 'httpcore']:
                logger_obj = logging.getLogger(logger_name)
                logger_obj.disabled = True
                logger_obj.setLevel(logging.CRITICAL + 1)
                logger_obj.handlers.clear()
            os.environ['GRAPHITI_TELEMETRY_ENABLED'] = 'false'
        except Exception:
            pass
    else:
        logging.basicConfig(level=logging.DEBUG, stream=original_stderr)

    try:
        request = _load_publish_request_from_stdin()
        result = asyncio.run(_run_command(args.command, request))
        if not args.debug:
            sys.stderr.close()
            sys.stderr = original_stderr
        print_final_json_response(result)
    except Exception as e:
        if not args.debug and sys.stderr != original_stderr:
            try:
                sys.stderr.close()
            except Exception:
                pass
            sys.stderr = original_stderr
        tb = traceback.format_exc()
        error_response = {
            'success': False,
            'message': f'Publish process failed: {e}',
            'exception': str(e),
            'traceback': tb,
        }
        print(json.dumps(error_response, ensure_ascii=False, separators=(',', ':')), flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()