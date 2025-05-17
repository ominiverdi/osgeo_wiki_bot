# mcp_server/llm/ollama.py
import httpx
from typing import Dict, List, Any, Optional

from ..config import settings
from .keyword_extraction import create_keyword_extraction_prompt, extract_keywords_from_response
from .response_gen import create_response_generation_prompt, create_context_aware_response_prompt

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
    
    async def extract_keywords(self, query: str, keyword_cloud: str, categories: list) -> dict:
        """Extract keywords from a natural language query."""
        print(f"==== LLM REQUEST ====")
        print(f"QUERY: {query}")
        
        prompt = create_keyword_extraction_prompt(query, keyword_cloud, categories)
        print(f"PROMPT (truncated): {prompt[:200]}...")
        
        result = await self.generate(
            prompt=prompt,
            model=self.model,
            temperature=settings.KEYWORD_TEMPERATURE
        )
        
        print(f"==== LLM RESPONSE ====")
        print(f"RESPONSE: {result[:200]}...")
        
        return extract_keywords_from_response(result)
        
    async def generate_response(self, query: str, search_result: List[Dict[str, Any]]) -> str:
        """Generate natural language response from search results."""
        prompt = create_response_generation_prompt(query, search_result)
        return await self.generate(
            prompt=prompt,
            model=self.model,
            temperature=settings.RESPONSE_TEMPERATURE  # Higher temperature for more natural responses
        )
    
    async def generate_response_with_context(
        self, query: str, search_result: List[Dict[str, Any]], query_context: Dict[str, Any]
    ) -> str:
        """Generate natural language response from search results with conversation context."""
        prompt = create_context_aware_response_prompt(query, search_result, query_context)
        return await self.generate(
            prompt=prompt,
            model=self.model,
            temperature=settings.RESPONSE_TEMPERATURE  # Higher temperature for more natural responses
        )