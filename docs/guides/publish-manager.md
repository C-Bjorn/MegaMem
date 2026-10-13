---
title: Publish — Scoped Graph Replication
description: Publish a curated slice of your MegaMem graph to a hosted destination database, without exposing your private notes or your machine.
type: guide
category: Advanced
difficulty: intermediate
tags:
  - Publish
  - Aura
  - Neo4j
  - Security
  - Graph
last_updated: 2026-08-11
date_created: 2026-08-09T00:00
date_updated: 2026-10-13T00:00
---

# Publish — Scoped Graph Replication

The **Publish** tab replicates a chosen `group_id` namespace from your source graph to a separate, hosted destination graph. It exists so you (or an AI assistant on your website) can query a curated slice of your knowledge graph without ever exposing your private notes, your other namespaces, or your personal machine.

> **v1.8.0:** Publish writes in two passes (nodes, then edges) and then reconciles the destination's record and embedding counts against what it intended to write; a mismatch fails the run loudly instead of passing silently. A defect in which a publish could silently drop data was fixed in this release — if you published with an earlier version, run Publish again.

## Publish vs. Sync — this distinction matters

- **Sync** = vault → graph. It reads your notes and writes entities/edges into your graph database.
- **Publish** = graph → graph. It reads already-extracted entities/edges from a **source** database and replicates them into a **destination** database.

Publish never touches your vault, never re-runs LLM extraction, and never talks to your notes. It only moves Graphiti's own node and edge records from one database to another. Keep this distinction in mind everywhere you see the word "Publish" in this plugin — it is deliberately never called "Sync."

## The group_id-only rule — and why it's not negotiable

Publish lets you select **one or more `group_id` namespaces** to replicate. There is no per-note or per-episode "publish this note" checkbox anywhere, and there never will be. Here's why, in plain terms:

