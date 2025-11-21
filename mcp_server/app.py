# mcp_server/app.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import logging
import uuid

from mcp_server.config import settings
from mcp_server.db.connection import test_connection
from mcp_server.llm.ollama import LLMClient
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

class MCPSource(BaseModel):
    title: str
    url: str

class MCPResponse(BaseModel):
    message: MCPMessage
    context: Optional[Dict[str, Any]] = None
    sources: Optional[List[MCPSource]] = None
    metadata: Optional[Dict[str, Any]] = None

# Initialize LLM client
llm_client = LLMClient(model=settings.LLM_MODEL)

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
        
        logger.info("MCP server startup complete")
    except Exception as e:
        logger.error(f"Startup error: {e}")

@app.get("/")
async def root():
    """Root endpoint - server health check."""
    return {
        "status": "ok",
        "service": "OSGeo Wiki MCP Server",
        "version": "2.0-agentic"
    }

@app.post("/v1", response_model=MCPResponse)
async def mcp_endpoint(request: MCPRequest):
    """Main MCP protocol endpoint with agentic search."""
    # Extract the latest user message
    user_messages = [msg for msg in request.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    
    user_query = user_messages[-1].content
    
    # Initialize or load context
    context = create_context(request.context)
    if not context.conversation_id:
        context.conversation_id = str(uuid.uuid4())
    
    try:
        # Process the query using the agentic search handler
        search_handler = get_search_handler(llm_client)
        response_text, sources = await search_handler.process_query(user_query, context)
        
        # Build metadata
        metadata = {
            "search_type": "agentic",
            "sources_count": len(sources)
        }
        
        # Return MCP-compliant response with sources
        return MCPResponse(
            message=MCPMessage(role="assistant", content=response_text),
            context=context.to_dict(),
            sources=[MCPSource(**s) for s in sources] if sources else None,
            metadata=metadata
        )
    
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Return error response
        return MCPResponse(
            message=MCPMessage(
                role="assistant",
                content="I encountered an error processing your query. Please try again."
            ),
            context=context.to_dict(),
            sources=None,
            metadata={"error": str(e)}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app", 
        host=settings.HOST, 
        port=settings.PORT,
        reload=settings.DEBUG
    )