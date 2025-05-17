# mcp_server/handlers/search.py
from typing import Dict, List, Any, Optional, Tuple
import logging
import re

from mcp_server.config import settings
from mcp_server.db.queries import execute_keyword_search, execute_fallback_search, get_keyword_cloud, get_top_categories
from mcp_server.llm.ollama import OllamaClient
from mcp_server.utils.response import format_search_results
from .context import ConversationContext, update_context_with_results

logger = logging.getLogger(__name__)

class SearchHandler:
    """Handler for search requests using keyword extraction."""
    
    def __init__(self, llm_client: OllamaClient, response_model: OllamaClient = None):
        self.llm_client = llm_client
        self.response_model = response_model or llm_client
        self.keyword_cloud = None
        self.categories = None
    
    async def initialize(self):
        """Initialize the handler with keyword cloud and categories."""
        if self.keyword_cloud is None:
            self.keyword_cloud = await get_keyword_cloud()
            logger.info(f"Generated keyword cloud with {len(self.keyword_cloud.split())} terms")
        
        if self.categories is None:
            self.categories = await get_top_categories()
            logger.info(f"Retrieved {len(self.categories)} top categories")
    
    async def process_query(
        self, 
        query: str, 
        context: ConversationContext
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Process a query using keyword extraction and search.
        Returns (response_text, results)
        """
        # Initialize if needed
        await self.initialize()
        
        # Get query-specific context
        query_context = context.get_context_for_query(query)
        is_followup = query_context.get("is_followup", False)
        
        # Initialize response
        response_text = ""
        results = []
        
        try:
            # Normal flow: Extract keywords from query
            logger.info(f"Extracting keywords for query: {query}")
            keywords = await self.llm_client.extract_keywords(
                query,
                self.keyword_cloud,
                self.categories
            )
            
            logger.info(f"LLM extracted keywords: {keywords}")
            
            # Execute search with keywords
            results = await execute_keyword_search(keywords)
            
            # Log search results
            logger.info(f"Search found {len(results)} results")
            if results and len(results) > 0:
                logger.info(f"Top result: {results[0].get('title')} - {results[0].get('url')}")
        
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            response_text = f"I encountered an error while searching for information about '{query}'. Please try rephrasing your question."
            results = []
        
        # Add the response to the context
        context.add_message("assistant", response_text)
        
        return response_text, results

# Create a singleton instance
search_handler = None

def get_search_handler(llm_client: OllamaClient, response_model: OllamaClient = None) -> SearchHandler:
    """Get or create the search handler singleton."""
    global search_handler
    if search_handler is None:
        search_handler = SearchHandler(llm_client, response_model)
    return search_handler