"""Register (or update) the knowledge-base MCP server in Claude Desktop's config. Keeps a backup."""
import json, os, shutil, sys, time
py, server, cfg = sys.argv[1], sys.argv[2], sys.argv[3]
p = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
data = {}
if os.path.exists(p):
    shutil.copy(p, p + time.strftime(".backup-%Y%m%d-%H%M%S"))
    data = json.load(open(p))
data.setdefault("mcpServers", {})["knowledge-base"] = {
    "command": py, "args": [server], "env": {"KB_RAG_CONFIG": cfg, "HF_HOME": os.path.expanduser("~/KnowledgeRAG/hf"),
                                              "TOKENIZERS_PARALLELISM": "false"}}
json.dump(data, open(p, "w"), indent=2)
print(f"Claude Desktop config updated: {p}\nRestart Claude Desktop (Cmd+Q, reopen) to load the 'knowledge-base' tools.")
