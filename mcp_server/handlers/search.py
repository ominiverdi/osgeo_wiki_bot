# mcp_server/handlers/search.py
from typing import Dict, List, Any, Optional, Tuple
import logging

from mcp_server.config import settings
from mcp_server.db.queries import execute_search_query
from mcp_server.llm.ollama import OllamaClient
from .context import ConversationContext, update_context_with_results
from .agentic import agentic_search, extract_sources

logger = logging.getLogger(__name__)


class SearchHandler:
    """Handler for search requests using agentic search."""
    
    def __init__(self, llm_client: OllamaClient, response_model: OllamaClient = None):
        self.llm_client = llm_client
        self.response_model = response_model or llm_client
    
    async def initialize(self):
        """Initialize the handler (placeholder for future needs)."""
        logger.info("Search handler initialized")
    
    async def process_query(
        self, 
        query: str, 
        context: ConversationContext
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Process a query using agentic search.
        
        Args:
            query: User's natural language query
            context: Conversation context
            
        Returns:
            Tuple of (response_text, sources)
        """
        logger.info(f"Processing query: {query}")
        
        try:
            # Run agentic search
            result = await agentic_search(
                llm_client=self.llm_client,
                db_execute_fn=self._execute_sql,
                user_query=query,
                max_iterations=3
            )
            
            # Extract sources from search history
            sources = extract_sources(result['search_history'], max_sources=3)
            
            # Log results
            logger.info(
                f"Completed in {result['iterations']} iterations, "
                f"{result['total_time_ms']:.0f}ms"
            )
            logger.info(f"Found {len(sources)} sources")
            
            # Update context with the final results
            if result['search_history']:
                last_search = result['search_history'][-1]
                if last_search['result_count'] > 0:
                    # Convert to format expected by update_context_with_results
                    results_for_context = []
                    for r in last_search['results']:
                        # Normalize result format
                        normalized = {
                            'id': r.get('source_page_id') or r.get('id', 0),
                            'title': r.get('source_page_title') or r.get('page_title') or r.get('title', ''),
                            'url': r.get('source_page_url') or r.get('wiki_url') or r.get('url', ''),
                            'chunk_text': r.get('chunk_text') or r.get('resume', '')[:200]
                        }
                        results_for_context.append(normalized)
                    
                    update_context_with_results(context, query, results_for_context)
            
            # Add response to context
            context.add_message("assistant", result['answer'])
            
            return result['answer'], sources
        
        except Exception as e:
            logger.error(f"Error in agentic search: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Fallback response
            response_text = (
                f"I encountered an error while searching for information about '{query}'. "
                "Please try rephrasing your question."
            )
            context.add_message("assistant", response_text)
            
            return response_text, []
    
    async def _execute_sql(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results.
        
        Args:
            sql: SQL query string
            
        Returns:
            List of result dicts
        """
        try:
            results = await execute_search_query(sql)
            return results
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            logger.error(f"SQL was: {sql[:200]}")
            return []


# Create a singleton instance
search_handler = None


def get_search_handler(llm_client: OllamaClient, response_model: OllamaClient = None) -> SearchHandler:
    """Get or create the search handler singleton."""
    global search_handler
    if search_handler is None:
        search_handler = SearchHandler(llm_client, response_model)
    return search_handler