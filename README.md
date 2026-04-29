# PubTator-Link

A unified server for the PubTator3 biomedical literature API with MCP integration for AI assistants.

## 🎯 Core Features

- **Unified API Server**: Modern FastAPI-based REST API for PubTator3 data access
- **MCP Integration**: Model Context Protocol server for seamless AI assistant integration
- **Rate-Limited Client**: Respects PubTator3 API guidelines (3 requests/second max)
- **Intelligent Caching**: Async LRU caching with configurable TTL for optimal performance
- **Multiple Transport Modes**: HTTP REST API, MCP STDIO, or unified mode
- **Rich Data Models**: Comprehensive Pydantic models for all API responses
- **Production Ready**: Structured logging, health checks, and graceful shutdown

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd pubtator-link

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev]"

# Create environment configuration
cp .env.example .env
```

### Environment Configuration

Create a `.env` file with your configuration:

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

### Start the Server

```bash
# Unified mode (REST API + MCP)
python server.py --transport unified

# HTTP-only mode (REST API only) 
python server.py --transport http

# STDIO mode (MCP only)
python server.py --transport stdio
```

## 📋 REST API Endpoints

### Core Endpoints

- `GET /` - Root endpoint with service information
- `GET /health` - Health check and status
- `GET /api/cache/stats` - Cache statistics
- `DELETE /api/cache/clear` - Clear cache

### Publication Export

- `GET /api/publications/export/{format}` - Export publication annotations by PMIDs
- `GET /api/publications/pmc_export/{format}` - Export PMC publications by PMC IDs

**Supported formats**: `pubtator`, `biocxml`, `biocjson`

```bash
# Export publication annotations in BioC JSON format
curl "http://127.0.0.1:8000/api/publications/export/biocjson?pmids=29355051,32511357"

# Export with full text (biocxml/biocjson only)
curl "http://127.0.0.1:8000/api/publications/export/biocxml?pmids=29355051&full=true"

# Export PMC publications
curl "http://127.0.0.1:8000/api/publications/pmc_export/biocjson?pmcids=PMC7696669,PMC8869656"
```

### Entity Search

- `GET /api/entities/autocomplete` - Find entity IDs through autocomplete

**Supported bioconcepts**: `Gene`, `Disease`, `Chemical`, `Species`, `Variant`, `CellLine`

```bash
# Find disease entities
curl "http://127.0.0.1:8000/api/entities/autocomplete?query=breast%20cancer&concept=Disease&limit=5"

# Find gene entities
curl "http://127.0.0.1:8000/api/entities/autocomplete?query=BRCA1&concept=Gene"
```

### Publication Search  

- `GET /api/search` - Search publications by text, entity IDs, or relations with sorting

```bash
# Free text search (default: relevance-based sorting)
curl "http://127.0.0.1:8000/api/search?text=breast%20cancer&page=1"

# Sort by publication date (newest first)
curl "http://127.0.0.1:8000/api/search?text=breast%20cancer&sort=date%20desc"

# Sort by publication date (oldest first)
curl "http://127.0.0.1:8000/api/search?text=autism&sort=date%20asc"

# Sort by relevance score (highest first)
curl "http://127.0.0.1:8000/api/search?text=epilepsy&sort=score%20desc"

# Entity-based search with sorting
curl "http://127.0.0.1:8000/api/search?text=@CHEMICAL_remdesivir&sort=date%20desc"

# Relation-based search
curl "http://127.0.0.1:8000/api/search?text=relations:ANY|@CHEMICAL_Doxorubicin|@DISEASE_Neoplasms"
```

**Supported sort options:**
- `date desc` - Newest publications first (default for date sorting)
- `date asc` - Oldest publications first  
- `score desc` - Highest relevance first (default for relevance sorting)
- `score asc` - Lowest relevance first

### Entity Relations

- `GET /api/relations` - Find related entities

**Supported relation types**: `treat`, `cause`, `cotreat`, `convert`, `compare`, `interact`, `associate`, `positive_correlate`, `negative_correlate`, `prevent`, `inhibit`, `stimulate`, `drug_interact`

```bash
# Find entities that interact with a chemical
curl "http://127.0.0.1:8000/api/relations?e1=@CHEMICAL_remdesivir&type=interact"