Graphiti (the graph engine underneath MegaMem) treats entities as unique **within a `group_id`**, not within a note. If your private note and your public note both mention "Neo4j," Graphiti merges them into a single "Neo4j" entity in that namespace. That entity node — and every relationship hanging off it — is shared. There is no way to cleanly cut a "publish this episode's slice" boundary through a subgraph that's already been merged this way; you'd either publish the whole shared entity (bringing your private note's context along with it) or you'd have to unmerge something Graphiti has already merged.

The only boundary that's actually safe to cut along is the `group_id` boundary itself, because entities and edges never span across group_ids — Graphiti's own deduplication guarantees that. So `group_id` is the *sole* selection predicate for what gets published. If you need finer-grained control over what's public, the answer is to put that content in its own `group_id` (a dedicated folder mapping), not to look for a per-note flag that doesn't exist.

## Setting up an Aura destination

[Neo4j Aura](https://neo4j.com/docs/aura/getting-started/create-instance/) is the reference hosted destination for Publish. To set one up:

1. **Create the instance directly in the Aura console** — https://console.neo4j.io. Do **not** use Neo4j Desktop's "Deploy to Aura" feature; that path dumps and uploads your *entire* local database with no scope filter, which defeats the entire point of a scoped publish.
2. **Save the generated credentials immediately.** The password is shown exactly **once** at creation time and cannot be recovered afterward — if you lose it, you'll need to reset it or create a new instance.
3. **Register the database in MegaMem's Database settings** using the connection URI Aura gives you (`neo4j+s://<instance-id>.databases.neo4j.io`). `neo4j+s://` URIs are parsed correctly as of v1.8.0, and Aura credentials are passed through to the destination connection.

### The database name gotcha

When registering the Aura instance, you'll be tempted to leave the database name as the default `neo4j` — **don't**. Aura database names are the **instance ID**, not the literal string `"neo4j"`. For example, an instance at `cd92a120.databases.neo4j.io` has a database named `cd92a120`, not `neo4j`. Connecting with `database: "neo4j"` against an Aura instance fails with `DatabaseNotFound`.

Find your instance's real database name in the Aura console's connection details (it's the same string as the instance ID in your connection URI), and enter that exact value in MegaMem's **Database Name** field when registering the destination. This is a one-time configuration detail — no code change is needed, Graphiti already supports custom database names natively.

### Aura Free limitations to know about

- **Auto-pauses after 72 hours of inactivity** and is deleted after 30 days paused. If you're hosting a public-facing consumer, that consumer needs its own periodic "keep-alive" query — Publish itself doesn't run a background daemon (see *Scheduling* below).
- **One instance per account** on the Free tier. Test your publish job against a second local database, not a second Aura instance.
- **APOC Core only** — no APOC Extended procedures. Nothing in Publish depends on them.

## The allowedDatabases gotcha (HTTP MCP tokens)

This one is easy to miss and will produce a confusing failure if you don't know about it.

Registering a new database (such as your new Aura destination) in MegaMem's Database settings makes it available to the plugin — but it does **not** automatically add it to any existing HTTP MCP token profile's allowlist. Each token profile under **Settings → Servers → Streamable HTTP Access** has its own `allowedDatabases` list, and an empty list there is treated as "all databases allowed" — but a *non-empty* list is a strict allowlist that a newly-registered database is **not** automatically added to.

**If you intend to query a newly-registered database through an HTTP token profile that already has a non-empty database allowlist:**

1. Go to **Settings → Servers → Streamable HTTP Access**.
2. Expand the relevant token profile.
3. Find the database checklist and check the box for your newly-registered database.
4. Save.

If you skip this step, queries against the new database will fail with `DATABASE_NOT_PERMITTED` — even though the database itself is correctly configured, reachable, and works fine everywhere else in the plugin. This is a token-profile permission gap, not a database connectivity problem; don't waste time re-checking your connection string.

## Embedder parity — why Publish can refuse to run, and why it usually doesn't need to

Every entity and edge in your graph carries a vector embedding used for semantic (vector) search. The rule that actually matters is: **the destination's embeddings must have been produced by the destination's own currently-configured embedder** — not that source and destination need to match each other. A local Ollama source and a hosted OpenAI/OpenRouter destination are expected to use *different* embedders, since a serverless query backend usually can't reach a local Ollama instance at all.

To make this safe, Publish **derives** one of three modes on every run — never a manual choice:

- **COPY** — source and destination declare the same embedder. Vectors pass through byte-for-byte, no re-embedding, no cost.
- **RE-EMBED** — source and destination embedders differ (the normal case for a local source + hosted destination), or the destination's configured embedder has changed since its last publish. The destination's own embedder generates fresh vectors for every record in the scoped set. A destination-embedder *change* always forces a **full**, non-incremental re-embed of everything previously published to that destination — never just the newly-touched records — so the destination is never left holding a mix of old- and new-embedder vectors.
- **COPY (no destination embedder configured)** — vectors copy through as-is; there's nothing to re-embed with.

Preflight discloses which mode will run, the source/destination embedder identity, and — in RE-EMBED mode — an estimated record count and cost before you commit. If RE-EMBED mode would run, preflight also makes one real test call to the destination's embedder first, so a misconfigured or unauthenticated credential is caught immediately as a specific refusal rather than mid-publish after a full source read.

The one case that's still always a hard refusal, regardless of mode: the **source's** measured embedding dimension disagreeing with what a prior publish recorded for it. That's a sign of drift at the source itself, not something re-embedding can safely paper over.

- The destination graph carries a `PublishMetadata` record (embedder provider, embedder model, embedding dimension) written on every successful publish.
- A per-`group_id` `PublishMetadataGroup` record is also written on every successful publish, holding that group's `last_publish_at` timestamp, source identifier, and record counts. A downstream consumer (e.g. a chat backend querying the destination) can read the singleton `PublishMetadata` record to self-check embedder identity, and read the per-group record to check that specific `group_id`'s freshness before trusting the answer it's about to give.

## The group_id selector's counts

When you pick a source database in the Publish tab, the group_id selector lists every namespace in that source along with live entity/episode/edge counts. This isn't just informational — it's a safety affordance. Before you commit to publishing a namespace, you can see exactly how much you're about to expose to the destination (and, by extension, to whoever queries that destination). Always check the counts before hitting Publish, especially the first time you publish a given `group_id`.

## Preflight refusals

Every publish attempt — including dry runs — starts with a **preflight** check. Preflight never returns a plain pass/fail; it returns a structured result with specific reasons, shown directly in the UI panel. Common refusal codes you may see:

| Code | Meaning |
|---|---|
| `same_source_destination` | Source and destination resolve to the exact same database — publishing to yourself is refused outright. |
| `source_unreachable` | Could not connect to the source database. |
| `destination_unreachable` | Could not connect to the destination database. |
| `destination_schema_missing` | Destination has zero indexes even after schema initialization — something went wrong setting it up. |
| `embedder_dimension_mismatch` | The **source's** measured embedding dimension disagrees with what a prior publish recorded for it — a sign of drift at the source, always a hard refusal regardless of embedder mode. |
| `embedder_auth_failed` | RE-EMBED mode would run, but a real test call to the destination's configured embedder failed authentication (e.g. an invalid or missing API key). Carries the provider's actual error message. |
| `embedder_unreachable` | RE-EMBED mode would run, but the destination's configured embedder couldn't be reached at all (network error, not an auth error). |

A destination-embedder-model *change* (as opposed to a dimension mismatch at the source) is **not** a refusal — it resolves to RE-EMBED mode instead, disclosed as a non-blocking warning with the record count and cost estimate before the run. Preflight can also surface other non-blocking **warnings** (for example, if community nodes exist in the scoped source set — communities are deliberately excluded from Publish and will not be replicated). Warnings don't block the run; refusals do.

## Dry run

The dry-run toggle lets you preview a publish before committing to it. A dry run reports exactly what a real publish would upsert and sweep — same counts, same orphan-sweep preview — and writes **no** node, edge, or metadata data to the destination.

One side effect worth knowing about: connecting to a destination at all (which preflight always does, dry run or not) triggers Graphiti's own schema initialization on that destination, creating its standard indexes and constraints if they don't already exist. This happens as an unavoidable consequence of establishing the connection — it is **not** something Publish does deliberately as part of the dry run, and it writes no actual graph data. If you need to probe a destination without creating any schema on it at all, don't run preflight or publish against it.

## Scheduling

Publish supports interval-based scheduling, mirroring the existing sync scheduler. Pick a source, destination, and group_id selection, set an interval, and enable scheduling — Publish will re-run automatically on that interval.

**Scheduled publishing requires Obsidian to be running.** There is no background daemon or separate process; if Obsidian is closed, no scheduled publish fires until you reopen it. This is stated directly in the Schedule section of the Publish tab as well.

## No vector index at current scale (FYI)

At typical current usage scale (a few hundred entities), Publish/Aura destinations run vector search as **exact brute-force cosine similarity** rather than through a formal vector index. This is a deliberate choice, not a limitation to work around:

- At small scale, brute-force cosine has no meaningful performance cost and, unlike an approximate index (HNSW/ANN), has zero approximation error.
- It also structurally eliminates one entire failure mode: a vector index built at the wrong dimension can silently return confidently-wrong results, and that can't happen if there's no index to mismatch in the first place.

This isn't something you need to configure — it's just useful context if you're curious why there's no "create vector index" step in the destination setup. Past a few thousand entities, a vector index becomes worth revisiting; below that, it isn't.
