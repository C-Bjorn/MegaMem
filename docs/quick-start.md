---
title: Quick Start Guide
description: Get MegaMem running in your Obsidian vault in under 5 minutes
date: 2025-09-23
tags:
  - setup
  - installation
  - configuration
  - quickstart
sidebar: auto
date_created: 2025-09-23T11:20
date_updated: 2025-09-28T11:36
---

# 🚀 Quick Start Guide

Get MegaMem running in your Obsidian vault in under 5 minutes with this streamlined setup process.

## 📦 Installation

### Method 1: Community Plugins (Coming Soon!)

1. **Open Obsidian Settings**
   - Go to `Settings` → `Community plugins`
   - Disable `Safe mode` if enabled

2. **Install MegaMem**
   - Click `Browse` and search for "MegaMem"
   - Click `Install` → `Enable`

### Method 2: BRAT (Beta Reviewers and Auto-update Tool)

1. **Install BRAT** from Community Plugins if you haven't already

2. **Add MegaMem via BRAT**
   - Open BRAT settings → `Add Beta Plugin`
   - Enter: `C-Bjorn/megamem-mcp`
   - Click `Add Plugin`

3. **Python Components Install Automatically**
   - After ~3 seconds, a dialog will appear: **"Install / Update Components"**
   - Click the button — MegaMem downloads and installs `graphiti_bridge` and `mcp-server` automatically
   - No manual file downloads required

### Method 3: Manual Installation

1. **Download Latest Release**
   - Visit https://github.com/C-Bjorn/megamem-mcp/releases
   - Download the latest release ZIP file
   - Extract the contents to your vault's `.obsidian/plugins/megamem-mcp/` directory

2. **Enable Plugin**
   - Restart Obsidian
   - Go to `Settings` → `Community plugins`
   - Enable "MegaMem MCP"

## ⚡ 7-Step Setup

### Step 0: Register Obsidian CLI *(Required for MCP file tools)*

MegaMem's MCP server uses the **Obsidian CLI** (native since Obsidian 1.12) to read, write, and search vault files without a persistent WebSocket connection. Follow these steps before anything else:

1. **Download and run the Obsidian 1.12.4+ installer** from [obsidian.md/download](https://obsidian.md/download)
   > ⚠️ **In-app auto-update is NOT sufficient** — it updates the app version but not the installer. You must run the full installer to get the CLI binary.

2. **Enable CLI in Obsidian Settings**
   - Open Obsidian → `Settings` → `General`
   - Find the **"Command line interface"** section and toggle it on
   - Click **"Register"** to add `obsidian` to your system PATH

3. **Restart your terminal** (PATH changes only apply to new terminal sessions)

4. **Verify** by running `obsidian version` in a terminal — you should see a version string.
   - *Windows note:* The CLI uses `Obsidian.com` (a terminal redirector) installed alongside `Obsidian.exe`. This ships with the 1.12.4+ installer automatically.

> **Tip:** In MegaMem Plugin Settings → Servers, use the **"Verify CLI"** button to confirm the CLI is accessible without opening a terminal.

---

### Step 1: Database Setup
Setup your preferred database (Neo4j or FalkorDB - see [Database Setup](guides/database-setup.md) for details). **Kuzu & Amazon Neptune coming soon**

### Step 2: Python Dependencies
Under Python Environment (first accordion section), click **"Install Dependencies"**.

Uses the **UV Package Manager** by default — recommended for all platforms (macOS, Windows, Linux). System Python is available for advanced users who prefer their own environment.

### Step 3: LLM Configuration
In Plugin Settings → API Keys, add your LLM provider key and select "Load Defaults" to populate recommended models.

### Step 4: Database Configuration
In Plugin Settings → Database Configuration, enter your connection details and click **"Test Connection"** then **"Initialize Schema"**.

### Step 5: Basic Setup Complete
For basic functionality - leave everything else default.

> ⚠️ **Frontmatter requirement:** Notes must have a **`type`** property in their frontmatter to be synced. Without it, the note is skipped. Example:
> ```yaml
> ---
> type: Person
> name: "Jane Smith"
> ---
> ```

### Step 6: Sync Your Notes

Two ways to sync:
- **Single note** — click the **sync icon** in the top-right of any note window to sync that note
- **Bulk sync** — click the **MegaMem icon** in the left sidebar to open the **Sync Manager** for batch operations

### Step 7: Advanced Configuration (Optional)
For custom ontologies, set [Knowledge Namespacing](plugin-settings.md#knowledge-namespacing) settings, and review the "Ontology Manager" section.

## 🤖 MCP Server Setup (for Claude Desktop and other private LLM consoles)

1. **Generate MCP Configuration**
   - Go to Plugin Settings → Servers section
   - Click "Generate Config" button
   - Copy the generated configuration (formatted with `mcpServers` wrapper for Claude Desktop compatibility)

2. **Apply to Your MCP Client**
   - For Claude Desktop: Paste the configuration into your `claude_desktop_config.json` file
   - For other MCP clients: Use the configuration as directed by your client's documentation
   - Restart your MCP client
   - Verify connection in chat interface

## ✅ Verification Checklist

- [ ] Obsidian 1.12.4+ installer run and CLI registered in PATH
- [ ] `obsidian version` returns a version string in terminal
- [ ] Python dependencies installed
- [ ] Database connection successful (Test Connection ✓)
- [ ] LLM provider responding correctly
- [ ] At least one note has `type:` in frontmatter
- [ ] Sync icon syncs a note successfully
- [ ] Claude Desktop MCP connection active

---

**🎉 Congratulations!** MegaMem is now transforming your Obsidian vault into an intelligent knowledge graph. Explore the [Plugin Settings](plugin-settings.md) to unlock advanced features.