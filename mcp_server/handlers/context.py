# mcp_server/handlers/context.py
from typing import Dict, List, Any, Optional, Tuple
import json
import time
from pydantic import BaseModel

from ..config import settings

class Message(BaseModel):
    """Model for a conversation message."""
    role: str
    content: str
    timestamp: Optional[float] = None

class EntityReference(BaseModel):
    """Model for tracked entity references."""
    type: str  # 'page', 'category', 'term'
    value: str
    timestamp: float
    count: int = 1

class SearchResult(BaseModel):
    """Model for a search result reference."""
    page_id: int
    title: str
    url: str
    snippet: str
    timestamp: float

class ConversationContext:
    """Manages conversation context for the MCP server."""
    
    def __init__(self, context_dict: Optional[Dict[str, Any]] = None):
        """Initialize context from a dictionary or create a new context."""
        self.conversation_id: str = ""
        self.messages: List[Message] = []
        self.entities: Dict[str, EntityReference] = {}  # Key is type:value
        self.search_results: List[SearchResult] = []
        self.last_query_time: float = 0
        self.query_count: int = 0
        self.metadata: Dict[str, Any] = {}
        
        # Initialize from existing context if provided
        if context_dict:
            self._load_from_dict(context_dict)
        
    def _load_from_dict(self, context_dict: Dict[str, Any]) -> None:
        """Load context from a dictionary."""
        self.conversation_id = context_dict.get("conversation_id", "")
        
        # Load messages
        messages_data = context_dict.get("messages", [])
        self.messages = [Message(**msg) if isinstance(msg, dict) else msg for msg in messages_data]
        
        # Load entities
        entities_data = context_dict.get("entities", {})
        self.entities = {
            k: EntityReference(**v) if isinstance(v, dict) else v 
            for k, v in entities_data.items()
        }
        
        # Load search results
        results_data = context_dict.get("search_results", [])
        self.search_results = [
            SearchResult(**result) if isinstance(result, dict) else result 
            for result in results_data
        ]
        
        # Load other properties
        self.last_query_time = context_dict.get("last_query_time", 0)
        self.query_count = context_dict.get("query_count", 0)
        self.metadata = context_dict.get("metadata", {})
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to a dictionary for MCP protocol."""
        return {
            "conversation_id": self.conversation_id,
            "messages": [msg.dict() for msg in self.messages[-settings.CONTEXT_HISTORY_SIZE:]],
            "entities": {k: v.dict() for k, v in self.entities.items()},
            "search_results": [result.dict() for result in self.search_results[-5:]],  # Keep last 5 results
            "last_query_time": self.last_query_time,
            "query_count": self.query_count,
            "metadata": self.metadata
        }
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        message = Message(
            role=role,
            content=content,
            timestamp=time.time()
        )
        self.messages.append(message)
        
        # Update query count and time if this is a user message
        if role == "user":
            self.last_query_time = message.timestamp
            self.query_count += 1
    
    def add_entity_reference(self, entity_type: str, value: str) -> None:
        """Track a referenced entity."""
        key = f"{entity_type}:{value}"
        current_time = time.time()
        
        if key in self.entities:
            self.entities[key].count += 1
            self.entities[key].timestamp = current_time
        else:
            self.entities[key] = EntityReference(
                type=entity_type,
                value=value,
                timestamp=current_time
            )
    
    def add_search_result(self, page_id: int, title: str, url: str, snippet: str) -> None:
        """Add a search result to the context."""
        result = SearchResult(
            page_id=page_id,
            title=title, 
            url=url,
            snippet=snippet,
            timestamp=time.time()
        )
        
        # Check if this result is already in context
        for existing in self.search_results:
            if existing.page_id == page_id:
                # Just update the timestamp
                existing.timestamp = result.timestamp
                return
                
        self.search_results.append(result)
    
    def get_recent_messages(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get recent conversation messages."""
        return [msg.dict() for msg in self.messages[-count:]]
    
    def get_topic_entities(self) -> List[str]:
        """Get main topic entities from conversation."""
        if not self.entities:
            return []
            
        # Sort by count and recency
        sorted_entities = sorted(
            self.entities.values(), 
            key=lambda e: (e.count, e.timestamp),
            reverse=True
        )
        
        return [e.value for e in sorted_entities[:3]]
    
    def is_followup_question(self, query: str) -> bool:
        """Determine if a query is likely a follow-up question."""
        # Look for pronouns and referential phrases
        followup_indicators = [
            "it", "this", "that", "they", "them", "those",
            "their", "these", "the", "what about", "how about",
            "tell me more", "more", "what else", "also", "and",
            "?", "another"
        ]
        
        query_lower = query.lower()
        
        # Check if query contains followup indicators
        has_indicator = any(indicator in query_lower for indicator in followup_indicators)
        
        # Check if query is very short (often follow-ups are short)
        is_short = len(query.split()) <= 5
        
        # Check if there are previous messages
        has_history = len(self.messages) > 0
        
        # Check recency - follow-up usually happens within 2 minutes
        is_recent = False
        if has_history and self.last_query_time > 0:
            is_recent = (time.time() - self.last_query_time) < 120
        
        # Determine if this is likely a follow-up
        return has_history and is_recent and (has_indicator or is_short)
    
    def get_context_for_query(self, query: str) -> Dict[str, Any]:
        """Get the relevant context for a query."""
        # Start with basic context
        query_context = {
            "conversation_id": self.conversation_id,
            "recent_messages": self.get_recent_messages(),
            "is_followup": self.is_followup_question(query)
        }
        
        # Add topic entities if we have them
        topic_entities = self.get_topic_entities()
        if topic_entities:
            query_context["topic_entities"] = topic_entities
        
        # Add recent search results if this is a follow-up
        if query_context["is_followup"] and self.search_results:
            recent_results = sorted(self.search_results, key=lambda r: r.timestamp, reverse=True)[:3]
            query_context["recent_results"] = [
                {
                    "title": r.title,
                    "snippet": r.snippet,
                    "page_id": r.page_id
                } for r in recent_results
            ]
        
        return query_context

def create_context(mcp_context: Optional[Dict[str, Any]] = None) -> ConversationContext:
    """Create a ConversationContext object from MCP protocol context."""
    return ConversationContext(mcp_context)

def update_context_with_results(
    context: ConversationContext,
    query: str,
    results: List[Dict[str, Any]]
) -> None:
    """Update context with new query and search results."""
    # Add the query as a user message
    context.add_message("user", query)
    
    # Process search results
    for result in results:
        if all(k in result for k in ["id", "title", "url"]):
            context.add_search_result(
                page_id=result["id"],
                title=result["title"],
                url=result["url"],
                snippet=result.get("chunk_text", "")[:200]  # Store a snippet
            )
    
    # Extract and add potential entities from results
    for result in results:
        # Add page title as entity
        if "title" in result:
            context.add_entity_reference("page", result["title"])
        
        # Add categories if present
        if "category_name" in result:
            context.add_entity_reference("category", result["category_name"])