"""
Dapr Handler - Main entry point for the Lua Code Analyzer service.

This FastAPI application:
1. Subscribes to 'parser-code-tasks' topic via Dapr pub/sub
2. Downloads project ZIP from Graph Store Adapter
3. Parses Lua files and builds knowledge graph
4. Publishes results to 'graph-updates' and 'results' topics
"""

import os
import json
import shutil
import tempfile
import zipfile
import logging
import datetime
import base64
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from contextlib import asynccontextmanager

import aiofiles
import httpx
import jsonschema
import zstandard as zstd
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from code_analyzer.parse_code import ASTManager
from file_system_analyzer.project_structure_analyzer import analyze_project_structure
from graph_builder.output_builder import GraphOutputBuilder
from graph_builder.ast_inserter import ASTInserter
from graph_builder.graph_queries import GraphQueries


# ============================================================================
# Configuration
# ============================================================================

DAPR_HTTP_PORT = os.getenv("DAPR_HTTP_PORT", "3500")
DAPR_BASE_URL = f"http://localhost:{DAPR_HTTP_PORT}"
GRAPH_STORE_ADAPTER_APP_ID = os.getenv("GRAPH_STORE_ADAPTER_APP_ID", "graph-store-adapter")
PUBSUB_NAME = os.getenv("PUBSUB_NAME", "rabbitmq-pubsub")

# Default schema path (absolute for workspace, or relative for container)
CPG_SCHEMA_PATH = os.getenv("CPG_SCHEMA_PATH", "/var/home/roman/Projects/BcArchitectureC4/schema/v1/cpg.export.schema.json")
if not os.path.exists(CPG_SCHEMA_PATH):
    # Try relative paths (../ for container, ../../ for local dev)
    for rel_path in ["../schema/v1/cpg.export.schema.json", "../../schema/v1/cpg.export.schema.json"]:
        potential_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
        if os.path.exists(potential_path):
            CPG_SCHEMA_PATH = potential_path
            break

# Topics
TOPIC_PARSER_CODE_TASKS = "parser-code-tasks"
TOPIC_GRAPH_UPDATES = "graph-updates"
TOPIC_RESULTS = "results"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class ParseTaskMessage(BaseModel):
    """Message received from parser-code-tasks topic"""
    project_id: str
    # Optional additional configuration
    incremental: bool = False


@dataclass
class FileError:
    """Error information for a single file"""
    file_path: str
    error_type: str
    error_message: str


@dataclass
class ProcessingResult:
    """Result of processing a project"""
    project_id: str
    status: str  # "completed", "partial", "failed"
    files_processed: int = 0
    files_failed: int = 0
    errors: List[FileError] = field(default_factory=list)
    message: Optional[str] = None


# ============================================================================
# Dapr Client
# ============================================================================

