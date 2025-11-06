"""
WebSocket server for the MCP server to accept connections from Obsidian plugins.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Set, List
import uuid

import aiohttp
from aiohttp import web
import aiohttp_cors

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket server that Obsidian plugins connect to."""

    def __init__(self, port: int = 41484, auth_token: str = ""):
        self._port = port
        self.auth_token = auth_token
        self.app = web.Application()
        self.clients: Dict[str, web.WebSocketResponse] = {}
        self.vault_info: Dict[str, Dict[str, Any]] = {}
        self.client_to_vault: Dict[str, str] = {}  # Map client_id to vault_id
        self.vault_to_client: Dict[str, str] = {}  # Map vault_id to client_id
        # Track pending file operation requests
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.active_vault_id: Optional[str] = None
        self.setup_routes()
        self.runner = None

    def setup_routes(self):
        """Setup HTTP and WebSocket routes."""
        # Support both /ws endpoint and root path for backward compatibility
        self.app.router.add_get('/ws', self.websocket_handler)
        # Add root path support
        self.app.router.add_get('/', self.websocket_handler)
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_post('/rpc', self.rpc_handler)

        # Configure CORS for browser-based connections
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })

        for route in list(self.app.router.routes()):
            cors.add(route)

        # SECURITY: enforce localhost-only binding by rejecting requests from non-local hosts early
        @web.middleware
        async def localhost_only_middleware(request, handler):
            peername = request.transport.get_extra_info('peername')
            # peername may be None or (host, port)
            host = None
            if peername:
                try:
                    host = peername[0]
                except Exception:
                    host = None
            # Allow if host is localhost variants or None (internal)
            if host not in (None, '127.0.0.1', '::1', 'localhost'):
                return web.json_response({'error': 'Forbidden - localhost only'}, status=403)
            return await handler(request)
        
        self.app.middlewares.append(localhost_only_middleware)

    async def health_check(self, request):
        """Enhanced health check endpoint with authentication."""
        # @@vessel-protocol:Heimdall governs:validation context:Authenticated health endpoint for MCP process discovery

        # Check authentication - support both Bearer header and query token
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            token = request.query.get('token', '')

        if self.auth_token and token != self.auth_token:
            logger.warning(
                "[HEALTH] Authentication failed - invalid or missing token")
            return web.json_response({'error': 'Unauthorized'}, status=401)

        # Return comprehensive server status for MCP discovery
        connected_vaults = list(self.vault_to_client.keys())
        client_ids = list(self.clients.keys())

        return web.json_response({
            'status': 'healthy',
            'clients': len(self.clients),
            'clientIds': client_ids,
            'connectedVaults': connected_vaults,
            'activeVault': self.active_vault_id,
            'timestamp': str(asyncio.get_event_loop().time())
        })

    async def rpc_handler(self, request):
        """HTTP RPC endpoint for inter-process MCP communication."""
        # @@vessel-protocol:Bragi governs:integration context:HTTP RPC bridge for MCP file operations

        # Check authentication
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            token = request.query.get('token', '')

        if self.auth_token and token != self.auth_token:
            logger.warning(
                "[RPC] Authentication failed - invalid or missing token")
            return web.json_response({'error': 'Unauthorized'}, status=401)

        # Enforce payload size limit (~2MB)
        content_length = request.headers.get('Content-Length')
        if content_length and int(content_length) > 2 * 1024 * 1024:
            logger.warning(f"[RPC] Payload too large: {content_length} bytes")
            return web.json_response({'error': 'Payload too large'}, status=413)

        operation = None  # Initialize to prevent unbound variable
        try:
            # Parse request body
            data = await request.json()
            operation = data.get('operation')
            vault_id = data.get('vaultId')
            params = data.get('params', {})
            timeout_ms = data.get('timeoutMs')

            if not operation:
                return web.json_response({'error': 'Missing operation'}, status=400)

            # Set timeout (default 20s, max from request)
            timeout = min(timeout_ms / 1000.0 if timeout_ms else 20.0, 30.0)

            logger.debug(
                f"[RPC] Executing {operation} on vault {vault_id} with timeout {timeout}s")

            # Route to existing WebSocket request handler
            result = await self.request_file_operation(vault_id, operation, params, timeout)

            if result is None:
                return web.json_response({
                    'success': False,
                    'error': f'No connected vault found: {vault_id}'
                }, status=404)

            return web.json_response({
                'success': result.get('success', False),
                'result': result.get('payload'),
                'error': result.get('error'),
                'timestamp': result.get('timestamp')
            })

        except asyncio.TimeoutError:
            logger.error(f"[RPC] Request timeout for {operation or 'unknown'}")
            return web.json_response({
                'success': False,
                'error': 'Request timeout'
            }, status=504)
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"[RPC] Request failed: {e}")
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def websocket_handler(self, request):
        """Handle WebSocket connections from Obsidian plugins."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Authenticate if token is set - support both header and query param
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            # Fallback to query parameter for backward compatibility with Obsidian plugin
            token = request.query.get('token', '')

        # Validate authentication without logging sensitive tokens
        auth_required = bool(self.auth_token)
        token_valid = not auth_required or (token == self.auth_token)

        logger.info(f"[AUTH] Authentication required: {auth_required}")
        logger.info(
            f"[AUTH] Token validation result: {'PASS' if token_valid else 'FAIL'}")

        if auth_required and not token_valid:
            logger.warning(
                "[AUTH] Authentication failed - invalid or missing WebSocket token")
            await ws.close(code=4001, message=b'Authentication failed')
            return ws

        # Generate client ID
        client_id = str(uuid.uuid4())
        self.clients[client_id] = ws

        logger.info(f"New WebSocket client connected: {client_id}")

        # Send welcome message
        welcome_msg = {
            'type': 'connected',
            'clientId': client_id,
            'timestamp': str(asyncio.get_event_loop().time())
        }
        logger.info(f"[WS] Sending welcome message to client {client_id}")
        await ws.send_json(welcome_msg)

        try:
            async for msg in ws:
                try:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.debug(
                            f"[WS] Received message from client {client_id}")
                        try:
                            data = json.loads(msg.data)
                            logger.debug(
                                f"[WS] Processing message type: {data.get('type', 'unknown')}")
                            await self.handle_message(client_id, data)
                        except json.JSONDecodeError as e:
                            logger.error(
                                f"[WS] JSON decode error from client {client_id}: {e}")
                            await ws.send_json({
                                'type': 'error',
                                'error': 'Invalid JSON'
                            })
                        except Exception as msg_error:
                            logger.error(
                                f"[WS] Message handling error for client {client_id}: {msg_error}")
                            try:
                                await ws.send_json({
                                    'type': 'error',
                                    'error': 'Internal error processing message'
                                })
                            except:
                                pass  # Client may have disconnected
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f'WebSocket error: {ws.exception()}')
                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        logger.info(
                            f"[WS] WebSocket close message from client {client_id}")
                    else:
                        logger.debug(
                            f"[WS] Unknown message type from client {client_id}: {msg.type}")
                except Exception as loop_error:
                    logger.error(
                        f"[WS] Message loop error for client {client_id}: {loop_error}")
                    break  # Exit the message loop but continue cleanup

        except Exception as e:
            logger.error(
                f"[ERROR] WebSocket handler error for client {client_id}: {e}")
        finally:
            # Clean up on disconnect
            if client_id in self.clients:
                del self.clients[client_id]
            if client_id in self.vault_info:
                del self.vault_info[client_id]

            # Clean up vault mappings
            if client_id in self.client_to_vault:
                vault_id = self.client_to_vault[client_id]
                del self.client_to_vault[client_id]
                if vault_id in self.vault_to_client:
                    del self.vault_to_client[vault_id]

                # If this was the active vault, switch to another connected vault
                if self.active_vault_id == vault_id:
                    connected_vaults = list(self.vault_to_client.keys())
                    self.active_vault_id = connected_vaults[0] if connected_vaults else None
                    if self.active_vault_id:
                        logger.info(
                            f"[INFO] Switched active vault to: {self.active_vault_id}")
                    else:
                        logger.info(
                            "[INFO] No active vault - all vaults disconnected")

            # Cancel any pending requests for this client
            requests_to_cancel = []
            for request_id, future in self.pending_requests.items():
                if not future.done():
                    requests_to_cancel.append(request_id)

            for request_id in requests_to_cancel:
                future = self.pending_requests.pop(request_id, None)
                if future and not future.done():
                    future.cancel()
                    logger.debug(
                        f"[INFO] Cancelled pending request {request_id} for disconnected client")

            logger.info(f"[INFO] Client disconnected: {client_id}")

        return ws

    async def handle_message(self, client_id: str, message: Dict[str, Any]):
        """Handle incoming messages from Obsidian plugins."""
        msg_type = message.get('type')
        logger.debug(
            f"[WS] Processing message type '{msg_type}' from client {client_id}")

        if msg_type == 'register':
            # Store vault information
            payload = message.get('payload', {})
            self.vault_info[client_id] = payload

            # Extract vault identification
            vault_name = payload.get('vaultName', '')
            vault_path = payload.get('vaultPath', '')
            vault_id = vault_name or f"vault_{client_id}"

            # Map client to vault
            self.client_to_vault[client_id] = vault_id
            self.vault_to_client[vault_id] = client_id

            # Set as active vault if none set
            if not self.active_vault_id:
                self.active_vault_id = vault_id
                logger.info(f"[INFO] Set active vault to: {vault_id}")

            logger.info(
                f"[INFO] Registered vault '{vault_id}' for client {client_id}")

            await self.send_to_client(client_id, {
                'type': 'registered',
                'success': True,
                'vaultId': vault_id,
                'isActive': vault_id == self.active_vault_id
            })

        elif msg_type == 'pong':
            # Handle pong response
            pass

        elif msg_type and 'response' in msg_type and 'id' in message:
            # Handle response messages from file operations
            request_id = message.get('id')
            if request_id and request_id in self.pending_requests:
                future = self.pending_requests.pop(request_id)
                if not future.done():
                    # Resolve the future with the complete response
                    response_data = {
                        'success': message.get('success', False),
                        'payload': message.get('payload', {}),
                        'error': message.get('error'),
                        'timestamp': message.get('timestamp')
                    }
                    future.set_result(response_data)
                    logger.debug(
                        f"[INFO] Resolved pending request {request_id}")
            else:
                logger.warning(
                    f"[WARNING] Received response for unknown request: {request_id}")

        else:
            # Forward to appropriate handler
            # This is where you'd integrate with MCP tools
            await self.send_to_client(client_id, {
                'type': 'error',
                'error': f'Unknown message type: {msg_type}'
            })

    async def send_to_client(self, client_id: str, message: Dict[str, Any]):
        """Send a message to a specific client."""
        if client_id in self.clients:
            ws = self.clients[client_id]
            try:
                await ws.send_json(message)
            except ConnectionError:
                logger.error(f"Failed to send to client {client_id}")

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """Broadcast a message to all connected clients."""
        for client_id, ws in self.clients.items():
            if client_id != exclude:
                try:
                    await ws.send_json(message)
                except ConnectionError:
                    logger.error(f"Failed to broadcast to client {client_id}")

    async def request_file_operation(self, vault_id: str, operation: str, params: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Request a file operation from a specific vault with proper async correlation."""
        # Find client for vault using improved lookup
        client_id = self.vault_to_client.get(vault_id)

        # Fallback to legacy lookup for backward compatibility
        if not client_id:
            for cid, info in self.vault_info.items():
                if info.get('vaultName') == vault_id or cid == vault_id:
                    client_id = cid
                    break

        if not client_id or client_id not in self.clients:
            logger.warning(
                f"[WARNING] No connected client found for vault: {vault_id}")
            return None

        # Create request with ID
        request_id = str(uuid.uuid4())
        request = {
            'id': request_id,
            'type': operation,
            'payload': params
        }

        # Create future for response tracking
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            # Send request to client
            await self.send_to_client(client_id, request)
            logger.debug(
                f"[INFO] Sent file operation request {request_id} to vault {vault_id}")

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            logger.debug(f"[INFO] Received response for request {request_id}")
            return response

        except asyncio.TimeoutError:
            logger.error(
                f"[ERROR] Timeout waiting for response to request {request_id} from vault {vault_id}")
            return {
                'success': False,
                'error': f'Request timeout after {timeout}s',
                'requestId': request_id
            }
        except Exception as e:
            logger.error(
                f"[ERROR] File operation request {request_id} failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'requestId': request_id
            }
        finally:
            # Clean up pending request
            self.pending_requests.pop(request_id, None)

    async def start(self):
        """Start the WebSocket server"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # This will raise OSError if port is in use - LET IT BUBBLE UP
        site = web.TCPSite(self.runner, 'localhost', self._port)
        await site.start()  # Don't catch this error here!

        logger.info(f"[SUCCESS] WebSocket server started on port {self._port}")

        # Don't block here - let the server run in the background
        # The aiohttp server will keep running on its own

    async def stop(self):
        """Stop the WebSocket server."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("[INFO] WebSocket server stopped")

    def get_active_vault(self) -> Optional[str]:
        """Get the currently active vault ID."""
        return self.active_vault_id

    def set_active_vault(self, vault_id: str) -> bool:
        """Set the active vault ID."""
        if vault_id in self.vault_to_client:
            self.active_vault_id = vault_id
            logger.info(f"[INFO] Active vault set to: {vault_id}")
            return True
        else:
            logger.warning(
                f"[WARNING] Cannot set active vault - vault not connected: {vault_id}")
            return False

    def get_connected_vaults(self) -> List[str]:
        """Get list of all connected vault IDs."""
        return list(self.vault_to_client.keys())

    def get_vault_info(self, vault_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific vault."""
        client_id = self.vault_to_client.get(vault_id)
        if client_id and client_id in self.vault_info:
            info = self.vault_info[client_id].copy()
            info['vaultId'] = vault_id
            info['clientId'] = client_id
            info['isActive'] = vault_id == self.active_vault_id
            return info
        return None

    def get_all_vault_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all connected vaults."""
        result = {}
        for vault_id in self.vault_to_client.keys():
            info = self.get_vault_info(vault_id)
            if info:
                result[vault_id] = info
        return result

    @property
    def port(self):
        return self._port


# Global server instance
_server: Optional[WebSocketServer] = None


async def start_websocket_server(port: int = 41484, auth_token: str = "") -> WebSocketServer:
    """Start the global WebSocket server."""
    global _server
    if _server is None:
        _server = WebSocketServer(port, auth_token)
        await _server.start()
    return _server


def get_websocket_server() -> Optional[WebSocketServer]:
    """Get the global WebSocket server instance."""
    return _server


def resolve_vault_id(vault_id: Optional[str] = None) -> str:
    """
    Resolve vault ID with dynamic fallback logic.

    Args:
        vault_id: Explicit vault ID if provided

    Returns:
        Resolved vault ID, with intelligent fallback to active vault or "default"
    """
    if vault_id:
        logger.debug(f"Using explicit vault ID: {vault_id}")
        return vault_id

    # Try to get active vault from WebSocket server
    try:
        server = get_websocket_server()
        if server:
            active_vault = server.get_active_vault()
            if active_vault:
                logger.debug(f"Using active vault from server: {active_vault}")
                return active_vault
    except Exception as e:
        logger.warning(f"Failed to get active vault from server: {e}")

    # Fallback to default
    logger.debug("Using fallback vault ID: default")
    return "default"
