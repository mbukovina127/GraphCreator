# Lua Code Analyzer Service

_A temporary unofficial fork of rgajdos147 LuaGraphCreator, et. al._

Dapr-based microservice for analyzing Lua source code and building knowledge graphs.

## Overview

This service is part of the SoftVis distributed visualization system. It:

1. **Subscribes** to `parser-code-tasks` topic via Dapr pub/sub
2. **Downloads** project source code (ZIP) from Graph Store Adapter
3. **Parses** Lua files using tree-sitter
4. **Builds** an AST and knowledge graph
5. **Publishes** results to `graph-updates` and `results` topics

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│   RabbitMQ          │     │  Graph Store Adapter │
│   (via Dapr)        │     │  (via Dapr)          │
└────────┬────────────┘     └──────────┬───────────┘
         │                             │
         │ parser-code-tasks           │ GET /projects/{id}/source/zip
         ▼                             │
┌───────────────────────────────────────────────────┐
│              Lua Code Analyzer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ Dapr Handler │→ │ AST Manager  │→ │ Graph    │ │
│  │ (FastAPI)    │  │ (tree-sitter)│  │ Builder  │ │
│  └──────────────┘  └──────────────┘  └──────────┘ │
└────────┬───────────────────────────────┬──────────┘
         │                               │
         │ graph-updates                 │ results
         ▼                               ▼
┌─────────────────────┐     ┌─────────────────────┐
│   Graph Store       │     │   API Program       │
│   Adapter           │     │                     │
└─────────────────────┘     └─────────────────────┘
```

## Project Structure

```
lua-code-analyzer/
├── src/
│   ├── dapr_handler.py          # Main entry point, Dapr pub/sub
│   ├── code_analyzer/           # AST parsing with tree-sitter
│   │   ├── parse_code.py        # ASTManager singleton
│   │   └── ast_metrics/         # Complexity, Halstead, LOC
│   ├── file_system_analyzer/    # Project structure analysis
│   └── graph_builder/           # Knowledge graph construction
│       ├── output_builder.py    # In-memory graph builder
│       ├── ast_inserter.py      # AST to graph conversion
│       └── graph_queries.py     # KG building logic
├── tests/                       # Unit and integration tests
├── manifests/                   # Kubernetes/Dapr manifests
├── Dockerfile
├── requirements.txt
└── README.md
```

## Development

### Prerequisites

- Python 3.11+
- Docker (for running tests with testcontainers)

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_code_analyzer.py

# Skip integration tests (no Docker)
SKIP_INTEGRATION_TESTS=true pytest
```

### Running Locally

```bash
# Without Dapr (for testing)
cd src
python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080 --reload

# With Dapr sidecar
dapr run --app-id lua-code-analyzer --app-port 8080 -- python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080
```

## API Endpoints

### Health Checks

- `GET /health` - Liveness probe
- `GET /ready` - Readiness probe

### Dapr Pub/Sub

- `GET /dapr/subscribe` - Returns subscription configuration
- `POST /parser-code-tasks` - Handles incoming parse tasks (CloudEvents format)

### Debug (Development Only)

- `POST /analyze` - Synchronous analyze endpoint for testing

## Message Formats

### Input: parser-code-tasks

```json
{
  "project_id": "uuid-of-project",
  "incremental": false
}
```

### Output: graph-updates

```json
{
  "project_id": "uuid-of-project",
  "lua_graph": {
    "vertices": [...],
    "edges": [...]
  },
  "knowledge_graph": {
    "vertices": [...],
    "edges": [...]
  },
  "metadata": {
    "total_nodes": 150,
    "total_knowledge_nodes": 45,
    "total_edges": 200,
    "total_knowledge_edges": 60
  }
}
```

### Output: results

```json
{
  "project_id": "uuid-of-project",
  "status": "completed",
  "files_processed": 10,
  "files_failed": 0,
  "errors": [],
  "message": "Successfully processed 10 files"
}
```

## Deployment

### Build Docker Image

```bash
docker build -t lua-code-analyzer:latest .
```

### Deploy to Kubernetes

```bash
# Create namespace and resources
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/dapr-pubsub.yaml
kubectl apply -f manifests/deployment.yaml
kubectl apply -f manifests/service.yaml
kubectl apply -f manifests/keda-scaledobject.yaml
```

## Configuration

| Environment Variable         | Default             | Description                   |
| ---------------------------- | ------------------- | ----------------------------- |
| `DAPR_HTTP_PORT`             | 3500                | Dapr sidecar HTTP port        |
| `PUBSUB_NAME`                | rabbitmq-pubsub     | Dapr pub/sub component name   |
| `GRAPH_STORE_ADAPTER_APP_ID` | graph-store-adapter | App ID for service invocation |
| `APP_PORT`                   | 8080                | Application HTTP port         |

## License

Part of the SoftVis project.
