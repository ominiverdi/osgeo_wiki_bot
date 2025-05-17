import json
import time
import re
import httpx
import logging
from typing import Dict, List, Any, Optional, Tuple

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
        logger.debug(f"Sending to MCP server: '{message}'")
        response = await self._send_to_mcp(room_id, message)
        logger.debug(f"MCP response received: {response is not None}")
        
        # If we got a response, return it
        if response:
            return True, response
        
        # Fallback message if MCP server fails
        return True, "I'm sorry, I'm having trouble accessing the OSGeo wiki information right now. Please try again later."
    
    async def _send_to_mcp(self, room_id: str, query: str) -> Optional[str]:
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
        
        logger.debug(f"MCP request data: {request_data}")
        
        try:
            async with httpx.AsyncClient() as client:
                logger.debug(f"Sending request to MCP server: {self.mcp_server_url}")
                response = await client.post(
                    self.mcp_server_url,
                    json=request_data,
                    timeout=60.0  # Long timeout for complex queries
                )
                
                logger.debug(f"MCP server status code: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"Error from MCP server: {response.status_code}")
                    logger.error(response.text)
                    return None
                
                response_data = response.json()
                logger.debug(f"MCP server response data: {response_data}")
                
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