"""
Test fixtures for Lua Code Analyzer tests.

Provides:
- RabbitMQ testcontainer for integration testing
- Mock Graph Store Adapter server
- Sample Lua files for testing
"""

import os
import sys
import json
import asyncio
import tempfile
import zipfile
from typing import Generator, AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ============================================================================
# Sample Lua Code for Testing
# ============================================================================

SAMPLE_LUA_SIMPLE = '''
-- Simple Lua file for testing
local x = 10
local y = 20

function add(a, b)
    return a + b
end

local result = add(x, y)
print(result)
'''

SAMPLE_LUA_MODULE = '''
-- Module with require
module("mymodule")

local utils = require("utils")

function greet(name)
    return "Hello, " .. name
end

function calculate(x)
    if x > 0 then
        return x * 2
    else
        return 0
    end
end

return {
    greet = greet,
    calculate = calculate
}
'''

SAMPLE_LUA_COMPLEX = '''
-- Complex Lua file with control flow
local config = require("config")

local function processItem(item)
    local result = {}
    
    if item.type == "a" then
        result.value = item.data * 2
    elseif item.type == "b" then
        result.value = item.data + 10
    else
        result.value = item.data
    end
    
    for i = 1, 10 do
        result[i] = i * item.data
    end
    
    while result.value > 100 do
        result.value = result.value / 2
    end
    
    return result
end

local items = {
    {type = "a", data = 5},
    {type = "b", data = 15},
}

for _, item in ipairs(items) do
    local processed = processItem(item)
    print(processed.value)
end
'''


@pytest.fixture
def sample_lua_files() -> dict:
    """Return sample Lua code strings"""
    return {
        "simple.lua": SAMPLE_LUA_SIMPLE,
        "mymodule.lua": SAMPLE_LUA_MODULE,
        "complex.lua": SAMPLE_LUA_COMPLEX,
    }


@pytest.fixture
def temp_lua_project(sample_lua_files) -> Generator[str, None, None]:
    """Create a temporary directory with sample Lua files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create subdirectory
        src_dir = os.path.join(tmpdir, "src")
        os.makedirs(src_dir)
        
        # Write Lua files
        for filename, content in sample_lua_files.items():
            filepath = os.path.join(src_dir, filename)
            with open(filepath, "w") as f:
                f.write(content)
        
        yield tmpdir


@pytest.fixture
def temp_lua_project_zip(temp_lua_project) -> Generator[str, None, None]:
    """Create a ZIP archive of the sample Lua project"""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        zip_path = f.name
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_lua_project):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_lua_project)
                zipf.write(file_path, arcname)
    
    yield zip_path
    
    # Cleanup
    if os.path.exists(zip_path):
        os.unlink(zip_path)


# ============================================================================
# Mock Graph Store Adapter
# ============================================================================

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

def create_mock_graph_store_adapter(zip_path: str) -> FastAPI:
    """Create a mock Graph Store Adapter FastAPI app"""
    app = FastAPI()
    
    received_graphs = []
    received_results = []
    
    @app.get("/health")
    async def health():
        return {"status": "healthy"}
    
    @app.get("/projects/{project_id}/source/zip")
    async def get_project_zip(project_id: str):
        """Return the test ZIP file"""
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{project_id}.zip"
        )
    
    @app.get("/projects/{project_id}/source")
    async def get_project_structure(project_id: str):
        """Return mock project structure"""
        return {
            "files": [
                {"path": "src/simple.lua", "type": "file"},
                {"path": "src/mymodule.lua", "type": "file"},
                {"path": "src/complex.lua", "type": "file"},
            ]
        }
    
    # Store reference to received data for assertions
    app.state.received_graphs = received_graphs
    app.state.received_results = received_results
    
    return app


@pytest.fixture
def mock_graph_store_app(temp_lua_project_zip) -> FastAPI:
    """Create mock Graph Store Adapter app"""
    return create_mock_graph_store_adapter(temp_lua_project_zip)


# ============================================================================
# RabbitMQ Testcontainer
# ============================================================================

try:
    from testcontainers.rabbitmq import RabbitMqContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False


@pytest.fixture(scope="session")
def rabbitmq_container():
    """Start RabbitMQ container for integration tests"""
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not available")
    
    container = RabbitMqContainer("rabbitmq:3.12-management")
    container.start()
    
    yield container
    
    container.stop()


@pytest.fixture
def rabbitmq_connection_string(rabbitmq_container) -> str:
    """Get RabbitMQ connection string"""
    return rabbitmq_container.get_connection_url()


# ============================================================================
# Application Fixtures
# ============================================================================

@pytest.fixture
def graph_output_builder():
    """Create a fresh GraphOutputBuilder instance"""
    from graph_builder.output_builder import GraphOutputBuilder  # type: ignore[import-not-found]
    return GraphOutputBuilder()


@pytest.fixture
def ast_manager():
    """Create a fresh ASTManager instance"""
    from code_analyzer.parse_code import ASTManager  # type: ignore[import-not-found]
    manager = ASTManager()
    manager.clear()  # type: ignore[attr-defined]
    return manager


# ============================================================================
# Async Test Helpers
# ============================================================================

@pytest.fixture
def event_loop():
    """Create an event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_client(mock_graph_store_app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing"""
    transport = ASGITransport(app=mock_graph_store_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