# Find diseases treated by a chemical  
curl "http://127.0.0.1:8000/api/relations?e1=@CHEMICAL_Doxorubicin&type=treat&e2=Disease"
```

### Text Annotation

- `POST /api/annotations/submit` - Submit text for NER processing
- `GET /api/annotations/{session_id}` - Retrieve annotation results

```bash
# Submit text for gene entity extraction
curl -X POST "http://127.0.0.1:8000/api/annotations/submit" \
  -H "Content-Type: application/json" \
  -d '{"text": "The ESR1 mutations are associated with breast cancer", "bioconcept": "Gene"}'

# Retrieve results (use session_id from submit response)
curl "http://127.0.0.1:8000/api/annotations/abc123def456"
```

## 🔧 MCP Integration

### Configuration for AI Assistants

#### Claude Desktop (STDIO Mode)

Add to your Claude Desktop configuration (`claude_desktop_config.json`):

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

#### Web-based AI (HTTP Mode)

For HTTP-based MCP integration:

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

### Configuration Files

**Find your Claude Desktop config file:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

**Example configurations are provided:**
- See `claude_desktop_config_example.json` for complete examples
- Copy and modify paths to match your installation

### Available MCP Tools

- `export_publication_annotations` - Export annotations for publications by PMIDs
- `export_pmc_publications` - Export PMC publications by PMC IDs
- `search_entity_ids` - Find biomedical entity identifiers with autocomplete
- `search_publications` - Search biomedical literature with pagination and sorting
- `find_related_entities` - Discover entity relationships and associations
- `submit_text_annotation` - Submit text for biomedical entity extraction
- `get_annotation_results` - Retrieve text annotation results
- `get_cache_statistics` - Monitor cache performance
- `clear_cache` - Clear cached data

### Transport Modes

#### STDIO Mode (Recommended for Claude Desktop)
```bash
# Direct STDIO mode for maximum performance
python mcp_server.py
```

#### HTTP Mode (For web-based AI)
```bash
# Start unified server with MCP HTTP endpoint
python server.py --transport unified
# MCP available at http://localhost:8000/mcp
```

#### Unified Mode (REST + MCP)
```bash
# Both REST API and MCP in one server
python server.py --transport unified
# REST API: http://localhost:8000/docs
# MCP: http://localhost:8000/mcp
```

### 📚 Additional Documentation

- **[MCP Connection Guide](docs/MCP_CONNECTION_GUIDE.md)** - Detailed setup instructions for all transport modes
- **[Configuration Examples](claude_desktop_config_example.json)** - Ready-to-use Claude Desktop configurations
- **Interactive API Docs** - Available at http://localhost:8000/docs when server is running

## 🛠️ CLI Usage

The CLI provides convenient access to PubTator3 functionality:

```bash
# Test API connection
pubtator-link test

# Search for entity IDs
pubtator-link entities "breast cancer" --concept Disease --limit 5

# Search publications
pubtator-link search "@CHEMICAL_remdesivir" --page 1

# Export publication annotations
pubtator-link export "29355051,32511357" --format biocjson --full
```

## 🏗️ Architecture

### Project Structure

```
pubtator-link/
├── pubtator_link/
│   ├── api/
│   │   ├── client.py           # PubTator3 API client with rate limiting
│   │   └── routes/             # FastAPI route definitions
│   ├── models/
│   │   ├── requests.py         # Request validation models
│   │   ├── responses.py        # Response models
│   │   ├── entities.py         # Bioconcept entity models
│   │   └── publications.py     # Publication models
│   ├── services/
│   │   └── publication_service.py  # Business logic with caching
│   ├── config.py               # Configuration management
│   ├── logging_config.py       # Structured logging
│   ├── server_manager.py       # Unified server management
│   └── cli.py                  # Command-line interface
├── server.py                   # Main server entry point
├── mcp_server.py              # MCP STDIO server entry point
└── pyproject.toml             # Modern Python project configuration
```

### Key Components

- **API Client**: Rate-limited HTTP client respecting PubTator3 guidelines
- **Service Layer**: Business logic with async LRU caching
- **Server Manager**: Unified handling of multiple transport modes
- **Data Models**: Comprehensive Pydantic models for type safety
- **MCP Integration**: Backwards-compatible STDIO server

## 🧪 Development

### Modern Development Workflow

This project uses `uv` and `make` as the primary local development interface.

```bash
make install       # install project and dev dependencies
make lock          # update uv.lock
make format        # format with Ruff
make lint          # lint with Ruff
make typecheck     # run mypy
make test          # run tests
make test-fast     # run tests in parallel
make ci-local      # run local CI checks
```

Dependencies are locked in `uv.lock`; update them with `uv lock` or
`make lock`. Agentic coding tools should follow `AGENTS.md`; Claude Code also
loads the lean `CLAUDE.md` entrypoint.

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=pubtator_link

# Run specific test categories
pytest -m "not slow"        # Exclude slow tests
pytest -m integration       # Only integration tests
```

