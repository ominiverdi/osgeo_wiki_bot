# mcp_server/llm/ollama.py (updated)
import httpx
from typing import Dict, List, Any, Optional

from ..config import settings
from .sql_gen import (
    create_sql_generation_prompt, 
    create_context_aware_sql_prompt,
    extract_sql_from_response
)
from .response_gen import (
    create_response_generation_prompt,
    create_context_aware_response_prompt
)

class OllamaClient:
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model
        self.generate_endpoint = f"{self.base_url}/api/generate"
    
    async def generate(self, 
                      prompt: str, 
                      model: Optional[str] = None,
                      temperature: float = 0.7,
                      max_tokens: int = 2048) -> str:
        """Generate text using Ollama API."""
        model_to_use = model or self.model
        if not model_to_use:
            raise ValueError("Model name must be provided")
            
        payload = {
            "model": model_to_use,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.generate_endpoint,
                json=payload,
                timeout=60.0  # Longer timeout for model generation
            )
            
            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text}")
                
            result = response.json()
            return result["response"]
    
    async def generate_sql(self, query: str, schema: str) -> str:
        """Generate SQL from natural language query."""
        prompt = create_sql_generation_prompt(query, schema)
        result = await self.generate(
            prompt=prompt,
            model=settings.SQL_MODEL,
            temperature=0.1  # Low temperature for more deterministic SQL
        )
        
        # Extract SQL from the result
        return extract_sql_from_response(result)
    
    async def generate_sql_with_context(self, query: str, schema: str, query_context: Dict[str, Any]) -> str:
        """Generate SQL from natural language query with conversation context."""
        prompt = create_context_aware_sql_prompt(query, schema, query_context)
        result = await self.generate(
            prompt=prompt,
            model=settings.SQL_MODEL,
            temperature=0.1  # Low temperature for more deterministic SQL
        )
        
        # Extract SQL from the result
        return extract_sql_from_response(result)
        
    async def generate_response(self, query: str, sql_result: List[Dict[str, Any]]) -> str:
        """Generate natural language response from SQL results."""
        prompt = create_response_generation_prompt(query, sql_result)
        return await self.generate(
            prompt=prompt,
            model=settings.RESPONSE_MODEL,
            temperature=0.7  # Higher temperature for more natural responses
        )
    
    async def generate_response_with_context(
        self, query: str, sql_result: List[Dict[str, Any]], query_context: Dict[str, Any]
    ) -> str:
        """Generate natural language response from SQL results with conversation context."""
        prompt = create_context_aware_response_prompt(query, sql_result, query_context)
        return await self.generate(
            prompt=prompt,
            model=settings.RESPONSE_MODEL,
            temperature=0.7  # Higher temperature for more natural responses
        )