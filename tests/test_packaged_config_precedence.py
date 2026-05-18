from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _extract_method_body(source: str, method_name: str) -> str:
    marker = f"{method_name}(){{"
    start = source.index(marker) + len(marker)
    depth = 1
    index = start

    while index < len(source) and depth:
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1

    return source[start:index - 1]


def test_packaged_connection_tests_prefer_current_database_entries():
    main_js = (PROJECT_ROOT / "main.js").read_text()

    body = _extract_method_body(main_js, "getDatabaseConfig")

    current_database_index = body.find("this.settings.databases")
    legacy_database_index = body.find("this.settings.databaseConfigs")

    assert current_database_index != -1
    assert legacy_database_index != -1
    assert current_database_index < legacy_database_index


def test_mcp_server_bridge_config_uses_shared_config_parser():
    server_source = (PROJECT_ROOT / "mcp-server" / "megamem_mcp_server.py").read_text()

    method_start = server_source.index("    def _create_bridge_config(")
    method_end = server_source.index(
        "    def _get_database_url_from_obsidian_config", method_start
    )
    method_body = server_source[method_start:method_end]

    assert "BridgeConfig.from_dict" in method_body
    assert 'current_db_config.get("password")' not in method_body
