# MCP Server Connection Guide

PubTator-Link exposes a curated research-use MCP surface for biomedical literature exploration.

| Mode | Endpoint | Status | Use Case |
|------|----------|--------|----------|
| Streamable HTTP | `/mcp` | Recommended | Claude HTTP, ChatGPT developer mode, hosted remote MCP clients |
| stdio | `pubtator-link-mcp` | Local fallback | Local desktop-only workflows |

PubTator-Link tools are research-oriented and must not be used for diagnosis, treatment, triage, patient management, or clinical decision support.

## Start The Server

```bash
python server.py --transport unified
```

The unified server provides:

- REST API at `http://127.0.0.1:8000/`
- Interactive docs at `http://127.0.0.1:8000/docs`
- MCP Streamable HTTP at `http://127.0.0.1:8000/mcp`

## ChatGPT Developer Mode

Add a remote MCP connector with this URL:

```text
https://your-domain.example/mcp
```

Use no authentication only for local/private deployments. Public deployments should be protected by OAuth or an authenticated reverse proxy. PubTator-Link tools are research-oriented and must not be used for diagnosis, treatment, triage, patient management, or clinical decision support.

## Claude HTTP

```bash
claude mcp add --transport http pubtator-link https://your-domain.example/mcp
```

For local development:

```bash
python server.py --transport unified
claude mcp add --transport http pubtator-link http://127.0.0.1:8000/mcp
```

## Claude Desktop HTTP Config

```json
{
  "mcpServers": {
    "pubtator-link": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## stdio Fallback

Use stdio only for local desktop workflows that cannot connect to HTTP MCP endpoints:

```json
{
  "mcpServers": {
    "pubtator-link-stdio": {
      "command": "pubtator-link-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1",
        "PUBTATOR_LINK_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

## Available Tools

| Tool | Use When |
|------|----------|
| `pubtator.search_literature` | Search PubMed literature through PubTator3 |
| `pubtator.fetch_publication_annotations` | Fetch annotations for PubMed IDs |
| `pubtator.fetch_pmc_annotations` | Fetch annotations for PMC full-text articles |
| `pubtator.search_biomedical_entities` | Find canonical PubTator biomedical entity IDs |
| `pubtator.find_entity_relations` | Explore literature-derived relations for a PubTator entity |
| `pubtator.submit_text_annotation` | Submit research text for PubTator biomedical NER |
| `pubtator.get_text_annotation_results` | Retrieve asynchronous text annotation results |
| `pubtator.get_server_capabilities` | Discover formats, bioconcepts, relation types, and limitations |

## Verification

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

## Troubleshooting

If the HTTP endpoint is unavailable, confirm the server is running in unified mode and that reverse proxy forwarding preserves POST requests to `/mcp`.

For hosted deployments behind Nginx Proxy Manager, see `docker/README.md`.
