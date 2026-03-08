#!/usr/bin/env python3
"""
Python Daemon — warm-start optimization for faster consecutive note syncs.
Protocol: JSON only on stdout. All diagnostics via logging to stderr.
"""

import json
import sys
import os
import time
import signal
import logging
import asyncio
import warnings
from typing import Dict, Any, Optional
from contextlib import contextmanager

# Ensure local modules are importable (config.py, sync.py, utils.py live beside this file)
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Performance timing configuration - controlled by UI setting via environment variable
ENABLE_PERF_TIMING = os.getenv(
    'GRAPHITI_LOG_PERFORMANCE', 'false').lower() == 'true'
PERF_TIMING_PREFIX = "[PERF-TIMING]"

# Global timing storage for daemon startup analysis
_timing_data = {}
_daemon_start_time = time.perf_counter()

# @purpose: Performance timing utilities for daemon startup bottleneck analysis
# @depends: time.perf_counter, logging, ENABLE_PERF_TIMING
# @results: Structured timing data logged to stderr for optimization analysis


@contextmanager
def time_operation(operation_name: str, category: str = "general"):
    """Context manager for timing operations with structured logging"""
    if not ENABLE_PERF_TIMING:
        yield
        return

    start_time = time.perf_counter()
    start_offset = start_time - _daemon_start_time

    try:
        yield
    finally:
        end_time = time.perf_counter()
        duration = end_time - start_time
        end_offset = end_time - _daemon_start_time

        # Store timing data
        if category not in _timing_data:
            _timing_data[category] = []

        timing_entry = {
            'operation': operation_name,
            'duration_ms': round(duration * 1000, 2),
            'start_offset_ms': round(start_offset * 1000, 2),
            'end_offset_ms': round(end_offset * 1000, 2)
        }
        _timing_data[category].append(timing_entry)

        # Log timing data to stderr with structured format
        # Handle case where logger might not be initialized yet during early imports
        try:
            logger.debug(
                f"{PERF_TIMING_PREFIX} {category}.{operation_name}: {duration*1000:.2f}ms (offset: {start_offset*1000:.2f}ms)")
        except NameError:
            # Logger not yet defined, use print to stderr
            print(f"{PERF_TIMING_PREFIX} {category}.{operation_name}: {duration*1000:.2f}ms (offset: {start_offset*1000:.2f}ms)", file=sys.stderr)


def log_timing_summary():
    """Log comprehensive timing summary for daemon startup analysis"""
    if not ENABLE_PERF_TIMING or not _timing_data:
        return

    total_time = time.perf_counter() - _daemon_start_time
    # Handle case where logger might not be initialized yet
    try:
        logger.debug(
            f"{PERF_TIMING_PREFIX} SUMMARY: Total daemon startup: {total_time*1000:.2f}ms")

        for category, operations in _timing_data.items():
            category_total = sum(op['duration_ms'] for op in operations)
            logger.debug(
                f"{PERF_TIMING_PREFIX} CATEGORY {category}: {category_total:.2f}ms total")

            for op in operations:
                percentage = (op['duration_ms'] / (total_time * 1000)) * 100
                logger.debug(
                    f"{PERF_TIMING_PREFIX}   {op['operation']}: {op['duration_ms']:.2f}ms ({percentage:.1f}%)")
    except NameError:
        # Logger not yet defined, use print to stderr
        print(f"{PERF_TIMING_PREFIX} SUMMARY: Total daemon startup: {total_time*1000:.2f}ms", file=sys.stderr)

        for category, operations in _timing_data.items():
            category_total = sum(op['duration_ms'] for op in operations)
            print(
                f"{PERF_TIMING_PREFIX} CATEGORY {category}: {category_total:.2f}ms total", file=sys.stderr)

            for op in operations:
                percentage = (op['duration_ms'] / (total_time * 1000)) * 100
                print(
                    f"{PERF_TIMING_PREFIX}   {op['operation']}: {op['duration_ms']:.2f}ms ({percentage:.1f}%)", file=sys.stderr)


# Import config helpers (conforms with sync.py usage)
with time_operation("config_import", "imports"):
    from .config import BridgeConfig, setup_environment_variables

# Import sync module to reuse its internal pipeline functions (no stdout contamination)
# Note: This will trigger granular import timing from sync.py when GRAPHITI_LOG_PERFORMANCE=true
with time_operation("sync_module_import", "imports"):
    from . import sync  # graphiti_bridge/sync.py

# Minimal logger per Day27.01_Python-Logging-Refactor (stderr only)
logger = logging.getLogger("graphiti_bridge.sync_daemon")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Suppress noisy HF/Transformers warnings to keep protocol-clean logs
# - FutureWarning for TRANSFORMERS_CACHE deprecation
# - Reduce general Transformers logging to errors only
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
warnings.filterwarnings(
    "ignore",
    message="Using `TRANSFORMERS_CACHE` is deprecated",
    category=FutureWarning
)


