#!/usr/bin/env python3
"""
Test Ollama Connection and Model Availability

This script verifies that Ollama is running and has the required models.
"""

import requests
import json
import sys


def test_ollama_connection():
    """Test basic Ollama server connectivity"""
    base_url = "http://localhost:11434"

    print("[INFO] Testing Ollama server connectivity...")

    try:
        # Test basic server connection
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code == 200:
            print("[SUCCESS] Ollama server is running")
            models = response.json().get('models', [])
            print(f"[INFO] Available models: {len(models)}")
            for model in models:
                print(f"  - {model.get('name', 'Unknown')}")
            return models
        else:
            print(
                f"[ERROR] Ollama server returned status {response.status_code}")
            return None

    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to Ollama server at localhost:11434")
        print("[INFO] Please ensure Ollama is running:")
        print("  - Install Ollama from https://ollama.ai/")
        print("  - Run 'ollama serve' to start the server")
        return None
    except Exception as e:
        print(f"[ERROR] Connection test failed: {e}")
        return None


def test_embedding_model(model_name="nomic-embed-text"):
    """Test if the embedding model is available"""
    base_url = "http://localhost:11434"

    print(f"[INFO] Testing embedding model '{model_name}'...")

    try:
        # Test embedding endpoint
        response = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": model_name, "prompt": "test"},
            timeout=10
        )

        if response.status_code == 200:
            print(f"[SUCCESS] Model '{model_name}' is available and working")
            return True
        elif response.status_code == 404:
            print(f"[ERROR] Model '{model_name}' not found")
            print(f"[INFO] Install the model with: ollama pull {model_name}")
            return False
        else:
            print(
                f"[ERROR] Embedding test failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"[ERROR] Embedding test failed: {e}")
        return False


def test_openai_compatibility():
    """Test OpenAI-compatible endpoint"""
    base_url = "http://localhost:11434/v1"

    print("[INFO] Testing OpenAI-compatible endpoint...")

    try:
        # Test OpenAI-style embedding endpoint
        response = requests.post(
            f"{base_url}/embeddings",
            headers={"Authorization": "Bearer ollama"},
            json={
                "model": "nomic-embed-text",
                "input": ["test embedding"]
            },
            timeout=10
        )

        if response.status_code == 200:
            print("[SUCCESS] OpenAI-compatible endpoint working")
            result = response.json()
            embeddings = result.get('data', [])
            if embeddings:
                print(f"[SUCCESS] Received {len(embeddings)} embeddings")
                print(
                    f"[INFO] Embedding dimension: {len(embeddings[0].get('embedding', []))}")
            return True
        else:
            print(
                f"[ERROR] OpenAI endpoint failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"[ERROR] OpenAI compatibility test failed: {e}")
        return False


def main():
    """Run all Ollama tests"""
    print("=== Ollama Connection Diagnostics ===")

    # Test 1: Basic server connectivity
    models = test_ollama_connection()
    if not models:
        print("\n[CRITICAL] Ollama server is not running or accessible")
        sys.exit(1)

    print()

    # Test 2: Check for embedding model
    has_embedding_model = False
    for model in models:
        if "nomic-embed-text" in model.get('name', ''):
            has_embedding_model = True
            break

    if not has_embedding_model:
        print("[WARNING] nomic-embed-text model not found in model list")
        print("[INFO] Install with: ollama pull nomic-embed-text")

    # Test 3: Test embedding functionality
    embedding_works = test_embedding_model()
    print()

    # Test 4: Test OpenAI compatibility
    openai_works = test_openai_compatibility()
    print()

    # Summary
    print("=== Test Summary ===")
    print(f"[INFO] Ollama server: {'RUNNING' if models else 'NOT RUNNING'}")
    print(
        f"[INFO] Embedding model: {'AVAILABLE' if embedding_works else 'MISSING'}")
    print(
        f"[INFO] OpenAI compatibility: {'WORKING' if openai_works else 'FAILED'}")

    if models and embedding_works and openai_works:
        print("\n[SUCCESS] All tests passed! Ollama should work with Graphiti.")
    else:
        print("\n[ERROR] Some tests failed. Please fix the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
