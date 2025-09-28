# Obsidian Graphiti MCP Server

A Model Context Protocol (MCP) server that provides seamless integration between Claude Desktop and Obsidian's knowledge graph via a shared WebSocket architecture.

## Architecture

### Shared WebSocket Server Design

This MCP server uses a **shared WebSocket server architecture** to eliminate port conflicts when multiple MCP clients (Claude Desktop, AnythingLLM, LobeHub, etc.) access the same Obsidian vault simultaneously.

```
Multiple MCP Clients → First MCP Process (WebSocket Server) → Obsidian Plugin → Knowledge Graph
                    ↗ Second MCP Process (RPC Client) ↗
                    ↗ Third MCP Process (RPC Client) ↗
```

**Key Features:**

- **First-process ownership**: The first MCP process to start becomes the WebSocket server host
- **Automatic fallback**: Subsequent MCP processes automatically become RPC clients
- **Health monitoring**: HTTP `/health` endpoint for connection status monitoring
- **Remote procedure calls**: HTTP `/rpc` endpoint for file operations via RPC clients
- **Obsidian auto-launch**: Automatically launches Obsidian if not running
- **Multi-vault support**: Each vault has its own shared server instance

### Components

1. **WebSocket Server** ([`websocket_server.py`](websocket_server.py))

   - Hosts WebSocket connection to Obsidian plugin
   - Provides HTTP endpoints (`/health`, `/rpc`) on localhost
   - Bearer token authentication for security
   - Automatic connection management and cleanup

2. **MCP Server** ([`megamem_mcp_server.py`](megamem_mcp_server.py))

   - Main MCP server implementation with file tools
   - Server/client mode detection via health endpoint probing
   - Obsidian auto-launch functionality
   - Comprehensive ASCII-only logging for Windows compatibility

3. **RPC Bridge** ([`remote_rpc_bridge.py`](remote_rpc_bridge.py))

   - Lightweight adapter for RPC client mode
   - Maps file operations to HTTP `/rpc` calls
   - Transparent fallback when WebSocket server is unavailable

4. **File Tools** ([`file_tools.py`](file_tools.py))
   - File system operations for knowledge graph management
   - Supports both direct WebSocket and RPC bridge connections
   - Unified API regardless of connection type

## Setup

### 1. Install Dependencies

```bash
cd mcp-server
pip install -r requirements.txt
```

### 2. Configure Claude Desktop

