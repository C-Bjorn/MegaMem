# MegaMem: Obsidian MCP with SuperPowers

## Graphiti | GraphRAG | MCP

Transform your Obsidian vault into a temporal knowledge graph powered by Graphiti. This plugin automatically discovers schema patterns from your notes' frontmatter and syncs them to a knowledge graph accessible by AI assistants through the Model Context Protocol (MCP).

### ALPHA Launch

**IMPORTANT** _Not all features and functions are fully tested. We actively use this plugin every day with our intenral team, working on Windows with Neo4j. Although the infrastructure is there to support Mac/Linux & other db providers, we haven't tested them yet._

- **Development Repo** is private, along with obsidian source code. As we near Beta Launch, all source code will be pushed to this repo and request made to Obsidian Community Plugins.
- **Early beta-testers** are encouraged to contact the developer for a full obsidian template and customization services. Trust me, even at this stage, it's worth it(!)

## 🌟 Key Features

### 🔍 Automatic Schema Discovery

- **Smart Vault Scanning**: Automatically discovers entity types and properties from your existing notes' frontmatter
- **Intelligent Type Inference**: Analyzes actual values to determine property types (string, number, date, array, etc.)
- **No Manual Configuration**: Unlike traditional approaches, you don't need to define schemas manually

### 🏗️ Schema Management

- **Visual Schema Editor**: Intuitive interface to review and customize discovered schemas
- **Property Management**: Toggle properties on/off, edit descriptions, and refine types
- **Pydantic Model Generation**: One-click generation of Python models for Graphiti integration
- **Best Practices Compliance**: Automatic validation against Graphiti naming conventions and protected attributes

### 🔄 Enhanced Knowledge Graph Sync

- **Intelligent Auto Sync**: Smart synchronization with granular control over when and what gets synced
- **Filtering Options**: Choose between syncing "New notes only" or "New and updated notes"
- **Real-time Synchronization**: Automatic sync on save, scheduled intervals, and manual triggers
- **Custom Entity Support**: Define your own entity types beyond standard Person/Company models
- **Relationship Mapping**: Automatically extract and map relationships between entities

### 🤖 AI Assistant Integration

- **MCP Protocol Support**: Make your knowledge graph accessible to Claude and other AI assistants
- **Contextual Search**: AI can query your knowledge graph for relevant information
- **Dynamic Ontologies**: Your custom schemas are understood by AI assistants
- **Enhanced AI Responses**: Get more accurate, context-aware responses based on your personal knowledge

## 🚀 Getting Started

### Prerequisites

1. **Obsidian**: Version 0.15.0 or higher
2. **Database**: Neo4j Desktop or FalkorDB (via Docker)
3. **Python**: Version 3.11+ (for MCP server)
4. **Node.js**: Version 18+ (for development)

### Quick Setup

1. Install the plugin from Obsidian Community Plugins (coming soon) or build from source
2. Set up your graph database (Neo4j or FalkorDB)
3. Configure the MCP server for AI integration
4. Open the Schema Manager to discover your vault's patterns
5. Start syncing your notes to the knowledge graph!

## 📋 How It Works

### 1. Schema Discovery

The plugin scans your vault to find patterns in frontmatter:

```yaml
---
type: Person
name: "John Doe"
occupation: "Software Engineer"
company: "TechCorp"
skills: ["Python", "JavaScript", "GraphQL"]
---
```

### 2. Automatic Type Detection

Based on your actual data, the plugin infers property types and generates schemas:

```python
class Person(BaseModel):
    name: Optional[str] = Field(None, description="Person's full name")
    occupation: Optional[str] = Field(None, description="Current occupation")
    company: Optional[str] = Field(None, description="Current employer")
    skills: Optional[List[str]] = Field(None, description="List of skills")
```

### 3. Knowledge Graph Sync

Your notes are transformed into a temporal knowledge graph:

- Entities become nodes with properties
- Relationships are extracted from content
- Consecutive notes dynamically update the Graph
- AI assistants can query this structured data

## 🎯 Use Cases

### Personal Knowledge Management

- Track people you meet, companies you research, projects you work on
- Build a personal CRM within Obsidian
- Visualize connections between ideas and entities

### Research & Academia

- Organize research papers, authors, and concepts
- Track citations and relationships between works
- Build domain-specific knowledge graphs

### Business Intelligence

- Track competitors, market trends, and industry insights
- Build company knowledge bases
- Create structured data from unstructured notes

### Creative Projects