class DaprClient:
    """Simple Dapr HTTP client for service invocation and pub/sub"""
    
    def __init__(self, base_url: str = DAPR_BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 min timeout for large projects
    
    async def close(self):
        await self.client.aclose()
    
    async def invoke_service(self, app_id: str, method: str, 
                            http_method: str = "GET",
                            data: Optional[Dict] = None,
                            params: Optional[Dict] = None) -> httpx.Response:
        """Invoke a service method via Dapr service invocation"""
        url = f"{self.base_url}/v1.0/invoke/{app_id}/method/{method}"
        
        if http_method.upper() == "GET":
            response = await self.client.get(url, params=params)
        elif http_method.upper() == "POST":
            response = await self.client.post(url, json=data, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {http_method}")
        
        return response
    
    async def publish(self, pubsub_name: str, topic: str, data: Dict[str, Any]):
        """Publish a message to a topic via Dapr pub/sub"""
        url = f"{self.base_url}/v1.0/publish/{pubsub_name}/{topic}"
        response = await self.client.post(url, json=data)
        response.raise_for_status()
        return response
    
    async def publish_compressed(self, pubsub_name: str, topic: str, data: Dict[str, Any]):
        """
        Publish a compressed message to a topic via Dapr pub/sub.
        
        Uses zstd compression for efficient transfer of large graph payloads.
        The message is wrapped in an envelope with encoding info since Dapr
        RabbitMQ pubsub doesn't preserve HTTP metadata.
        """
        # Serialize to JSON
        json_bytes = json.dumps(data, separators=(',', ':')).encode('utf-8')
        original_size = len(json_bytes)
        
        # Compress with zstd
        compressor = zstd.ZstdCompressor(level=3)
        compressed = compressor.compress(json_bytes)
        compressed_size = len(compressed)
        
        # Base64 encode for safe transport
        encoded = base64.b64encode(compressed).decode('ascii')
        
        # Wrap in envelope with encoding info (RabbitMQ doesn't preserve HTTP metadata)
        envelope = {
            "encoding": "zstd+base64",
            "data": encoded
        }
        
        # Publish envelope as JSON
        url = f"{self.base_url}/v1.0/publish/{pubsub_name}/{topic}"
        response = await self.client.post(
            url,
            json=envelope,
        )
        response.raise_for_status()
        
        logger.info(
            f"Published compressed message: {original_size} -> {compressed_size} bytes "
            f"({compressed_size / original_size * 100:.1f}% of original)"
        )
        return response
    
    async def download_project_zip(self, project_id: str, dest_path: str) -> str:
        """Download project ZIP from Graph Store Adapter"""
        # Storage adapter uses query parameter for project_id
        url = f"{self.base_url}/v1.0/invoke/{GRAPH_STORE_ADAPTER_APP_ID}/method/projects/source/zip?project_id={project_id}"
        
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            
            zip_path = os.path.join(dest_path, f"{project_id}.zip")
            async with aiofiles.open(zip_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    await f.write(chunk)
        
        return zip_path


# ============================================================================
# Code Analyzer Service
# ============================================================================

class LuaCodeAnalyzerService:
    """Main service for analyzing Lua code and building knowledge graphs"""
    
    def __init__(self, dapr_client: DaprClient):
        self.dapr = dapr_client
        self.ast_manager: ASTManager = ASTManager()
    
    def _validate_cpg(self, data: Dict[str, Any]):
        """Validate CPG data against JSON schema"""
        if not os.path.exists(CPG_SCHEMA_PATH):
            logger.warning(f"Schema file not found at {CPG_SCHEMA_PATH}. Skipping validation.")
            return

        try:
            with open(CPG_SCHEMA_PATH, "r") as f:
                schema = json.load(f)
            
            # The export schema references node and edge schemas via relative paths.
            # The $id in the schemas (e.g., "schema/v1/cpg.node.schema.json") requires
            # the base URI to be the root directory containing the 'schema' folder.
            schema_dir = os.path.dirname(CPG_SCHEMA_PATH)
            base_dir = os.path.dirname(os.path.dirname(schema_dir))
            resolver = jsonschema.RefResolver(
                base_uri=f"file://{base_dir}/",
                referrer=schema
            )
            
            jsonschema.validate(instance=data, schema=schema, resolver=resolver)
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"CPG Validation Error: {e.message}")
            raise RuntimeError(f"CPG Validation Failed: {e.message}")
        except Exception as e:
            logger.error(f"Error during CPG validation: {e}")
            raise

    async def process_project(self, project_id: str) -> ProcessingResult:
        """
        Process a complete project:
        1. Download ZIP from Graph Store Adapter
        2. Extract and analyze all .lua files
        3. Build knowledge graph
        4. Publish results
        """
        result = ProcessingResult(project_id=project_id, status="completed")
        temp_dir = None
        
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix=f"lua-analyzer-{project_id}-")
            logger.info(f"Processing project {project_id} in {temp_dir}")
            
            # Download and extract ZIP
            zip_path = await self.dapr.download_project_zip(project_id, temp_dir)
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            logger.info(f"Extracted project to {extract_dir}")
            
            # Clear AST manager for new project
            self.ast_manager.clear()  # type: ignore[attr-defined]
            
            # Analyze project structure
            project_items = analyze_project_structure(extract_dir)
            lua_files = [item for item in project_items if item["type"] == "file"]
            
            logger.info(f"Found {len(lua_files)} Lua files to analyze")
            
            # Initialize graph builder
            graph_builder = GraphOutputBuilder()
            ast_inserter = ASTInserter(graph_builder)
            
            # Insert directory structure
            ast_inserter.insert_dir_struct(project_items)
            
            # Parse each Lua file
            for file_item in lua_files:
                file_path = file_item["path"]
                try:
                    ast = self.ast_manager.parse(file_path)
                    ast_inserter.insert_node(ast.root_node, file=file_path)
                    result.files_processed += 1
                    logger.debug(f"Parsed: {file_path}")
                except Exception as e:
                    error = FileError(
                        file_path=file_path,
                        error_type=type(e).__name__,
                        error_message=str(e)
                    )
                    result.errors.append(error)
                    result.files_failed += 1
                    logger.warning(f"Failed to parse {file_path}: {e}")
            
            # Build knowledge graph
            graph_queries = GraphQueries(graph_builder)
            graph_queries.build_KG()
            
            # 1. Export original format (for comparison/legacy)
            legacy_graph_data = graph_builder.export_all()
            legacy_graph_data["project_id"] = project_id
            
            # Save legacy copy to /tmp (avoid read-only filesystem in container)
            legacy_copy_path = os.path.join(tempfile.gettempdir(), f"legacy_graph_{project_id}.json")
            with open(legacy_copy_path, "w") as f:
                json.dump(legacy_graph_data, f, indent=2)
            logger.info(f"Saved legacy graph copy to {legacy_copy_path}")

            # 2. Export new CPG v1 format
            cpg_v1_data = graph_builder.export_cpg_v1(project_id)
            
            # Save CPG v1 copy to /tmp
            cpg_copy_path = os.path.join(tempfile.gettempdir(), f"cpg_v1_{project_id}.json")
            with open(cpg_copy_path, "w") as f:
                json.dump(cpg_v1_data, f, indent=2)
            logger.info(f"Saved CPG v1 graph copy to {cpg_copy_path}")

            # 3. Validate against schema
            self._validate_cpg(cpg_v1_data)
            logger.info(f"CPG v1 data validated successfully for project {project_id}")
            
            # 4. Publish the export in the CPG v1 schema (meta_data/nodes/edges)
            # Use compressed publish for efficient transfer of large graphs
            await self.dapr.publish_compressed(PUBSUB_NAME, TOPIC_GRAPH_UPDATES, cpg_v1_data)
            logger.info(
                f"Published CPG v1 export for project {project_id} ("
                f"{len(cpg_v1_data.get('nodes', []))} nodes, {len(cpg_v1_data.get('edges', []))} edges)"
            )
            
            # Determine final status
            if result.files_failed > 0:
                if result.files_processed > 0:
                    result.status = "partial"
                    result.message = f"Completed with {result.files_failed} errors"
                else:
                    result.status = "failed"
                    result.message = "All files failed to parse"
            else:
                result.message = f"Successfully processed {result.files_processed} files"
            
        except Exception as e:
            logger.error(f"Failed to process project {project_id}: {e}", exc_info=True)
            result.status = "failed"
            result.message = str(e)
        
        finally:
            # Cleanup temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup {temp_dir}: {e}")
        
        return result


# ============================================================================
# FastAPI Application
# ============================================================================

dapr_client: Optional[DaprClient] = None
analyzer_service: Optional[LuaCodeAnalyzerService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global dapr_client, analyzer_service
    
    dapr_client = DaprClient()
    analyzer_service = LuaCodeAnalyzerService(dapr_client)
    logger.info("Lua Code Analyzer service started")
    
    yield
    
    if dapr_client:
        await dapr_client.close()
    logger.info("Lua Code Analyzer service stopped")


app = FastAPI(
    title="Lua Code Analyzer",
    description="Dapr-based service for analyzing Lua source code and building knowledge graphs",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# Dapr Pub/Sub Subscription
# ============================================================================

@app.get("/dapr/subscribe")
async def subscribe():
    """
    Dapr subscription configuration.
    Tells Dapr which topics this service subscribes to.
    """
    subscriptions = [
        {
            "pubsubname": PUBSUB_NAME,
            "topic": TOPIC_PARSER_CODE_TASKS,
            "route": f"/{TOPIC_PARSER_CODE_TASKS}"
        }
    ]
    return JSONResponse(content=subscriptions)


@app.post(f"/{TOPIC_PARSER_CODE_TASKS}")
async def handle_parse_task(request: Request):
    """
    Handle incoming parse task from Dapr pub/sub.
    
    CloudEvents format from Dapr:
    {
        "specversion": "1.0",
        "type": "...",
        "source": "...",
        "id": "...",
        "data": {
            "project_id": "..."
        }
    }
    """
    try:
        body = await request.json()
        logger.info(f"Received parse task: {json.dumps(body, indent=2)}")
        
        # Extract data from CloudEvents format
        if "data" in body:
            data = body["data"]
        else:
            data = body
        
        task = ParseTaskMessage(**data)
        
        if analyzer_service is None:
            raise RuntimeError("Service not initialized")
        
        # Process the project
        result = await analyzer_service.process_project(task.project_id)
        
        # Publish result to results topic
        result_dict = asdict(result)
        result_dict["errors"] = [asdict(e) for e in result.errors]
        
        if dapr_client is None:
            raise RuntimeError("Dapr client not initialized")
        
        await dapr_client.publish(PUBSUB_NAME, TOPIC_RESULTS, result_dict)
        logger.info(f"Published result for project {task.project_id}: {result.status}")
        
        # Return success to acknowledge message
        return JSONResponse(content={"status": "SUCCESS"})
    
    except Exception as e:
        logger.error(f"Error handling parse task: {e}", exc_info=True)
        # Return RETRY to have Dapr retry the message
        return JSONResponse(
            content={"status": "RETRY", "message": str(e)},
            status_code=500
        )


# ============================================================================
# Health Endpoints
# ============================================================================

@app.get("/health")
async def health():
    """Health check endpoint for Kubernetes probes"""
    return {"status": "healthy", "service": "lua-code-analyzer"}


@app.get("/ready")
async def ready():
    """Readiness check endpoint"""
    # Could add checks for dependencies here
    return {"status": "ready"}


# ============================================================================
# Debug/Admin Endpoints (optional, for development)
# ============================================================================

@app.post("/analyze")
async def analyze_sync(request: Request):
    """
    Synchronous analyze endpoint for testing.
    Not used in production - tasks come via pub/sub.
    """
    if analyzer_service is None:
        raise RuntimeError("Service not initialized")
    
    body = await request.json()
    task = ParseTaskMessage(**body)
    
    result = await analyzer_service.process_project(task.project_id)
    result_dict = asdict(result)
    result_dict["errors"] = [asdict(e) for e in result.errors]
    
    return JSONResponse(content=result_dict)


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("APP_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
