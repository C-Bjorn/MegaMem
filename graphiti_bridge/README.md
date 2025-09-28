# Graphiti Bridge

Python bridge for connecting Obsidian plugin with Graphiti temporal knowledge graphs.

## Overview

This directory contains the Python components that bridge the TypeScript Obsidian plugin with the Graphiti library. The bridge uses a simple process-spawning approach with JSON communication for maximum compatibility and minimal complexity.

## Architecture

```
Obsidian Plugin (TypeScript)
    ↓ spawn Python process
Python Bridge Script
    ↓ imports graphiti-core
    ↓ loads custom Pydantic models
    ↓ initializes Graphiti with user's LLM config
    ↓ processes notes into episodes
Graphiti → Neo4j/FalkorDB
```

## Directory Structure

```
graphiti_bridge/
├── __init__.py          # Package initialization
├── install.py           # Hybrid pip/uv installation script
├── sync.py              # Main sync script
├── models.py            # Import generated Pydantic models
├── config.py            # Configuration handling
├── utils.py             # Helper functions
└── README.md            # This file
```

## Installation

The installation script automatically detects your Python environment and uses the best available package manager:

```bash
# From the plugin directory
python graphiti_bridge/install.py
```

Or with configuration:

```bash
echo '{"llmProvider": "openai", "databaseType": "neo4j"}' | python graphiti_bridge/install.py
```

### Supported Package Managers

1. **UV** (preferred): Faster, modern Python package manager
2. **pip** (fallback): Standard Python package manager

### Requirements

- Python 3.10 or higher
- Internet connection for package installation

## Usage

The bridge is designed to be called from the TypeScript plugin:

```typescript
const config = {
    llmProvider: 'openai',
    llmApiKey: 'sk-...',
    llmModel: 'gpt-4o',
    // ... other configuration
    notes: ['path/to/note1.md', 'path/to/note2.md']
};

const python = spawn('python', ['graphiti_bridge/sync.py']);
python.stdin.write(JSON.stringify(config));
python.stdin.end();
```

## Configuration

The bridge accepts configuration via JSON on stdin with the following structure:

```json
{
    "llmProvider": "openai",
    "llmApiKey": "sk-...",
    "llmModel": "gpt-4o",
    "llmSmallModel": "gpt-4o-mini",
    "embedderProvider": "openai",
    "embedderApiKey": "sk-...",
    "embeddingModel": "text-embedding-3-small",
    "databaseType": "neo4j",
    "databaseUrl": "bolt://localhost:7687",
    "databaseUsername": "neo4j",
    "databasePassword": "password",
    "databaseName": "neo4j",
    "modelsPath": "/path/to/generated/models",
    "notes": ["note1.md", "note2.md"]
}
```

## Error Handling

The bridge returns JSON responses indicating success or failure:

```json
// Success
{"status": "success", "processed": 5, "skipped": 0}

// Error
{"status": "error", "message": "Database connection failed", "details": "..."}
```

## Development

### Testing Installation

```bash
# Test with minimal config
echo '{}' | python graphiti_bridge/install.py

# Test with specific providers
echo '{"llmProvider": "anthropic", "databaseType": "falkordb"}' | python graphiti_bridge/install.py
```

### Debugging

Set environment variable for verbose output:

```bash
export GRAPHITI_BRIDGE_DEBUG=1
python graphiti_bridge/sync.py
```

## Community Plugin Considerations

### User-Friendly Features

1. **Auto-detection**: Automatically detects Python and package managers
2. **Clear messaging**: Provides helpful progress and error messages
3. **Graceful fallbacks**: Handles missing dependencies elegantly
4. **OS compatibility**: Works on Windows, macOS, and Linux

### Error Recovery

- Clear error messages with actionable guidance
- Automatic retry logic for transient failures
- Graceful handling of missing Python installations
- Helpful troubleshooting information

## Troubleshooting

### Common Issues

1. **Python not found**
   - Install Python 3.10+ from python.org
   - Ensure Python is in your PATH

2. **Package installation fails**
   - Check internet connection
   - Try running as administrator (Windows)
   - Clear pip cache: `pip cache purge`

3. **Import errors**
   - Verify installation completed successfully
   - Check Python version compatibility
   - Ensure virtual environment is activated if used

### Getting Help

1. Check the plugin's debug logs
2. Run installation with verbose output
3. Report issues with full error messages and system information

## License

This component is part of the Obsidian Graphiti Plugin and follows the same license terms.