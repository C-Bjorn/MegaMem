#!/usr/bin/env python3
"""
Graphiti Bridge Installation Script

Hybrid pip/uv installation approach for maximum compatibility with community plugin users.
This script automatically detects available package managers and installs graphiti-core
with the appropriate extras based on user configuration.
"""

import subprocess
import sys
import json
import os
import argparse
import io
from typing import List, Dict, Any

# Single source of truth for the graphiti-core version constraint (Day79.02 Task 1 / Rev 5 SS8).
# Do not hardcode a pin here - read it from mcp-server/requirements.txt so there is exactly
# one place that declares the graphiti-core version across the whole plugin.
_REQUIREMENTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcp-server', 'requirements.txt')


def read_graphiti_core_spec(requirements_path: str = _REQUIREMENTS_PATH) -> str:
    """Read the exact graphiti-core[extras]==version spec from mcp-server/requirements.txt.

    Falls back to a safe last-known pin only if requirements.txt cannot be read at all,
    so this script never silently installs an unbounded/arbitrary version.
    """
    fallback = "graphiti-core[falkordb,anthropic,google-genai,groq,voyageai]==0.29.3"
    try:
        with open(requirements_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('graphiti-core'):
                    return line
    except OSError as e:
        print(f"WARNING: Could not read {requirements_path}: {e}")
        print(f"WARNING: Falling back to last-known pin: {fallback}")
        return fallback
    print(f"WARNING: No graphiti-core line found in {requirements_path}")
    print(f"WARNING: Falling back to last-known pin: {fallback}")
    return fallback

# Force UTF-8 encoding for Windows compatibility
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check_python_environment():
    """Verify Python 3.10+ requirement"""
    if sys.version_info < (3, 10):
        raise RuntimeError(f"Python 3.10+ required, found {sys.version}")
    print(f"✓ Python {sys.version} meets requirements")


def detect_package_manager():
    """Check if pip is available"""
    try:
        result = subprocess.run(['pip', '--version'],
                                check=True, capture_output=True, text=True)
        print(f"✓ pip detected: {result.stdout.strip()}")
        return 'pip'
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("pip not found. Please install pip first.")


def build_extras_list(config: Dict[str, Any]) -> List[str]:
    """Build list of ALL available extras to install for maximum compatibility"""
    # Install ALL provider extras to allow users to switch between providers
    # without needing to reinstall dependencies
    all_extras = [
        # Database extras (though neo4j and falkordb are in base)
        'falkordb',

        # LLM provider extras
        'anthropic',
        'google-genai',
        'groq',
        # Note: openai, ollama, and azure-openai (LLM client + embedder) are included in
        # base graphiti-core - there is no 'azure-openai' extra on this release (Day79.02 wrap-up)

        # Embedder provider extras
        'voyageai',
        # Note: openai embedder is included in base graphiti-core
    ]

    return all_extras


def install_graphiti(package_manager: str, extras: List[str]):
    """Install graphiti-core using the exact spec declared in mcp-server/requirements.txt.

    `extras` is accepted for backward compatibility with callers/CLI args but is no longer
    used to build the spec - requirements.txt is the single source of truth for both the
    version pin and the extras list (Day79.02 Task 1 / Rev 5 SS8).
    """
    package_spec = read_graphiti_core_spec()
    print(f"Installing graphiti-core using spec from requirements.txt: {package_spec}")

    # Build installation command (simplified to use only pip)
    cmd = ['pip', 'install', '--upgrade', '--user', package_spec]

    print(f"Running: {' '.join(cmd)}")
    print("This may take a few minutes...")
    sys.stdout.flush()  # Force output to appear immediately

    try:
        # Run installation with real-time output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, universal_newlines=True)

        # Stream output line by line
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    print(f"  {line}")
                    sys.stdout.flush()

        # Wait for process to complete
        returncode = process.wait()

        if returncode == 0:
            print("✓ Installation completed successfully")
            return True
        else:
            print(f"❌ Installation failed with exit code {returncode}")
            raise subprocess.CalledProcessError(returncode, cmd)

    except subprocess.CalledProcessError as e:
        print(f"❌ Installation failed with exit code {e.returncode}")
        raise


def verify_installation():
    """Verify that graphiti-core was installed correctly"""
    try:
        import graphiti_core
        # Try to get version, fallback to "installed" if not available
        try:
            version = graphiti_core.__version__
            print(f"✓ graphiti-core {version} imported successfully")
        except AttributeError:
            print("✓ graphiti-core imported successfully")

        # Test basic functionality
        from graphiti_core import Graphiti
        print("✓ Graphiti class available")
        return True
    except ImportError as e:
        print(f"❌ Failed to import graphiti-core: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        return False


def main():
    """Main installation process"""
    try:
        # Parse command-line arguments
        parser = argparse.ArgumentParser(
            description='Install Graphiti dependencies')
        parser.add_argument('--llm-provider', default='openai',
                            help='LLM provider (openai, anthropic, google, azure, groq, ollama)')
        parser.add_argument('--embedder-provider', default='openai',
                            help='Embedder provider (openai, voyage)')
        parser.add_argument('--database-type', default='neo4j',
                            help='Database type (neo4j, falkordb)')
        parser.add_argument('--json-config', type=str,
                            help='JSON configuration string (alternative to individual args)')

        args = parser.parse_args()

        # Build config from arguments
        if args.json_config:
            config = json.loads(args.json_config)
        else:
            config = {
                'llmProvider': args.llm_provider,
                'embedderProvider': args.embedder_provider,
                'databaseType': args.database_type
            }

        print("🚀 Starting Graphiti Bridge Installation")
        print("=" * 50)

        # Step 1: Check Python environment
        print("\n📋 Checking Python environment...")
        check_python_environment()

        # Step 2: Detect package manager
        print("\n🔍 Detecting package manager...")
        package_manager = detect_package_manager()

        # Step 3: Build extras list
        print("\n📦 Building package specification...")
        extras = build_extras_list(config)
        print(f"Installing ALL provider extras for maximum compatibility:")
        print(f"  - Database: neo4j (built-in), falkordb")
        print(f"  - LLM: openai (built-in), anthropic, google-genai, azure-openai (built-in), groq, ollama (built-in)")
        print(f"  - Embedder: openai (built-in), voyageai")
        print(f"\nThis ensures you can switch between any provider without reinstalling.")

        # Step 4: Install graphiti-core
        print("\n⬇️  Installing graphiti-core...")
        install_graphiti(package_manager, extras)

        # Step 5: Verify installation
        print("\n✅ Verifying installation...")
        if verify_installation():
            print("\n🎉 Installation completed successfully!")
            print("\nGraphiti Bridge is ready to use.")
            return 0
        else:
            print("\n❌ Installation verification failed")
            return 1

    except Exception as e:
        print(f"\n💥 Installation failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
