# GraphCreator — Lua CPG Pipeline

Builds a **Code Property Graph (CPG)** from Lua source code: a unified model combining the AST, a knowledge graph of declarations/calls/imports, and cross-file module edges. Processing is parallelised across files using **Ray**, with a sequential fallback for single-machine benchmarking and comparison.

## Overview

The pipeline has two phases:

| Phase | Component | Parallelism |
|-------|-----------|-------------|
| **Analysis** | Ray workers (`analyze_file`) | fully parallel — 1 worker per file |
| **Collection** | `GraphCollector.collect()` | sequential — runs after all workers finish |

For a complete architectural description, class-level API reference, and data-flow diagrams, see **[docs/technical_documentation.md](docs/technical_documentation.md)**.

Benchmark methodology, scalability results (Kong dataset — 1 257 files), and per-repository statistics (121 repos) are documented in **[docs/benchmark_results.md](docs/benchmark_results.md)**.

---

## Project Structure

```
GraphCreator/
├── src/
│   ├── parser.py                        # ASTManager / ParallelASTManager (tree-sitter)
│   ├── dapr_handler.py                  # Optional: FastAPI + Dapr pub/sub service entry point
│   ├── managers/
│   │   ├── cgp_worker.py                # _analyze_single() + @ray.remote analyze_file()
│   │   ├── ray_orchestrator.py          # Submits one Ray task per file
│   │   └── graph_manager.py             # Per-file pipeline: ASTInserter → SymbolBuilder → CPGBuilder
│   ├── builders/
│   │   ├── graph_collector.py           # Cross-file merge: spine / indexes / resolve / metrics / schema
│   │   ├── ast_inserter.py              # tree-sitter Tree → AST graph vertices/edges
│   │   └── local_output_builder.py      # In-memory graph accumulator per file
│   ├── structures/
│   │   └── local_symbol_table.py        # SymbolTable, Scope, ScopeStack
│   ├── builders/cpg/
│   │   ├── _cpg_base.py                 # Node/edge factory, scope stack
│   │   ├── _cpg_declarations.py         # Functions, variables, modules (mixin)
│   │   ├── _cpg_relations.py            # Calls, assignments, control flow (mixin)
│   │   └── lua_cpg_builder.py           # CPGBuilder — main entry point
│   ├── ast_metrics/                     # Per-file metrics: cyclomatic complexity, Halstead, LOC
│   ├── graph_metrics/                   # Project-level metrics: dependency, global vars
│   └── dto/edges.py                     # Edges enum — all permitted CPG edge types
├── benchmarks/
│   ├── runner.py                        # Single-dataset benchmark runner (Ray + sequential)
│   ├── runner_repos.py                  # Multi-repository sweep runner
│   ├── datasets.py                      # Dataset registry (ZIP paths)
│   ├── plots.py                         # Chart generation for Kong dataset
│   ├── plots_repos.py                   # Chart generation for repository dataset
│   └── results/                         # Saved JSON benchmark results
├── docs/
│   ├── technical_documentation.md       # Architecture, class API, data formats
│   └── benchmark_results.md             # Benchmark results and analysis
├── schema/                              # JSON Schema for CPG nodes and edges
├── tests/                               # Unit and integration tests
├── manifests/                           # Kubernetes / Dapr manifests
├── Dockerfile
└── requirements.txt
```

---

## Setup

### Prerequisites

- Python 3.11+
- Docker (optional, for Dapr service mode)

### Install

```bash
git clone <repo-url>
cd GraphCreator

python -m venv venv
source venv/bin/activate          # Linux / macOS
.\venv\Scripts\activate            # Windows

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## Usage

### Direct Python API

Run the full pipeline on a directory of Lua files without starting any service:

```python
import sys
sys.path.insert(0, "src")

from benchmarks.datasets import extract_dataset
from benchmarks.runner import run_benchmark_on_dir

extract_dir, files = extract_dataset("kong")   # or point to your own directory
result = run_benchmark_on_dir(extract_dir, files, dataset_name="kong", num_cpus=4)