- Manage characters, locations, and plot elements for writing
- Track inspiration sources and creative connections
- Build world-building databases

## 🛠️ Configuration

### Database Setup

Choose between:

- **Neo4j Desktop**: Full-featured graph database with visualization
- **FalkorDB**: Lightweight Redis-based graph database
- **Kuzu**: coming soon
- **Neptune**: coming soon

### Model Context Protocol (MCP) Server

The plugin features a custom MCP server that seamlessly bridges your Obsidian vault with AI assistants. It enables:

- **Intelligent Communication**: Facilitates communication between your vault, Graphiti, and connected AI models.
- **AI-Powered Access**: Allows AI assistants to directly interact with and query your knowledge graph.
- **Dynamic Schema Sync**: Manages the synchronization of your discovered schema patterns, ensuring AI understands your custom data structures.

### Plugin Settings

- **Database Configuration**: Connection details and credentials
- **Auto Sync Settings**: Enable/disable automatic synchronization with intelligent filtering
- **Sync Options**: Choose between "New notes only" or "New and updated notes" for auto sync
- **Sync Preferences**: Choose folders to include/exclude from synchronization
- **Field Management**: Set globally ignored properties
- **Advanced Options**: Batch sizes, logging, performance tuning, and sync intervals

## 📚 Documentation

Explore the comprehensive documentation for MegaMem to get started and deepen your understanding:

### Getting Started

- [**Introduction**](https://c-bjorn.github.io/MegaMem/) - Overview of MegaMem and its core concepts.
- [**Quick Start Guide**](https://c-bjorn.github.io/MegaMem/quick-start) - Get up and running in minutes.
- [**Plugin Settings**](https://c-bjorn.github.io/MegaMem/plugin-settings) - Detailed reference for all configuration options.

### Advanced Guides

- [**Database Setup**](https://c-bjorn.github.io/MegaMem/guides/database-setup) - Configure your preferred graph database.
- [**Claude Desktop Integration**](https://c-bjorn.github.io/MegaMem/guides/claude-integration) - Connect MegaMem with Claude Desktop.
- [**Custom Entity Types & Ontology Manager**](https://c-bjorn.github.io/MegaMem/guides/ontology-manager) - Define and manage your custom data schemas.
- [**Sync Manager**](https://c-bjorn.github.io/MegaMem/guides/sync-manager) - Control how your notes are synchronized with the knowledge graph.
- [**MCP Commands**](https://c-bjorn.github.io/MegaMem/mcp-commands) - Reference for available Model Context Protocol commands.

### Community & Contribution

- [**Roadmap**](https://c-bjorn.github.io/MegaMem/roadmap) - See what's coming next for MegaMem.
- [**Contributing Guide**](https://c-bjorn.github.io/MegaMem/contributing) - Learn how to contribute to the project.
- [**FAQ**](https://c-bjorn.github.io/MegaMem/faq) - Find answers to frequently asked questions.

## 🤝 Community & Support

- **GitHub Issues**: Report bugs or request features
- **Discussions**: Share use cases and get help
- **Discord**: Join our community (coming soon)
- **Documentation**: Comprehensive guides and examples

## 🔮 Roadmap

### Current (v1.0)

- ✅ Automatic schema discovery
- ✅ Enhanced auto sync with granular filtering
- ✅ Intelligent sync options (new vs. new+updated notes)
- ✅ Real-time and scheduled synchronization
- ✅ MCP server integration
- ✅ Essential UI components

### Planned Features

- 🔄 Visual graph exploration
- 🔄 Advanced query builder
- 🔄 Batch operations
- 🔄 Plugin ecosystem integration
- 🔄 Cloud sync options
- 🔄 Mobile support

## 💡 Philosophy

This plugin embraces the principle of **progressive formalization**. Start with simple notes, let patterns emerge naturally, then gradually add structure as your knowledge grows. No need to define rigid schemas upfront – the plugin discovers them from your actual usage.

## 🙏 Acknowledgments

Built with:

- [Obsidian API](https://github.com/obsidianmd/obsidian-api)
- [Graphiti](https://github.com/getzep/graphiti) by Zep
- [Svelte](https://svelte.dev/) & [UnoCSS](https://unocss.dev/)
- Model Context Protocol (MCP) by Anthropic

## 📄 License

MIT License - see [LICENSE.txt](LICENSE.txt) for details

---

**Transform your notes into knowledge. Build your personal AI-powered knowledge graph today.**

_Created by [Casey Bjørn](https://github.com/C-Bjorn)_
