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
    
    async def process_message(self, room_id: str, sender: str, message: str) -> Tuple[bool, str]:
        """
        Process an incoming message and return a response if needed.
        
        Returns:
            Tuple[bool, str]: (is_mentioned, response_text)
            - is_mentioned: True if the bot was mentioned or command was used
            - response_text: The response to send (empty if no response)
        """
        # Check if the bot should respond to this message
        is_mentioned, query = self._parse_message(message)

        # Add near the top of process_message method in handlers.py
        logger.debug(f"Received message: '{message}' from {sender} in {room_id}")
        is_mentioned, query = self._parse_message(message)
        logger.debug(f"Is mentioned: {is_mentioned}, Query: '{query}'")
        
        if not is_mentioned or not query:
            return False, ""
        
        # Process the query through MCP server
        response = await self._send_to_mcp(room_id, query)
        
        # If we got a response, return it
        if response:
            return True, response
        
        # Fallback message if MCP server fails
        return True, "I'm sorry, I'm having trouble accessing the OSGeo wiki information right now. Please try again later."
    
    def _parse_message(self, message: str) -> Tuple[bool, str]:
        """
        Parse the message to determine if the bot was mentioned and extract the query.
        
        Returns:
            Tuple[bool, str]: (is_mentioned, query)
        """
        # Check for different ways the bot might be addressed
        mention_patterns = [
            r'@osgeo-wiki-bot:?\s*(.*)',      # Direct mention: @osgeo-wiki-bot
            r'!osgeo\s+(.*)',                 # Command: !osgeo
            r'OSGeo\s+Wiki\s+Bot:?\s*(.*)',   # Name mention with spaces: OSGeo Wiki Bot
            r'OSGeo_wiki_bot:?\s*(.*)',       # Name mention with underscores: OSGeo_wiki_bot
            r'wiki\s+bot:?\s*(.*)',           # Simplified mention: wiki bot
            r'OSGeo[-_]wiki[-_]bot:?\s*(.*)'  # Flexible underscore/hyphen mention
        ]
        
        # Try each pattern
        for pattern in mention_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                # Extract the query (everything after the mention)
                query = match.group(1).strip()
                return True, query
        
        # No mention found
        return False, ""
    
    async def _send_to_mcp(self, room_id: str, query: str) -> str:
        """Send a query to the MCP server and get a response."""
        # Get or initialize conversation context for this room
        context = self.conversations.get(room_id)
        
        # Build the full conversation history for the request
        messages = []
        if context and "history" in context:
            messages = context.get("history", []).copy()
        
        messages.append({"role": "user", "content": query})
        
        request_data = {
            "messages": messages,
            "context": context.get("context") if context else None
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.mcp_server_url,
                    json=request_data,
                    timeout=60.0  # Long timeout for complex queries
                )
                
                if response.status_code != 200:
                    logger.error(f"Error from MCP server: {response.status_code}")
                    logger.error(response.text)
                    return None
                
                response_data = response.json()
                
                # Update internal conversation state
                if "context" in response_data:
                    if room_id not in self.conversations:
                        self.conversations[room_id] = {}
                    
                    self.conversations[room_id]["context"] = response_data.get("context")
                    
                    # Update history
                    if "message" in response_data and response_data["message"]["role"] == "assistant":
                        if "history" not in self.conversations[room_id]:
                            self.conversations[room_id]["history"] = []
                        
                        # Add the user message
                        self.conversations[room_id]["history"].append({"role": "user", "content": query})
                        
                        # Add the assistant response
                        self.conversations[room_id]["history"].append(response_data["message"])
                        
                        # Trim history if it gets too long (keep last 10 messages)
                        if len(self.conversations[room_id]["history"]) > 20:
                            self.conversations[room_id]["history"] = self.conversations[room_id]["history"][-20:]
                
                # Return the response text
                if "message" in response_data and "content" in response_data["message"]:
                    return response_data["message"]["content"]
                
                return None
        
        except httpx.ConnectError:
            logger.error(f"Could not connect to MCP server at {self.mcp_server_url}")
            return None
        except Exception as e:
            logger.error(f"Error sending query to MCP server: {e}")
            return None