### Code Quality

The project uses modern Python tooling:

- **Ruff**: Fast linting and formatting
- **MyPy**: Static type checking
- **Pytest**: Testing framework with async support
- **Pre-commit**: Git hooks for code quality

## 📦 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Server host address |
| `PORT` | `8000` | Server port |
| `TRANSPORT` | `unified` | Server mode (unified/http/stdio) |
| `API_BASE_URL` | `https://www.ncbi.nlm.nih.gov/research/pubtator3-api` | PubTator3 API base URL |
| `API_TIMEOUT` | `30` | API request timeout (seconds) |
| `RATE_LIMIT_PER_SECOND` | `2.5` | Rate limit (requests/second) |
| `CACHE_SIZE` | `1000` | LRU cache size |
| `CACHE_TTL` | `3600` | Cache TTL (seconds) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FORMAT` | `console` | Log format (console/json) |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS allowed origins |

### Cache Configuration

The caching system uses async LRU caching with configurable size and TTL:

- **Publication Export**: Cached by PMIDs, format, and full-text flag
- **Entity Autocomplete**: Cached by query, concept, and limit
- **Publication Search**: Cached by query text and page number
- **Entity Relations**: Cached by entity, relation type, and target type

## 🚀 Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install -e .

EXPOSE 8000

CMD ["python", "server.py", "--transport", "unified", "--host", "0.0.0.0"]
```

### Health Monitoring

The server provides comprehensive health checks:

```bash
# Check server health
curl http://localhost:8000/health

# Monitor cache performance
curl http://localhost:8000/api/cache/stats
```

### Observability

- **Structured Logging**: JSON format for production, console for development
- **Performance Metrics**: Request timing and cache statistics
- **Error Tracking**: Comprehensive error logging with context
- **Rate Limiting**: Built-in protection against API abuse

## 📊 Performance

- **Rate Limiting**: Respects PubTator3 API guidelines (max 3 requests/second)
- **Async Architecture**: Non-blocking I/O for high concurrency
- **Intelligent Caching**: Reduces API calls and improves response times
- **Connection Pooling**: Efficient HTTP client management
- **Graceful Degradation**: Fallback strategies for API failures

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Install development dependencies (`pip install -e ".[dev]"`)
4. Make your changes and add tests
5. Run code quality checks (`ruff check . && mypy .`)
6. Run tests (`pytest`)
7. Commit your changes (`git commit -m 'Add amazing feature'`)
8. Push to the branch (`git push origin feature/amazing-feature`)
9. Open a Pull Request

## 📚 API Reference

For detailed API documentation, visit the interactive docs when running the server:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔗 Related Projects

- **gnomAD-Link**: MCP server for gnomAD genomic data
- **GeneReviews-Link**: MCP server for NCBI GeneReviews

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [PubTator3](https://www.ncbi.nlm.nih.gov/research/pubtator3/) - NCBI's biomedical literature annotation service
- [Model Context Protocol](https://modelcontextprotocol.io/) - Open standard for AI-tool integration
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Pydantic](https://pydantic.dev/) - Data validation using Python type hints

---

**Status**: Production Ready | **Version**: 1.0.0 | **Python**: 3.11+
