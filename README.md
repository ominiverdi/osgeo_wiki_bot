# OSGeo Wiki Bot

A Matrix chat bot that answers questions about OSGeo wiki content using PostgreSQL full-text search and LLM-powered responses.

## Project Overview

This bot crawls the OSGeo wiki, processes content into searchable chunks, and enables natural language queries through a Matrix chat interface. It provides concise, contextual answers to questions about OSGeo projects, events, governance, and community activities.

## Architecture

### Components

- **Crawler**: Extracts content from wiki.osgeo.org
- **Database**: PostgreSQL with full-text search capabilities
- **MCP Server**: Model Context Protocol server that processes queries
- **LLM Integration**: Uses Ollama for SQL generation and response formatting

### Data Flow

1. **Crawling**: Python crawler extracts content from OSGeo wiki
2. **Processing**: Content analyzed and divided into 500-character chunks
3. **Storage**: Data indexed in PostgreSQL with full-text search vectors
4. **Query Processing**:
   - User query received via Matrix
   - LLM generates optimized PostgreSQL search query
   - Database returns relevant content chunks
   - LLM transforms chunks into coherent, concise response
5. **Context Management**: System tracks conversation for follow-up questions

## Key Features

- **Intelligent Search**: Uses PostgreSQL's full-text search with LLM-optimized queries
- **Conversation Context**: Maintains history for coherent multi-turn interactions
- **Category-Aware**: Boosts relevance based on content categories
- **Concise Responses**: Generates chat-friendly answers from search results

## Database Design

- **Content Chunking**: 500-character chunks for optimal search precision
- **Full-Text Indexing**: Automatic text vector generation using PostgreSQL triggers
- **Category Classification**: Leverages wiki categories for better search filtering

## Setup and Usage

### Prerequisites

- Python 3.9+
- PostgreSQL 12+
- Matrix server access
- Ollama for LLM integration

### Quick Start

```bash
# Setup environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Crawl wiki content
python crawler/crawler.py

# Populate database
python db/populate_wiki_db.py

# Start MCP server
python run_server.py

# Test with CLI client
./mcp_client/cli/run.sh "What is OSGeo?"
```

## Project Structure

```
osgeo_wiki_bot/
├── analysis/        # Content analysis scripts
├── crawler/         # Wiki crawling components
├── db/              # Database population scripts
├── mcp_client/      # Matrix client implementation
├── mcp_server/      # Matrix Chat Protocol server
│   ├── app.py       # FastAPI application
│   ├── db/          # Database interaction
│   ├── handlers/    # Request handlers
│   ├── llm/         # LLM integration
│   └── utils/       # Utility functions
├── schema/          # Database schema definitions
└── wiki_dump/       # Raw crawled content
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.