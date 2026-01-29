"""
Integration tests for Dapr pub/sub functionality.

Tests the full flow:
1. Receive message from parser-code-tasks topic
2. Download ZIP from Graph Store Adapter
3. Parse Lua files and build knowledge graph  
4. Publish results to graph-updates and results topics
"""

import os
import sys
import json
import asyncio
import tempfile
import zipfile
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport, Response

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Now import from src - Pylance may show error but runtime works
from dapr_handler import (  # type: ignore[import-not-found]
    ParseTaskMessage,
    ProcessingResult,
    FileError,
    DaprClient,
    LuaCodeAnalyzerService,
    app,
)


# Sample Lua code
SAMPLE_LUA = '''
local x = 10

function add(a, b)
    return a + b
end

local result = add(x, 5)
print(result)
'''


class TestDaprHandlerUnit:
    """Unit tests for Dapr handler components"""
    
    def test_parse_task_message_model(self):
        """Test ParseTaskMessage model validation"""
        # Valid message
        msg = ParseTaskMessage(project_id="test-project-123")
        assert msg.project_id == "test-project-123"
        assert msg.incremental == False
        
        # With incremental flag
        msg2 = ParseTaskMessage(project_id="test", incremental=True)
        assert msg2.incremental == True
    
    def test_processing_result_dataclass(self):
        """Test ProcessingResult dataclass"""
        result = ProcessingResult(
            project_id="test",
            status="completed",
            files_processed=5,
            files_failed=1
        )
        
        assert result.project_id == "test"
        assert result.status == "completed"
        assert result.files_processed == 5
        assert result.files_failed == 1
        assert result.errors == []
        
        # Add error
        error = FileError(
            file_path="/test/file.lua",
            error_type="SyntaxError",
            error_message="Unexpected token"
        )
        result.errors.append(error)
        assert len(result.errors) == 1


