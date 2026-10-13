# Frequently Asked Questions (FAQ)

<details>
<summary>What is MegaMem Pro?</summary>
MegaMem Pro is the licensed tier for Stewards. It adds a dedicated <strong>Pro tab</strong> in plugin settings where you can validate your API key, view entitled content packages (vault templates, ontology packs), install or update them directly in-plugin, and add an Endogon Hosted Graph with one click. All graph and vault MCP tools remain free; the <code>ask_bjorn</code> support tool requires a Pro key with the Ask Bjørn capability. Get a license at <a href="https://endogon.com/stewards">endogon.com/stewards</a>.
</details>

<details>
<summary>Why Obsidian?</summary>
Obsidian provides a powerful, local-first knowledge base that integrates seamlessly with MegaMem. Its flexible linking and markdown support make it an ideal environment for building and interacting with your knowledge graph.
</details>

<details>
<summary>What is Graphiti?</summary>
Graphiti is a core component of MegaMem that enables the creation and management of temporal knowledge graphs. 
</details>

<details>
<summary>What is the Model Context Protocol (MCP)?</summary>
The Model Context Protocol (MCP) allows AI assistants, like Claude Desktop, to access and interact with your MegaMem knowledge graph. This enables AI to provide more accurate, context-aware responses based on your personal knowledge.
</details>

<details>
<summary>What databases does MegaMem support?</summary>
Currently, MegaMem supports Neo4j and FalkorDB (including TLS connections). Support for Kuzu and Amazon Neptune is planned for future releases.
</details>

<details>
<summary>I upgraded to v1.8.0 and the MCP server won't start (or FalkorDB data looks missing). What do I do?</summary>
v1.8.0 pins its Python dependencies (<code>graphiti-core</code> 0.29.3, <code>mcp&gt;=1.28,&lt;2</code>), and the MCP server exits at startup if it finds <code>mcp</code> 2.x or older than 1.28. Open <strong>Settings → MegaMem → Python Environment</strong> and click <strong>Install Dependencies</strong>; the dependency health readout shows what is installed. If you use FalkorDB, graphiti-core changed its default namespace, so <strong>re-sync your vault</strong> — data synced before and after the upgrade lives under different namespace values.
</details>

<details>
<summary>On Windows the MCP server times out the first time it starts. Why?</summary>
Windows Defender scanning a freshly created virtual environment can exceed the MCP handshake window. Restart your MCP client once and it normally connects. To avoid it, add a Defender exclusion for the plugin's venv folder.
</details>

<details>
<summary>What is Publish, and how is it different from Sync?</summary>
Sync writes your notes into a graph. Publish copies an already-built namespace (<code>group_id</code>) from one graph into a separate destination database, such as Neo4j Aura. See <a href="#/publishing">Publishing a Public Graph</a>.
</details>

<details>
<summary>Do I need to manually download Python files after installing via BRAT?</summary>
No. As of v1.3.2, MegaMem automatically detects missing Python components and offers to download them on first launch. When you install via BRAT, a dialog will appear after ~3 seconds asking you to install the Python components. Click "Install / Update Components" to complete the setup automatically.
</details>

<details>
<summary>How do I update MegaMem's Python components?</summary>
Go to <strong>Settings → MegaMem → Updates</strong> (scroll to the bottom) and click "Check for Updates". The plugin will check GitHub for the latest release and prompt you to update if needed. Updates are also checked automatically when the plugin loads.
</details>
