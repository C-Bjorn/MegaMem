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

### Method 2: Manual Installation

1. **Download Latest Release**
   - Visit https://github.com/C-Bjorn/megamem-mcp/releases
   - Download the latest release ZIP file
   - Extract the contents to your vault's `.obsidian/plugins/megamem-mcp/` directory

2. **Enable Plugin**
   - Restart Obsidian
   - Go to `Settings` → `Community plugins`
   - Enable "MegaMem MCP"

## ⚡ 6-Step Setup

### Step 1: Database Setup
Setup your preferred database (Neo4j or FalkorDB - see [Database Setup](guides/database-setup.md) for details). **Kuzu & Amazon Neptune coming soon**

### Step 2: LLM Configuration  
In Plugin Settings, add your LLM keys and configuration (select "Load Defaults" to start)

### Step 3: Database Configuration
In Plugin Settings, enter the Database Configuration and click "Test Connection" and then "Initialize Schema"

### Step 4: Python Dependencies
Under Python Environment, click "Install Dependencies"

### Step 5: Basic Setup Complete
For basic functionality - leave everything else default.

### Step 6: Advanced Configuration (Optional)
For custom ontologies, set [Knowledge Namespacing](plugin-settings.md#knowledge-namespacing) settings, and review "Ontology Manager" section.

## 🤖 MCP Server Setup (for Claude Desktop and other private LLM consoles)

1. **Generate MCP Configuration**
   - Go to Plugin Settings → Servers section
   - Click "Generate Config" button
   - Copy the generated configuration

2. **Apply to Your MCP Client**
   - Paste the configuration into your Claude Desktop config or other MCP client
   - Restart your MCP client
   - Verify connection in chat interface

## ✅ Verification Checklist

- [ ] Database connection successful
- [ ] LLM provider responding correctly  
- [ ] Python dependencies installed
- [ ] Plugin enabled and configured
- [ ] Claude Desktop MCP connection active

---

**🎉 Congratulations!** MegaMem is now transforming your Obsidian vault into an intelligent knowledge graph. Explore the [Plugin Settings](plugin-settings.md) to unlock advanced features.