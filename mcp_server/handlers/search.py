# mcp_server/handlers/search.py
from typing import Dict, List, Any, Optional, Tuple
import logging

from mcp_server.config import settings
from mcp_server.db.queries import execute_search_query
from mcp_server.llm.ollama import LLMClient
from .context import ConversationContext, update_context_with_results
from .agentic import agentic_search, extract_sources
from mcp_server.llm.classification import classify_query

logger = logging.getLogger(__name__)


class SearchHandler:
    """Handler for search requests using agentic search."""
    
    def __init__(self, llm_client: LLMClient, response_model: LLMClient = None):
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

        # Classify query ONCE - get language and OSGeo relevance
        detected_lang = 'en'  # Default fallback
        is_osgeo = True  # Default to proceeding with search if classification fails
        
        try:
            classification = await classify_query(query)
            detected_lang = classification['language']
            is_osgeo = classification['is_osgeo']
            logger.info(f"Query classification: language={detected_lang}, is_osgeo={is_osgeo}")
        except Exception as e:
            logger.warning(f"Classification failed, using defaults (lang=en, is_osgeo=true): {e}")
        
        # If not OSGeo-related, return redirect message in detected language
        if not is_osgeo:
            logger.info(f"Non-OSGeo query detected, generating redirect in {detected_lang}")
            redirect_msg = await self._generate_redirect_message(detected_lang)
            logger.debug(f"Redirect message generated: {redirect_msg[:100]}...")
            context.add_message("assistant", redirect_msg)
            return redirect_msg, []
        
        # OSGeo query - proceed with agentic search
        logger.info(f"OSGeo query confirmed, proceeding with agentic search in {detected_lang}")
        
        try:
            # Run agentic search with language parameter
            result = await agentic_search(
                llm_client=self.llm_client,
                db_execute_fn=self._execute_sql,
                user_query=query,
                max_iterations=3,
                response_language=detected_lang  # PASS LANGUAGE HERE
            )
            
            # Extract sources from search history
            if result.get('success', True):
                sources = extract_sources(result['search_history'], max_sources=3)
            else:
                sources = []
            
            # Log results
            logger.info(
                f"Completed in {result['iterations']} iterations, "
                f"{result['total_time_ms']:.0f}ms"
            )
            logger.info(f"Found {len(sources)} sources")
            logger.debug(f"Answer preview: {result['answer'][:100]}...")
            
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
            
            # Fallback response in detected language
            logger.info(f"Generating fallback error message in {detected_lang}")
            fallback_prompt = f"""You are a helpful assistant. Respond in {detected_lang} language.

There was an error searching for the user's query. Write a brief message:
- Tell them there was an error
- Ask them to try rephrasing

IMPORTANT:
- Write ONLY plain text, NO code, NO formatting, NO markdown
- Keep it brief (1-2 sentences)

Message:"""
            
            try:
                response_text = await self.llm_client.generate(
                    prompt=fallback_prompt,
                    temperature=0.7,
                    max_tokens=100
                )
                response_text = response_text.strip()
            except:
                # Ultimate fallback
                response_text = f"I encountered an error while searching for information about '{query}'. Please try rephrasing your question."
            
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
    
    async def _generate_redirect_message(self, lang: str) -> str:
        """Generate polite redirect message using LLM in detected language."""
    
        prompt = f"""You are a helpful assistant. Respond in language code: {lang}

    Write a friendly message (first person) explaining:
- I specialize in OSGeo questions (projects like QGIS, GDAL, PostGIS, events like FOSS4G)
- Please ask me about OSGeo topics

IMPORTANT: 
- Use first person ("I specialize", not "You specialize")
- Write ONLY plain text, NO code, NO formatting
- Keep it brief (2-3 sentences)

    Message:"""
        
        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                temperature=0.7,
                max_tokens=200
            )
            return response.strip()
        except Exception as e:
            logger.error(f"Failed to generate redirect message: {e}")
            # Fallback English only
            return "I specialize in answering questions about OSGeo projects and the geospatial community. Try asking about QGIS, GDAL, PostGIS, or FOSS4G!"



# Create a singleton instance
search_handler = None


def get_search_handler(llm_client: LLMClient, response_model: LLMClient = None) -> SearchHandler:
    """Get or create the search handler singleton."""
    global search_handler
    if search_handler is None:
        search_handler = SearchHandler(llm_client, response_model)
    return search_handler