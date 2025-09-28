"""
Graphiti Bridge Package

Python bridge for connecting Obsidian plugin with Graphiti temporal knowledge graphs.
Provides simple process-spawning interface with JSON communication.
"""

__version__ = "1.0.0"
__author__ = "Casey Bjørn <bjorn@endogon.com>"
__copyright__ = "Copyright 2024, Casey Bjørn"
__license__ = "MIT"

# Import main components for easy access
from .config import BridgeConfig
from .utils import (
    extract_frontmatter,
    extract_text_content,
    setup_logging,
    format_error_response,
    format_success_response
)

__all__ = [
    "BridgeConfig",
    "extract_frontmatter",
    "extract_text_content",
    "setup_logging",
    "format_error_response",
    "format_success_response"
]
