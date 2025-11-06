"""
Utility functions for Graphiti Bridge

Helper functions for text processing, frontmatter extraction, logging, and response formatting.
"""

import re
import json
import logging
import sys
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime

# Optional YAML import for frontmatter parsing
YAML_AVAILABLE = False
try:
    import yaml  # type: ignore[import]
    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore[assignment]

# TEMP DEBUG: Force stderr output to see if anything works
# Debug logging bridge functions

# @purpose: Global debug flag and stderr logging functions to replace broken Python logging
# @depends: sys.stderr, json for structured output
# @results: Clean debug messages in consolidated.log, stdout preserved for JSON bridge

DEBUG_ENABLED = False


def set_debug_enabled(enabled: bool):
    """Set global debug flag"""
    global DEBUG_ENABLED
    DEBUG_ENABLED = enabled


def debug_log(message: str, tag: str = "PYTHON", data: Optional[dict] = None):
    """Simple stderr logger - TypeScript will add timestamps"""
    if DEBUG_ENABLED:
        print(f"[{tag}] {message}", file=sys.stderr, flush=True)
        if data:
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            indented = "\n".join("  " + line for line in pretty.splitlines())
            print(f"  Data: {indented}", file=sys.stderr, flush=True)


class DebugLogger:
    """Bridge logger that routes to debug_log while preserving existing API"""

    def __init__(self, debug_enabled: bool):
        self.debug_enabled = debug_enabled

    def debug(self, msg, *args):

        if self.debug_enabled:
            debug_log(msg % args if args else msg, "DEBUG")

    def info(self, msg, *args):

        if self.debug_enabled:
            debug_log(msg % args if args else msg, "INFO")

    def warning(self, msg, *args):

        debug_log(msg % args if args else msg, "WARN")  # Always show warnings

    def error(self, msg, *args):

        debug_log(msg % args if args else msg, "ERROR")  # Always show errors

    def exception(self, msg, *args):

        debug_log(f"EXCEPTION: {msg % args if args else msg}", "ERROR")


def setup_logging(debug: bool = False) -> DebugLogger:
    """Return bridge logger instead of Python's logging module"""
    set_debug_enabled(debug)

    # Override logging.getLogger to return our DebugLogger for graphiti_bridge loggers
    original_getLogger = logging.getLogger
    debug_logger_instance = DebugLogger(debug)

    def patched_getLogger(name=None):
        if name and ('graphiti_bridge' in name or 'graphiti_core' in name):
            return debug_logger_instance
        return original_getLogger(name)

    logging.getLogger = patched_getLogger
    return debug_logger_instance