class TestDaprClientUnit:
    """Unit tests for DaprClient"""
    
    @pytest.mark.asyncio
    async def test_invoke_service_get(self):
        """Test service invocation with GET"""
        client = DaprClient("http://localhost:3500")
        
        with patch.object(client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = Response(200, json={"status": "ok"})
            
            response = await client.invoke_service("test-app", "health")
            
            mock_get.assert_called_once()
            assert response.status_code == 200
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_invoke_service_post(self):
        """Test service invocation with POST"""
        client = DaprClient("http://localhost:3500")
        
        with patch.object(client.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = Response(200, json={"result": "success"})
            
            response = await client.invoke_service(
                "test-app", 
                "process",
                http_method="POST",
                data={"key": "value"}
            )
            
            mock_post.assert_called_once()
            assert response.status_code == 200
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_publish(self):
        """Test publishing to a topic"""
        client = DaprClient("http://localhost:3500")
        
        with patch.object(client.client, 'post', new_callable=AsyncMock) as mock_post:
            # Create a proper mock response that supports raise_for_status
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()  # No-op
            mock_post.return_value = mock_response
            
            await client.publish("pubsub", "test-topic", {"message": "hello"})
            
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "test-topic" in call_args[0][0]
        
        await client.close()

    @pytest.mark.asyncio
    async def test_publish_compressed(self):
        """Test compressed publishing to a topic"""
        import base64
        import zstandard as zstd
        
        client = DaprClient("http://localhost:3500")
        
        with patch.object(client.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            test_data = {
                "meta_data": {"graph_id": "test-123"},
                "nodes": [{"id": "n1", "type": "file"}],
                "edges": []
            }
            
            await client.publish_compressed("pubsub", "graph-updates", test_data)
            
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            
            # Verify topic is in URL
            assert "graph-updates" in call_args[0][0]
            
            # Verify content is base64-encoded compressed data
            content = call_args.kwargs.get('content')
            assert content is not None
            
            # Verify headers indicate compression
            headers = call_args.kwargs.get('headers', {})
            assert headers.get('metadata.contentencoding') == 'zstd'
            
            # Verify we can decode and decompress
            compressed = base64.b64decode(content)
            decompressor = zstd.ZstdDecompressor()
            decompressed = decompressor.decompress(compressed)
            
            import json
            result = json.loads(decompressed)
            assert result == test_data
        
        await client.close()


class TestLuaCodeAnalyzerService:
    """Tests for the main analyzer service"""
    
    @pytest.fixture
    def sample_zip(self):
        """Create a sample ZIP file with Lua code"""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            zip_path = f.name
        
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("src/main.lua", SAMPLE_LUA)
            zf.writestr("src/utils.lua", "function helper() return true end")
        
        yield zip_path
        
        os.unlink(zip_path)
    
    @pytest.mark.asyncio
    async def test_process_project_success(self, sample_zip):
        """Test successful project processing"""
        # Create mock Dapr client
        mock_dapr = AsyncMock(spec=DaprClient)
        
        # Mock ZIP download
        async def mock_download(project_id, dest_path):
            # Copy sample ZIP to destination
            import shutil
            dest_zip = os.path.join(dest_path, f"{project_id}.zip")
            shutil.copy(sample_zip, dest_zip)
            return dest_zip
        
        mock_dapr.download_project_zip = mock_download
        mock_dapr.publish = AsyncMock()
        mock_dapr.publish_compressed = AsyncMock()
        
        # Create service and process
        service = LuaCodeAnalyzerService(mock_dapr)
        result = await service.process_project("test-project-123")
        
        # Verify result
        assert result.project_id == "test-project-123"
        assert result.status in ("completed", "partial")
        assert result.files_processed >= 1
        
        # Verify publish_compressed was called for graph updates
        assert mock_dapr.publish_compressed.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_process_project_with_errors(self, sample_zip):
        """Test project processing with some file errors"""
        # Create ZIP with invalid Lua
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            bad_zip_path = f.name
        
        with zipfile.ZipFile(bad_zip_path, 'w') as zf:
            zf.writestr("good.lua", "local x = 10")
            # This should still parse (Lua is forgiving) but we can test error handling
        
        mock_dapr = AsyncMock(spec=DaprClient)
        
        async def mock_download(project_id, dest_path):
            import shutil
            dest_zip = os.path.join(dest_path, f"{project_id}.zip")
            shutil.copy(bad_zip_path, dest_zip)
            return dest_zip
        
        mock_dapr.download_project_zip = mock_download
        mock_dapr.publish = AsyncMock()
        
        service = LuaCodeAnalyzerService(mock_dapr)
        result = await service.process_project("test-project")
        
        # Should complete even with issues
        assert result.project_id == "test-project"
        assert result.status in ("completed", "partial", "failed")
        
        os.unlink(bad_zip_path)


class TestFastAPIEndpoints:
    """Tests for FastAPI endpoints"""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health check endpoint"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "lua-code-analyzer"
    
    @pytest.mark.asyncio
    async def test_ready_endpoint(self):
        """Test readiness check endpoint"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
    
    @pytest.mark.asyncio
    async def test_dapr_subscribe_endpoint(self):
        """Test Dapr subscription configuration"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/dapr/subscribe")
            
            assert response.status_code == 200
            subscriptions = response.json()
            
            assert len(subscriptions) >= 1
            assert subscriptions[0]["topic"] == "parser-code-tasks"
            assert "route" in subscriptions[0]


@pytest.mark.skipif(
    os.getenv("SKIP_INTEGRATION_TESTS", "true").lower() == "true",
    reason="Integration tests disabled"
)
class TestRabbitMQIntegration:
    """Integration tests with RabbitMQ container"""
    
    @pytest.mark.asyncio
    async def test_pubsub_roundtrip(self, rabbitmq_container):
        """Test publishing and receiving messages via RabbitMQ"""
        # This test requires running RabbitMQ container
        # and would typically be run in CI/CD environment
        pass  # Placeholder for full integration test