Add the following to your Claude Desktop configuration file:

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "megamem": {
      "command": "python",
      "args": [
        "/path/to/obsidian-graphiti-mcp/mcp-server/megamem_mcp_server.py"
      ],
      "env": {
        "OBSIDIAN_CONFIG_PATH": "/path/to/your/vault/.obsidian/plugins/megamem-mcp/data.json"
      }
    }
  }
}
```

### 3. Configure Additional MCP Clients (Optional)

For multiple MCP clients, **all clients must use the same `OBSIDIAN_CONFIG_PATH`** to ensure they share the same `wsPort` and `wsAuthToken` for authentication.

**AnythingLLM Example:**

```json
{
  "mcpServers": {
    "megamem": {
      "command": "python",
      "args": [
        "/path/to/obsidian-graphiti-mcp/mcp-server/megamem_mcp_server.py"
      ],
      "env": {
        "OBSIDIAN_CONFIG_PATH": "/path/to/your/vault/.obsidian/plugins/megamem-mcp/data.json"
      }
    }
  }
}
```

### 4. Restart MCP Clients

After updating configurations, restart all MCP clients to load the server.

## Key Features

### Shared Server Architecture

- **No port conflicts**: Multiple MCP clients can access the same vault simultaneously
- **Automatic server management**: First process hosts, others become clients automatically
- **Graceful failover**: When server process exits, a new client can become the server
- **Real-time monitoring**: Plugin UI shows live connection status

### Obsidian Integration

- **Auto-launch**: Automatically launches Obsidian with default vault if not running
- **Multi-vault support**: Each vault gets its own shared server instance
- **Live connection monitoring**: Plugin settings show real-time connection status
- **Bearer token security**: Secure localhost-only authentication

### File Operations

- **Read/write files**: Full file system access within vault
- **Directory operations**: Create, list, and manage directories
- **Content search**: Find files and content within the vault
- **Metadata handling**: Access and modify file metadata

## Usage

Once configured, you get full access to your Obsidian vault from Claude Desktop and other MCP clients:

### File Operations

```
Create a new note called "Meeting Notes" with the following content: "Today we discussed..."
```

```
Read the contents of my "Daily Notes" file
```

```
Search for all files containing "project status"
```

### Directory Management

```
List all files in my "Projects" folder
```

```
Create a new folder called "Archive" in my vault
```

## Configuration

The server reads configuration from your Obsidian plugin's `data.json` file, including:

- **WebSocket settings**: `wsPort` and `wsAuthToken` for shared server
- **Default vault**: `defaultVault` for auto-launch functionality
- **Plugin settings**: Various plugin configuration options

## Server Lifecycle

### Startup Process

1. **Read configuration** from `OBSIDIAN_CONFIG_PATH`
2. **Probe health endpoint** to detect existing server
3. **Start WebSocket server** if none exists (first process)
4. **Fallback to RPC client** if server already running (subsequent processes)
5. **Launch Obsidian** if not running and auto-launch enabled
6. **Initialize file tools** with appropriate connection type

### Connection Types

- **Direct WebSocket**: First MCP process connects directly to Obsidian
- **RPC Client**: Subsequent processes route through shared WebSocket server
- **Transparent operation**: File tools work identically in both modes

## Operational Requirements

### Critical Configuration Notes

- **Shared configuration**: All MCP clients must use the same `OBSIDIAN_CONFIG_PATH`
- **Matching tokens**: `wsPort` and `wsAuthToken` must match across all clients
- **Localhost binding**: All connections are localhost-only for security
- **Windows compatibility**: All logging uses ASCII-only characters

### Multi-Client Setup

1. Configure the first MCP client (e.g., Claude Desktop)
2. Use **identical** `OBSIDIAN_CONFIG_PATH` for additional clients
3. Start clients in any order - automatic server/client detection
4. Monitor connection status in plugin settings

## Troubleshooting

### Common Issues

1. **"Connection refused"**:

   - Ensure Obsidian plugin is enabled and configured
   - Check that WebSocket port is not blocked
   - Verify `wsAuthToken` matches in plugin and MCP config

2. **"Authentication failed (401)"**:

   - Verify all MCP clients use the same `OBSIDIAN_CONFIG_PATH`
   - Check that `wsAuthToken` matches between plugin and MCP server
   - Restart all MCP clients after configuration changes

3. **"Port already in use"**:
   - This is expected behavior - indicates automatic RPC client mode
   - Check plugin UI for current connection status
   - Verify multiple processes can connect simultaneously

### Debug Mode

Enable detailed logging by adding to the MCP client configuration:

```json
"env": {
  "OBSIDIAN_CONFIG_PATH": "/path/to/data.json",
  "GRAPHITI_DEBUG": "true"
}
```

### Health Monitoring

Check server health manually:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://127.0.0.1:8765/health
```

Response includes:

- Server status and uptime
- Connected vault information
- Active client connections

## Testing

### Manual Server Test

```bash
# Set environment variable
export OBSIDIAN_CONFIG_PATH="/path/to/your/vault/.obsidian/plugins/megamem-mcp/data.json"

# Run the server
cd mcp-server
python megamem_mcp_server.py
```

### Multi-Client Test

1. Start first MCP client (becomes WebSocket server)
2. Start second MCP client (becomes RPC client)
3. Verify both can perform file operations
4. Check plugin UI shows multiple connections

### Failover Test

1. Start two MCP clients
2. Terminate the WebSocket server process
3. Start a new MCP client
4. Verify it becomes the new WebSocket server

## Architecture Benefits

- **Eliminates port conflicts**: No more "address already in use" errors
- **Seamless scaling**: Add MCP clients without configuration changes
- **Fault tolerance**: Automatic failover when server process exits
- **Resource efficiency**: Single WebSocket connection to Obsidian
- **Security**: Localhost-only with Bearer token authentication
- **Monitoring**: Real-time connection status in plugin UI

## Next Steps

- **Enhanced monitoring**: Additional health metrics and alerting
- **Connection pooling**: Optimize performance for high-frequency operations
- **Multi-vault management**: Simplified setup for users with multiple vaults
- **Integration testing**: Automated test suite for multi-client scenarios

The shared WebSocket architecture ensures reliable, scalable access to your Obsidian knowledge graph from multiple MCP clients simultaneously.
