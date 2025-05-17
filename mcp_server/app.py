# Update mcp_server/app.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import logging
import uuid

from mcp_server.config import settings
from mcp_server.db.connection import test_connection
from mcp_server.llm.ollama import OllamaClient
from mcp_server.handlers.context import create_context
from mcp_server.handlers.search import get_search_handler

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="OSGeo Wiki MCP Server")

# Define Pydantic models for MCP protocol
class MCPMessage(BaseModel):
    role: str
    content: str

class MCPRequest(BaseModel):
    messages: List[MCPMessage]
    context: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    message: MCPMessage
    context: Optional[Dict[str, Any]] = None

# Initialize Ollama client
llm_client = OllamaClient(model=settings.LLM_MODEL)

@app.on_event("startup")
async def startup_event():
    """Run startup tasks."""
    # Test database connection
    try:
        version = test_connection()
        logger.info(f"Connected to database: {version}")
        
        # Initialize search handler
        search_handler = get_search_handler(llm_client)
        await search_handler.initialize()
    except Exception as e:
        logger.error(f"Database connection error: {e}")

@app.get("/")
async def root():
    """Root endpoint - server health check."""
    return {"status": "ok", "service": "OSGeo Wiki MCP Server"}

@app.post("/v1", response_model=MCPResponse)
async def mcp_endpoint(request: MCPRequest):
    """Main MCP protocol endpoint."""
    # Extract the latest user message
    user_messages = [msg for msg in request.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    
    user_query = user_messages[-1].content
    
    # Initialize or load context
    context = create_context(request.context)
    if not context.conversation_id:
        context.conversation_id = str(uuid.uuid4())
    
    # Process the query using the search handler
    search_handler = get_search_handler(llm_client)
    response_text, _ = await search_handler.process_query(user_query, context)
    
    # Return MCP-compliant response
    return MCPResponse(
        message=MCPMessage(role="assistant", content=response_text),
        context=context.to_dict()
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app", 
        host=settings.HOST, 
        port=settings.PORT,
        reload=settings.DEBUG
    )