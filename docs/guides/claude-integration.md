---
title: Claude Integration Guide
description: Claude Desktop integration with MegaMem
type: guide
category: setup
difficulty: beginner
tags:
  - claude
  - mcp
  - integration
last_updated: 2025-01-23
date_created: 2025-09-23T11:43
date_updated: 2026-10-13T00:00
---

# Claude Integration Guide

It's pretty self-explanatory, more advanced guides and use-case-scenarios coming soon.

## Connecting Claude Desktop

Claude Desktop can connect two ways:

- **STDIO** — Plugin Settings → Servers → **STDIO MCP Server** → **Generate Config**, paste into `claude_desktop_config.json`, restart Claude Desktop.
- **Streamable HTTP via `mcp-remote`** — Plugin Settings → Servers → **Streamable HTTP Access** → **Copy Config for: Claude Desktop**. This config runs `npx mcp-remote`, so **Node.js must be installed**. If Node.js isn't found when you copy the config, MegaMem shows a warning (without it Claude Desktop fails with `spawn npx ENOENT`).

## Troubleshooting

- **Server exits at startup with a FATAL message about `mcp`:** the MCP server requires `mcp>=1.28,<2`. Open Plugin Settings → Python Environment → **Install Dependencies** (after upgrading to v1.8.0 this is required once).
- **First start on Windows times out:** Defender scanning a freshly created venv can exceed the MCP handshake window. Restart Claude Desktop once; consider a Defender exclusion for the venv folder.
- **`ask_bjorn` tool missing:** it is only listed when your Pro key is valid and has the `service.ask_bjorn` capability (Plugin Settings → Pro tab).