class SyncDaemon:
    def __init__(self):
        self.running = True

    def _build_result_error(self, message: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "message": message
        }

    async def _run_single_note(self, cfg: BridgeConfig) -> Dict[str, Any]:
        """
        Reuse sync.py internal pipeline without touching stdout:
        - initialize_global_loader (for custom ontology)
        - initialize_graphiti
        - process_note
        - close drivers
        """
        try:
            # Initialize custom ontology if enabled (matches sync.py main() logic)
            logger.debug(f"[DAEMON] Custom ontology check: use_custom_ontology={cfg.use_custom_ontology}, vault_path={cfg.vault_path}")
            if cfg.use_custom_ontology and cfg.vault_path:
                logger.debug("[DAEMON] Initializing custom ontology loader...")
                from .models import initialize_global_loader
                if not initialize_global_loader(cfg.vault_path):
                    logger.warning("[DAEMON] Failed to initialize custom ontology loader")
                else:
                    logger.debug("[DAEMON] Custom ontology loader initialized successfully")
                    
                    # Verify global loader initialization with lazy loading
                    from .models import get_entity_types
                    entity_types = get_entity_types()
                    logger.debug(f"[DAEMON] Daemon initialized with entity types: {entity_types}")
            else:
                logger.debug("[DAEMON] Skipping custom ontology initialization (disabled or no vault path)")
            
            graphiti = await sync.initialize_graphiti(cfg, cfg.debug)
            if not graphiti:
                return self._build_result_error("Failed to initialize Graphiti")

            # process a single note (daemon only handles single-note requests)
            if not cfg.notes or len(cfg.notes) != 1:
                return self._build_result_error(f"Expected exactly 1 note, got {len(cfg.notes) if cfg.notes else 0}")

            # Use sync logger namespace expected by process_note
            py_logger = logging.getLogger("graphiti_bridge.sync")

            try:
                result = await sync.process_note(cfg.notes[0], graphiti, py_logger, cfg)
            finally:
                # Ensure connections are closed
                try:
                    if hasattr(graphiti, 'close'):
                        await graphiti.close()
                except Exception:
                    pass

            if result is None:
                return self._build_result_error("No result generated")
            # result is already a compact dict from sync.process_note
            return result
        except Exception as e:
            logger.error(f"[DAEMON] Sync pipeline error: {e}")
            return self._build_result_error(str(e))

    def run_sync_with_config(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert incoming dict to BridgeConfig and execute the sync pipeline wholly in-process.
        """
        # @purpose: Set performance timing from UI setting (environment variable set at startup, config dict as fallback) @depends: config_dict @results: Performance timing controlled by logPerformance setting
        global ENABLE_PERF_TIMING

        # DIAGNOSTIC: Log current timing state and config value
        config_log_perf = config_dict.get('logPerformance', False)
        logger.debug(
            f"[DIAGNOSTIC] Performance timing state - Current: {ENABLE_PERF_TIMING}, Config: {config_log_perf}")

        # FIX: Always update ENABLE_PERF_TIMING from config to respect setting changes
        # Environment variable only takes precedence on first daemon startup
        env_timing = os.getenv('GRAPHITI_LOG_PERFORMANCE',
                               'false').lower() == 'true'
        if env_timing:
            # Environment variable overrides config (daemon startup setting)
            ENABLE_PERF_TIMING = True
            logger.debug(
                f"[DIAGNOSTIC] Environment variable override - ENABLE_PERF_TIMING: {ENABLE_PERF_TIMING}")
        else:
            # Use config value - this allows runtime setting changes to work
            ENABLE_PERF_TIMING = config_log_perf
            logger.debug(
                f"[DIAGNOSTIC] Updated ENABLE_PERF_TIMING from config: {ENABLE_PERF_TIMING}")

        try:
            cfg = BridgeConfig.from_dict(config_dict)
        except Exception as e:
            return self._build_result_error(f"Invalid configuration: {e}")

        try:
            setup_environment_variables(cfg)
        except Exception as e:
            return self._build_result_error(f"Failed to setup environment variables: {e}")

        try:
            # Non-ASCII entity names (e.g. Japanese) can still cause a silent sync failure
            # due to Neo4j BM25 Lucene query errors in search_utils.py. asyncio.run()
            # eliminates the RuntimeWarning symptom; the underlying Lucene sanitizer
            # issue is a separate open investigation.
            return asyncio.run(self._run_single_note(cfg))
        except Exception as e:
            logger.error(f"[DAEMON] Event loop execution error: {e}")
            return self._build_result_error(f"Async execution failed: {e}")

    def handle_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process incoming command. Adheres to JSON-only stdout protocol.
        """
        command = command_data.get("command")

        if command == "sync":
            config = command_data.get("config", {})
            return self.run_sync_with_config(config)
        elif command == "shutdown":
            self.running = False
            return {"status": "success", "message": "Daemon shutting down"}
        elif command == "status":
            return {
                "status": "success",
                "running": self.running
            }
        else:
            return {"status": "error", "message": f"Unknown command: {command}"}

    def run(self):
        """
        Main daemon loop. Prints only JSON to stdout.
        """
        with time_operation("daemon_startup", "initialization"):
            # Log timing summary after initialization
            log_timing_summary()

            logger.info("[DAEMON] Daemon ready")
            # Handshake
            ready_message = {
                "status": "ready",
                "timestamp": time.time()
            }
            print(json.dumps(ready_message), flush=True)

        # Command loop
        while self.running:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                with time_operation("json_parsing", "command_processing"):
                    command_data = json.loads(line)
            except json.JSONDecodeError as e:
                # Protocol: JSON only on stdout (error payload as JSON)
                print(json.dumps(
                    {"status": "error", "message": f"Invalid JSON: {e}"}), flush=True)
                continue

            with time_operation("command_handling", "command_processing"):
                response = self.handle_command(command_data)
            print(json.dumps(response), flush=True)

        self.running = False


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    daemon = SyncDaemon()
    daemon.run()
