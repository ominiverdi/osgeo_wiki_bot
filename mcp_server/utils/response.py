# mcp_server/utils/response.py
from typing import Dict, List, Any, Optional

def format_search_results(query: str, results: List[Dict[str, Any]]) -> str:
    """Format search results into a readable response."""
    if not results:
        return f"I couldn't find any information about '{query}' in the OSGeo wiki."
    
    # Group results by page
    pages = {}
    for result in results:
        page_id = result.get('id')
        if page_id not in pages:
            pages[page_id] = {
                'title': result.get('title', 'Unknown Title'),
                'url': result.get('url', '#'),
                'chunks': []
            }
        pages[page_id]['chunks'].append(result.get('chunk_text', ''))
    
    # Format the response
    response = f"Here's what I found about '{query}' in the OSGeo wiki:\n\n"
    
    for page_info in pages.values():
        response += f"## {page_info['title']}\n\n"
        
        # Add a sample of text from the page
        if page_info['chunks']:
            sample_text = page_info['chunks'][0]
            if len(sample_text) > 300:
                sample_text = sample_text[:297] + "..."
            response += f"{sample_text}\n\n"
        
        # Add source
        response += f"[Source: {page_info['url']}]\n\n"
    
    response += "Let me know if you need more specific information!"
    return response