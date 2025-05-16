# mcp_server/handlers/search.py
from typing import Dict, List, Any, Optional, Tuple
import logging

from mcp_server.config import settings
from mcp_server.db.queries import execute_search_query, execute_fallback_search, execute_category_boosted_search
from mcp_server.llm.ollama import OllamaClient
from mcp_server.utils.sql_parser import validate_sql, simplify_sql
from mcp_server.utils.response import format_search_results
from .context import ConversationContext, update_context_with_results

logger = logging.getLogger(__name__)

class SearchHandler:
    """Handler for search requests using LLM-to-SQL pipeline."""
    
    def __init__(self, sql_model: OllamaClient, response_model: OllamaClient):
        self.sql_model = sql_model
        self.response_model = response_model
    
    async def process_query(
        self, 
        query: str, 
        context: ConversationContext,
        db_schema: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Process a query through the LLM-to-SQL pipeline with fallbacks.
        Returns (response_text, results)
        """
        # Get query-specific context
        query_context = context.get_context_for_query(query)
        is_followup = query_context.get("is_followup", False)
        
        # Initialize response
        response_text = ""
        results = []
        
        try:
            # 1. Generate SQL using LLM
            if is_followup:
                generated_sql = await self.sql_model.generate_sql_with_context(
                    query, db_schema, query_context
                )
            else:
                generated_sql = await self.sql_model.generate_sql(query, db_schema)
            
            logger.debug(f"Generated SQL: {generated_sql}")
            
            # 2. Validate the SQL
            is_valid, validation_message = validate_sql(generated_sql)
            
            if is_valid:
                # 3. Execute the SQL
                results = await execute_search_query(generated_sql)
                
                # 4. If no results, try simplified SQL
                if not results:
                    simplified_sql = simplify_sql(generated_sql)
                    if simplified_sql != generated_sql:
                        logger.debug(f"Using simplified SQL: {simplified_sql}")
                        results = await execute_search_query(simplified_sql)
                
                # 5. If still no results, try fallback search
                if not results:
                    logger.debug("Using fallback search")
                    results = await execute_fallback_search(query)
                
                # 6. If still no results, try category-boosted search
                if not results:
                    logger.debug("Using category-boosted search")
                    results = await execute_category_boosted_search(query)
            else:
                # If SQL is invalid, skip to fallback
                logger.warning(f"Invalid SQL: {validation_message}")
                results = await execute_fallback_search(query)
            
            # Update context with results before generating response
            update_context_with_results(context, query, results)
            
            # Format response based on results
            if results:
                # Generate response using LLM
                if is_followup:
                    response_text = await self.response_model.generate_response_with_context(
                        query, results, query_context
                    )
                else:
                    response_text = await self.response_model.generate_response(query, results)
            else:
                response_text = format_search_results(query, [])
        
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            response_text = f"I encountered an error while searching for information about '{query}'. Please try rephrasing your question."
            results = []
        
        # Add the response to the context
        context.add_message("assistant", response_text)
        
        return response_text, results

# Create a singleton instance
search_handler = None

def get_search_handler(sql_model: OllamaClient, response_model: OllamaClient) -> SearchHandler:
    """Get or create the search handler singleton."""
    global search_handler
    if search_handler is None:
        search_handler = SearchHandler(sql_model, response_model)
    return search_handler