print(f"KG nodes: {result.n_knowledge_nodes}, edges: {result.n_knowledge_edges}")
print(f"Total time: {result.time_total_s:.2f}s")
```

Access the `GraphCollector` object directly for the raw graph:

```python
import ray
from managers.ray_orchestrator import RayOrchestrator
from builders.graph_collector import GraphCollector

ray.init(num_cpus=4, runtime_env={"env_vars": {"PYTHONPATH": "src"}})
orchestrator = RayOrchestrator()
futures = orchestrator.distribute_work(files)   # files = [{"path": "/abs/path/file.lua"}, ...]
results = [r for r in ray.get(futures) if r is not None]

gc = GraphCollector()
gc.collect(results, extract_dir)

print(f"AST nodes: {len(gc._ast_nodes)}")
print(f"KG nodes:  {len(gc._knowledge_nodes)}")
print(f"KG edges:  {len(gc._knowledge_edges)}")
ray.shutdown()
```

---

## Benchmarks

Drop a Lua project ZIP into `benchmarks/data/` and register it in `benchmarks/datasets.py`, then:

```bash
# Sweep all CPU budgets on the 'kong' dataset
python -m benchmarks.runner --dataset kong --cpus 1 2 4 8

# Run across a folder of repositories
python -m benchmarks.runner_repos --repo-dir /path/to/repos --cpus 1 2 4

# Regenerate all charts from saved results
python -m benchmarks.plots
python -m benchmarks.plots_repos
```

Results are saved as JSON files in `benchmarks/results/`. Charts are saved to `benchmarks/figures/`.

See **[docs/benchmark_results.md](docs/benchmark_results.md)** for the full Kong dataset analysis (speedup curves, GraphCollector phase breakdown, per-file timing distributions, and 121-repository statistics).

---

## Tests

```bash
# All tests
pytest tests/ -v

# Integration tests only (Ray + GraphCollector pipeline)
pytest tests/test_ray.py -v

# Unit tests only (SymbolTable, scope lookup)
pytest tests/test_symbol_table.py -v

# With coverage
pytest --cov=src --cov-report=html
```

---

 ## Dapr Service Mode (optional)

The analyzer can also run as a Dapr-integrated FastAPI microservice that subscribes to a `parser-code-tasks` topic, downloads project ZIPs from a Graph Store Adapter, and publishes CPG results to `graph-updates`.

### Run locally (without Dapr)

```bash
cd src
python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080 --reload
```

Endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe |
| `/analyze` | POST | Synchronous analysis (development only) |
| `/dapr/subscribe` | GET | Dapr subscription config |
| `/parser-code-tasks` | POST | Receives Dapr CloudEvent messages |

### Run with Dapr sidecar

```bash
dapr run \
  --app-id lua-code-analyzer \
  --app-port 8080 \
  -- python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAY_ADDRESS` | *(auto)* | Ray cluster address; omit to start a local cluster |
| `APP_PORT` | `8080` | HTTP server port |
| `DAPR_HTTP_PORT` | `3500` | Dapr sidecar port |
| `PUBSUB_NAME` | `rabbitmq-pubsub` | Dapr pub/sub component name |
| `GRAPH_STORE_ADAPTER_APP_ID` | `graph-store-adapter` | Dapr app ID for ZIP downloads |
| `PYTHONPATH` | `/app/src` | Must include `src/` |

### Deploy to Kubernetes

```bash
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/rabbitmq.yaml
kubectl apply -f manifests/dapr-pubsub.yaml
kubectl apply -f manifests/raycluster.yaml
kubectl apply -f manifests/deployment.yaml
kubectl apply -f manifests/service.yaml
kubectl apply -f manifests/keda-scaledobject.yaml
```

A RabbitMQ Secret must exist before applying (see `docs/technical_documentation.md` § 9 for details).

---

## Schema

CPG output is validated against JSON Schema files in `schema/`:

| File | Description |
|------|-------------|
| `cpg.node.schema.json` | Schema for a single CPG node |
| `cpg.edge.schema.json` | Schema for a single CPG edge |
| `cpg.export.schema.json` | Schema for the full CPG export |

Validation runs automatically at the end of `GraphCollector.collect()` (random sample of 200 nodes).