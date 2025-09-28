"""
Remote RPC Bridge for MCP inter-process communication.

This module provides an HTTP client adapter that implements the same server-like
interface as WebSocketServer, allowing FileTools to work with either local or
remote MCP processes transparently.
"""

import aiohttp
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class RemoteRPCBridge:
    """HTTP client adapter that mirrors WebSocketServer interface for FileTools."""

    def __init__(self, base_url: str, auth_token: str):
        # @@vessel-protocol:Bifrost governs:integration context:HTTP RPC bridge for inter-process MCP communication
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with proper headers."""
        if self._session is None or self._session.closed:
            headers = {}
            if self.auth_token:
                headers['Authorization'] = f'Bearer {self.auth_token}'

            timeout = aiohttp.ClientTimeout(total=30)  # Default timeout
            self._session = aiohttp.ClientSession(
                headers=headers, timeout=timeout)
        return self._session

    async def close(self):
        """Clean up HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def request_file_operation(self, vault_id: str, operation: str, params: Dict[str, Any], timeout: float = 20.0) -> Optional[Dict[str, Any]]:
        """Request file operation via HTTP RPC to remote MCP process."""
        try:
            session = await self._get_session()

            # Prepare RPC request
            rpc_data = {
                'operation': operation,
                'vaultId': vault_id,
                'params': params,
                'timeoutMs': int(timeout * 1000)
            }

                f"[RPC-BRIDGE] Sending {operation} to vault {vault_id}")

            # Send HTTP POST to /rpc endpoint
            async with session.post(f'{self.base_url}/rpc', json=rpc_data) as response:
                if response.status == 401:
                    logger.error(
                        "[RPC-BRIDGE] Authentication failed - token mismatch")
                    return {
                        'success': False,
                        'error': 'Authentication failed - token mismatch'
                    }
                elif response.status == 404:
                    logger.warning(
                        f"[RPC-BRIDGE] No connected vault found: {vault_id}")
                    return None
                elif response.status == 504:
                    logger.error(
                        f"[RPC-BRIDGE] Request timeout for {operation}")
                    return {
                        'success': False,
                        'error': f'Request timeout after {timeout}s'
                    }
                elif response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"[RPC-BRIDGE] RPC failed with status {response.status}: {error_text}")
                    return {
                        'success': False,
                        'error': f'RPC failed with status {response.status}'
                    }

                # Parse successful response
                result = await response.json()

                # Transform response to match WebSocketServer format
                return {
                    'success': result.get('success', False),
                    'payload': result.get('result'),
                    'error': result.get('error'),
                    'timestamp': result.get('timestamp')
                }

        except aiohttp.ClientConnectorError:
            logger.error(
                "[RPC-BRIDGE] Connection refused - no MCP server running")
            return {
                'success': False,
                'error': 'Connection refused - no MCP server running'
            }
        except asyncio.TimeoutError:
            logger.error(f"[RPC-BRIDGE] HTTP timeout for {operation}")
            return {
                'success': False,
                'error': f'HTTP timeout after {timeout}s'
            }
        except Exception as e:
            logger.error(f"[RPC-BRIDGE] Unexpected error in {operation}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_connected_vaults(self) -> List[str]:
        """Get list of connected vaults from remote server."""
        try:
            health_info = await self._get_health_info()
            if health_info:
                return health_info.get('connectedVaults', [])
            return []
        except Exception as e:
            logger.error(f"[RPC-BRIDGE] Failed to get connected vaults: {e}")
            return []

    async def get_active_vault(self) -> Optional[str]:
        """Get currently active vault from remote server."""
        try:
            health_info = await self._get_health_info()
            if health_info:
                return health_info.get('activeVault')
            return None
        except Exception as e:
            logger.error(f"[RPC-BRIDGE] Failed to get active vault: {e}")
            return None

    async def get_all_vault_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all vaults - limited in RPC bridge."""
        # Note: Remote server /health doesn't provide detailed vault info
        # This is a simplified implementation for compatibility
        try:
            vaults = await self.get_connected_vaults()
            active_vault = await self.get_active_vault()

            result = {}
            for vault_id in vaults:
                result[vault_id] = {
                    'vaultId': vault_id,
                    'isActive': vault_id == active_vault
                }
            return result
        except Exception as e:
            logger.error(f"[RPC-BRIDGE] Failed to get vault info: {e}")
            return {}

    async def _get_health_info(self) -> Optional[Dict[str, Any]]:
        """Get health info from remote server."""
        try:
            session = await self._get_session()

            async with session.get(f'{self.base_url}/health') as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    logger.error(
                        "[RPC-BRIDGE] Health check authentication failed")
                    return None
                else:
                    logger.error(
                        f"[RPC-BRIDGE] Health check failed with status {response.status}")
                    return None

        except aiohttp.ClientConnectorError:
            logger.error("[RPC-BRIDGE] Connection refused during health check")
            return None
        except Exception as e:
            logger.error(f"[RPC-BRIDGE] Health check error: {e}")
            return None


async def create_remote_rpc_bridge(host: str, port: int, auth_token: str) -> RemoteRPCBridge:
    """Create and validate a remote RPC bridge connection."""
    # @@vessel-protocol:Heimdall governs:validation context:Remote RPC bridge connection validation
    base_url = f'http://{host}:{port}'
    bridge = RemoteRPCBridge(base_url, auth_token)

    # Test connection with health check
    health_info = await bridge._get_health_info()
    if health_info is None:
        await bridge.close()
        raise ConnectionError(f"Cannot connect to MCP server at {base_url}")

    logger.info(f"[RPC-BRIDGE] Connected to remote MCP server at {base_url}")
    return bridge
