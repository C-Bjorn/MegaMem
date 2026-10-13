---
title: Publishing a Public Graph
description: Let others — or an AI assistant on your website — query a curated slice of your knowledge graph, without exposing your private notes or your machine.
date: 2026-08-09
tags:
  - publish
  - aura
  - security
sidebar: auto
date_created: 2026-08-09T00:00
date_updated: 2026-08-09T00:00
---

# 🌐 Publishing a Public Graph

You've built a knowledge graph in MegaMem. Some of it is private — your journal, your client notes, your drafts. Some of it isn't — your public writing, your documentation, the stuff you'd happily let a website chatbot answer questions about.

**Publish** lets you share exactly that second part, and nothing else.

## How it works

Publish replicates a chosen namespace (a `group_id`) from your graph into a separate destination database — a hosted [Neo4j Aura](https://neo4j.com/aura) instance, for example. The flow is three clicks:

1. **Pick a namespace** — the group of notes you've already organized as "public."
2. **Pick a destination** — a hosted graph database you control.
3. **Hit Publish.**

That's it. The destination now holds a live, queryable copy of that one namespace — nothing else.

## The key idea: it's a replica, not a window

This isn't a tunnel into your vault, and it isn't a proxy that forwards queries to your machine. The destination is a **real, independent copy** of just the data you selected — disposable, and never a peer of your source graph. Nothing on the destination can write back to your source, and nothing about querying the destination ever reaches your personal machine.

That means:

- **Your source graph is never exposed.** The public consumer talks only to the destination.
- **Your machine doesn't need to be online.** Once published, the destination serves queries on its own — no dependency on your laptop being powered on or your vault being open (aside from re-running Publish itself, which is scheduled and optional).
- **Everything outside the selected namespace stays private.** Namespaces are never merged, and there's no way to select "some of a namespace" — you either publish a namespace in full or not at all, which is exactly what keeps the boundary clean and safe.

## Why this is worth doing

If you've ever wanted an AI assistant on your own website to answer questions grounded in your actual public writing — not a generic LLM guess, but your specific graph of entities and relationships — this is how you get there without handing that assistant (or the internet) a door into your private knowledge base.

## Getting set up

Publish ships free in the MegaMem plugin. For the full setup walkthrough — creating a hosted destination, the specific setting you need to get right when registering it, and how scheduling works — see the [Publish settings guide](guides/publish-manager.md).
