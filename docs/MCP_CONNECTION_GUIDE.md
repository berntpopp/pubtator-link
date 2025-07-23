# MCP Server Connection Guide

## Understanding the Unified Server

The PubTator-Link server provides both REST API and MCP interfaces through a single unified application:

- **Single Process**: One server provides both interfaces
- **Shared Resources**: Both interfaces use the same cache and services
- **HTTP-Based**: The MCP interface is available via HTTP at `/mcp`

## How to Connect

### 1. Start the Unified Server

```bash
# Navigate to the project directory
cd /path/to/pubtator-link

# Start the server (development mode)
python server.py --transport unified

# Or production mode
uvicorn server:app --host 0.0.0.0 --port 8000
```

The server now provides:
- REST API at http://localhost:8000/
- Interactive docs at http://localhost:8000/docs
- MCP interface at http://localhost:8000/mcp

### 2. Claude Desktop Configuration (HTTP)

For Claude Desktop configurations that support HTTP endpoints:

**Step 1: Find your config file**
- Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**Step 2: Add the PubTator-Link server (HTTP endpoint)**
```json
{
  "mcpServers": {
    "pubtator-link": {
      "transport": {
        "type": "http",
        "url": "http://localhost:8000/mcp"
      }
    }
  }
}
```

**Step 3: Restart Claude Desktop**

**Step 4: Use the tools**
- Open Claude Desktop
- The PubTator-Link tools should be available:
  - `export_publication_annotations`
  - `search_entity_ids`
  - `search_publications`
  - `find_related_entities`
  - `submit_text_annotation`
  - `get_annotation_results`

### 3. Claude Desktop Configuration (STDIO)

For maximum performance and compatibility, use STDIO mode:

**Step 1: Create STDIO configuration**
```json
{
  "mcpServers": {
    "pubtator-link": {
      "command": "python",
      "args": ["/absolute/path/to/pubtator-link/mcp_server.py"],
      "env": {
        "PYTHONUNBUFFERED": "1",
        "LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

**Step 2: Restart Claude Desktop**

**Note**: Replace `/absolute/path/to/pubtator-link/` with the actual path to your installation.

### 4. Verify Connection

To verify your MCP connection is working:

1. **Check server logs**: Look for MCP client connections in server output
2. **Test in Claude**: Ask Claude to search for a biomedical entity like "BRCA1"
3. **Monitor cache**: Use the cache statistics tool to see if requests are being processed

### 5. Troubleshooting

#### Common Issues

**"No MCP tools available"**
- Ensure the server is running on the correct port
- Check firewall settings for localhost connections
- Verify the configuration file syntax is valid JSON

**"Connection refused"**
- Start the server first: `python server.py --transport unified`
- Check if port 8000 is already in use
- Try a different port: `python server.py --transport unified --port 8001`

**"STDIO mode not working"**
- Ensure Python path is correct in configuration
- Check that `mcp_server.py` is executable
- Verify environment variables are set correctly

#### Performance Tips

**For High-Performance Applications:**
- Use STDIO mode for fastest response times
- Set `LOG_LEVEL=WARNING` to reduce logging overhead
- Enable caching with appropriate TTL settings

**For Development:**
- Use HTTP mode for easier debugging
- Set `LOG_LEVEL=DEBUG` for detailed request logs
- Use unified mode to test both REST and MCP interfaces

## Example Configurations

### Complete Claude Desktop Config
```json
{
  "mcpServers": {
    "pubtator-link-stdio": {
      "command": "python",
      "args": ["/Users/username/projects/pubtator-link/mcp_server.py"],
      "env": {
        "PYTHONUNBUFFERED": "1",
        "LOG_LEVEL": "WARNING"
      }
    },
    "pubtator-link-http": {
      "transport": {
        "type": "http",
        "url": "http://localhost:8000/mcp"
      }
    }
  }
}
```

### Environment Variables
```env
# Server Configuration
HOST=127.0.0.1
PORT=8000
TRANSPORT=unified

# API Configuration
API_BASE_URL=https://www.ncbi.nlm.nih.gov/research/pubtator3-api
API_TIMEOUT=30
RATE_LIMIT_PER_SECOND=2.5

# Cache Configuration
CACHE_SIZE=1000
CACHE_TTL=3600

# Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=console

# CORS Configuration
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

## Available Tools

### Core PubTator3 Tools
- **export_publication_annotations**: Export publication annotations by PMIDs
- **export_pmc_publications**: Export PMC publications by PMC IDs
- **search_entity_ids**: Find biomedical entity identifiers
- **search_publications**: Search biomedical literature
- **find_related_entities**: Discover entity relationships

### Text Processing Tools
- **submit_text_annotation**: Submit text for biomedical NER
- **get_annotation_results**: Retrieve annotation results

### System Tools
- **get_cache_statistics**: Monitor cache performance
- **clear_cache**: Clear cached data

## Integration Examples

### Search for Disease Entities
```
Ask Claude: "Find entity IDs for 'breast cancer' using PubTator"
```

### Search Publications with Sorting
```
Ask Claude: "Search for recent publications about autism sorted by date"
Ask Claude: "Find the most relevant papers about epilepsy sorted by score"
Ask Claude: "Search for papers about intellectual disability, sorted newest first"
```

### Export Publication Data
```
Ask Claude: "Export annotations for PMIDs 29355051 and 32511357 in BioC JSON format"
```

### Process Custom Text
```
Ask Claude: "Extract gene mentions from this text: 'BRCA1 mutations increase breast cancer risk'"
```

### Find Related Entities
```
Ask Claude: "Find chemicals that interact with BRCA1 using PubTator relationships"
```