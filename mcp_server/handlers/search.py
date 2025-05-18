# mcp_server/handlers/search.py
from typing import Dict, List, Any, Optional, Tuple
import logging
import re

from mcp_server.config import settings
from mcp_server.db.queries import execute_keyword_search, execute_fallback_search, get_keyword_cloud, get_top_categories
from mcp_server.llm.ollama import OllamaClient
from mcp_server.utils.response import format_search_results
from .context import ConversationContext, update_context_with_results
from mcp_server.llm.query_alternatives import extract_query_alternatives
from mcp_server.db.queries import execute_alternative_search
from mcp_server.llm.response_gen import create_response_generation_prompt


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
        """Process a query using query alternatives approach."""
        # Initialize if needed
        await self.initialize()
        
        # Get query-specific context
        query_context = context.get_context_for_query(query)
        is_followup = query_context.get("is_followup", False)
        
        # Initialize response
        response_text = ""
        results = []
        
        try:
            # Generate alternative search queries
            # IMPORTANT FIX: Use self.keyword_cloud and self.categories
            logger.info(f"Generating query alternatives for: {query}")
            alternatives = await extract_query_alternatives(
                self.llm_client,
                query,
                self.keyword_cloud,  # Use instance variable
                self.categories      # Use instance variable
            )
            
            logger.info(f"Generated alternatives: {alternatives}")
            
            # Execute search with alternatives
            results = await execute_alternative_search(alternatives)
            
            # Log search results
            logger.info(f"Search found {len(results)} results")
            if results and len(results) > 0:
                logger.info(f"Top result: {results[0].get('title')} - {results[0].get('url')}")
                
                # Generate a response using the results
                if is_followup:
                    response_text = await self.response_model.generate_response_with_context(
                        query, results, query_context
                    )
                else:
                    # Use the correct function to generate a response
                    response_text = await self.response_model.generate(
                        prompt=create_response_generation_prompt(query, results),
                        temperature=settings.RESPONSE_TEMPERATURE
                    )
            else:
                response_text = f"I couldn't find any information about '{query}' in the OSGeo wiki. Please try rephrasing your question."
        
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            import traceback
            logger.error(traceback.format_exc())  # Add traceback for more details
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