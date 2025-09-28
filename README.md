# Graphiti Knowledge Graph Integration for Obsidian

### ALPHA Launch
**Actively used in development on Windows with Neo4j, not fully tested on Mac/Linux or alt.dbs**
Early beta-testers are encouraged to contact the developer for a full obsidian template install with customization services.  Trust me, even at this stage, it's worth it(!)

Transform your Obsidian vault into a temporal knowledge graph powered by Graphiti. This plugin automatically discovers schema patterns from your notes' frontmatter and syncs them to a knowledge graph accessible by AI assistants through the Model Context Protocol (MCP).

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
- **Temporal Awareness**: Track how your knowledge evolves over time with enhanced source tracking

### 🤖 AI Assistant Integration
- **MCP Protocol Support**: Make your knowledge graph accessible to Claude and other AI assistants
- **Contextual Search**: AI can query your knowledge graph for relevant information
- **Dynamic Ontologies**: Your custom schemas are understood by AI assistants
- **Enhanced AI Responses**: Get more accurate, context-aware responses based on your personal knowledge

## 🚀 Getting Started

### Prerequisites
1. **Obsidian**: Version 0.15.0 or higher
2. **Database**: Neo4j Desktop or FalkorDB (via Docker)
3. **Python**: Version 3.9+ (for MCP server)
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
- Time-based tracking shows knowledge evolution
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

### MCP Server
The plugin includes a custom MCP server that:
- Handles communication with Graphiti
- Provides AI assistant access
- Manages schema synchronization

### Plugin Settings
- **Database Configuration**: Connection details and credentials
- **Auto Sync Settings**: Enable/disable automatic synchronization with intelligent filtering
- **Sync Options**: Choose between "New notes only" or "New and updated notes" for auto sync
- **Sync Preferences**: Choose folders to include/exclude from synchronization
- **Field Management**: Set globally ignored properties
- **Advanced Options**: Batch sizes, logging, performance tuning, and sync intervals

## 📚 Documentation

### For Users
- [Installation Guide](docs/INSTALLATION.md)
- [User Manual](docs/USER_GUIDE.md)
- [Schema Examples](docs/examples/)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

### For Developers
- [Architecture Overview](roo_docs/architecture-diagram.md)
- [API Documentation](docs/API.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Development Setup](docs/DEVELOPMENT.md)

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

*Created by [Casey Jeppesen](https://github.com/kcsf)*
