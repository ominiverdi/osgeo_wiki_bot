# mcp_client/matrix/handlers.py
import re
import asyncio
import httpx
import logging
from typing import Dict, List, Any, Optional, Tuple
import json

logger = logging.getLogger(__name__)


class MessageHandler:
    """Handler for Matrix messages."""
    
    def __init__(self, mcp_server_url: str):
        self.mcp_server_url = mcp_server_url
        # Keep conversation contexts separated by room
        self.conversations = {}
        # Track processed messages to avoid duplicates
        self.processed_messages = set()
        # Track the last response time per room
        self.last_response_time = {}
    
    async def process_message(self, room_id: str, sender: str, message: str, event_id: str = None) -> Tuple[bool, str]:
        """
        Process an incoming message and return a response if needed.
        
        Returns:
            Tuple[bool, str]: (is_mentioned, response_text)
        """
        # Skip if we've already processed this message
        if event_id and event_id in self.processed_messages:
            logger.debug(f"Skipping already processed message: {event_id}")
            return False, ""
            
        # Add to processed messages if we have an event_id
        if event_id:
            self.processed_messages.add(event_id)
            # Keep set size manageable
            if len(self.processed_messages) > 1000:
                self.processed_messages = set(list(self.processed_messages)[-500:])
        
        # Use a strict mention pattern - ONLY respond to full Matrix ID mentions
        is_mentioned, query = self._parse_message(message)
        
        if not is_mentioned or not query:
            return False, ""
        
        # Limit response frequency per room (max once every 2 seconds)
        current_time = time.time()
        if room_id in self.last_response_time:
            time_since_last = current_time - self.last_response_time[room_id]
            if time_since_last < 2.0:
                logger.debug(f"Rate limiting: Only {time_since_last:.2f}s since last response in room {room_id}")
                return False, ""
        
        # Update last response time
        self.last_response_time[room_id] = current_time
        
        # Process the query through MCP server
        response = await self._send_to_mcp(room_id, query)
        
        # If we got a response, return it
        if response:
            return True, response
        
        # Fallback message if MCP server fails
        return True, "I'm sorry, I'm having trouble accessing the OSGeo wiki information right now. Please try again later."
    
    def _parse_message(self, message: str) -> Tuple[bool, str]:
        """
        Parse the message using ONLY the full Matrix ID mention.
        
        Returns:
            Tuple[bool, str]: (is_mentioned, query)
        """
        # ONLY allow full Matrix ID mentions
        pattern = r'@osgeo-wiki-bot:matrix\.org\s*(.*)'
        
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            query = match.group(1).strip()
            return True, query
            
        return False, ""


    