def extract_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Extract YAML frontmatter from markdown content

    Returns:
        Tuple of (frontmatter_dict, content_without_frontmatter)
    """
    frontmatter = {}
    remaining_content = content

    # Check for YAML frontmatter (--- at start and end)
    frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if match:
        frontmatter_text = match.group(1)
        try:
            if YAML_AVAILABLE and yaml:
                parsed = yaml.safe_load(frontmatter_text)
                frontmatter = parsed if isinstance(parsed, dict) else {}
                remaining_content = content[match.end():]
            else:
                # Fallback to simple key-value parsing if PyYAML not available
                frontmatter = parse_simple_frontmatter(frontmatter_text)
                remaining_content = content[match.end():]
        except Exception as e:
            logging.warning(f"Failed to parse frontmatter: {e}")
            # Keep original content if parsing fails

    return frontmatter, remaining_content


def parse_simple_frontmatter(frontmatter_text: str) -> Dict[str, Any]:
    """
    Simple frontmatter parser fallback for when PyYAML is not available
    Handles basic key: value pairs
    """
    frontmatter = {}

    for line in frontmatter_text.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('#'):
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            # Convert basic types
            if value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            elif value.replace('.', '').isdigit():
                value = float(value)

            frontmatter[key] = value

    return frontmatter


def extract_text_content(content: str) -> str:
    """
    Extract clean text content from markdown, removing frontmatter and cleaning formatting
    """
    # Remove frontmatter
    _, clean_content = extract_frontmatter(content)

    # Remove wiki-style links [[link]]
    clean_content = re.sub(r'\[\[([^\]]+)\]\]', r'\1', clean_content)

    # Remove markdown links [text](url)
    clean_content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_content)

    # Remove markdown headers (keep the text)
    clean_content = re.sub(r'^#+\s+', '', clean_content, flags=re.MULTILINE)

    # Remove markdown emphasis (keep the text)
    clean_content = re.sub(r'\*\*([^\*]+)\*\*', r'\1', clean_content)  # Bold
    clean_content = re.sub(r'\*([^\*]+)\*', r'\1', clean_content)      # Italic
    clean_content = re.sub(r'_([^_]+)_', r'\1', clean_content)         # Italic

    # Remove code blocks and inline code
    clean_content = re.sub(r'```[^`]*```', '', clean_content, flags=re.DOTALL)
    clean_content = re.sub(r'`([^`]+)`', r'\1', clean_content)

    # Remove HTML tags
    clean_content = re.sub(r'<[^>]+>', '', clean_content)

    # Clean up whitespace
    clean_content = re.sub(
        r'\n\s*\n', '\n\n', clean_content)  # Multiple newlines
    clean_content = clean_content.strip()

    return clean_content


def format_success_response(processed: int = 0, skipped: int = 0, **kwargs) -> str:
    """Format a success response as JSON"""
    response = {
        'status': 'success',
        'processed': processed,
        'skipped': skipped,
        'timestamp': datetime.utcnow().isoformat(),
        **kwargs
    }
    return json.dumps(response)


def format_error_response(message: str, details: Optional[str] = None, **kwargs) -> str:
    """Format an error response as JSON"""
    response = {
        'status': 'error',
        'message': message,
        'timestamp': datetime.utcnow().isoformat(),
        **kwargs
    }

    if details:
        response['details'] = details

    return json.dumps(response)


def format_progress_response(current: int, total: int, message: str = "", **kwargs) -> str:
    """Format a progress update response as JSON"""
    response = {
        'status': 'progress',
        'current': current,
        'total': total,
        'progress': round((current / total * 100), 1) if total > 0 else 0,
        'message': message,
        'timestamp': datetime.utcnow().isoformat(),
        **kwargs
    }
    return json.dumps(response)


def safe_file_read(file_path: str, encoding: str = 'utf-8') -> Optional[str]:
    """
    Safely read a file with fallback encoding options

    Returns None if file cannot be read
    """
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with different encodings
        for fallback_encoding in ['utf-8-sig', 'latin1', 'cp1252']:
            try:
                with open(file_path, 'r', encoding=fallback_encoding) as f:
                    content = f.read()
                    logging.warning(
                        f"File {file_path} read with {fallback_encoding} encoding")
                    return content
            except UnicodeDecodeError:
                continue

        logging.error(f"Could not read file {file_path} with any encoding")
        return None
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        return None


def validate_note_file(file_path: str) -> bool:
    """
    Validate that a note file exists and is readable
    """
    path = Path(file_path)

    if not path.exists():
        logging.error(f"Note file does not exist: {file_path}")
        return False

    if not path.is_file():
        logging.error(f"Path is not a file: {file_path}")
        return False

    if not file_path.lower().endswith(('.md', '.markdown', '.txt')):
        logging.warning(f"File may not be a text file: {file_path}")

    # Try to read the file
    content = safe_file_read(file_path)
    if content is None:
        return False

    return True


def sanitize_property_name(name: str) -> str:
    """
    Sanitize property names for use in graph databases

    - Remove or replace invalid characters
    - Ensure valid identifier format
    """
    # Replace spaces and special characters with underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"prop_{sanitized}"

    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)

    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')

    # Ensure non-empty
    if not sanitized:
        sanitized = "property"

    return sanitized


def chunk_list(items: list, chunk_size: int):
    """
    Split a list into chunks of specified size
    """
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


def get_file_modification_time(file_path: str) -> Optional[datetime]:
    """
    Get the modification time of a file
    """
    try:
        path = Path(file_path)
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime)
    except Exception as e:
        logging.error(f"Error getting modification time for {file_path}: {e}")
    return None


def print_json_response(response_dict: dict):
    """
    Print a response as JSON to stdout (for TypeScript to capture)
    """
    print(json.dumps(response_dict, ensure_ascii=False,
          separators=(',', ':')), flush=True)


def print_final_json_response(response_dict: dict):
    """
    Print the final result JSON response to stdout with explicit formatting

    CRITICAL: This function MUST ONLY print to stdout - never to stderr.
    TypeScript expects the final JSON result on stdout for the bridge communication.
    All debug/diagnostic logging should go through the DebugLogger to stderr.
    """
    # Ensure clean JSON output for final response
    json_str = json.dumps(
        response_dict, ensure_ascii=False, separators=(',', ':'))
    print(json_str, flush=True)


def print_error_and_exit(message: str, details: Optional[str] = None, exit_code: int = 1):
    """
    Print an error response and exit
    """
    error_response = format_error_response(message, details)
    # Add type field for consistency with TypeScript expectations
    response_dict = json.loads(error_response)
    response_dict['type'] = 'result'  # Mark as final result even for errors
    final_error = json.dumps(
        response_dict, ensure_ascii=False, separators=(',', ':'))
    print(final_error, flush=True)
    sys.exit(exit_code)
