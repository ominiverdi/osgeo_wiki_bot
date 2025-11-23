# mcp_client/matrix/client.py
import logging
import sys
import asyncio
import json
import httpx
from typing import Dict, List, Any, Optional
import re
import time

# Try different import approaches
try:
    from matrix_nio import AsyncClient, RoomMessageText, InviteEvent, LoginResponse, JoinError
except ImportError:
    try:
        # Sometimes it's just 'nio' in the Python path
        from nio import AsyncClient, RoomMessageText, InviteEvent, LoginResponse, JoinError
    except ImportError:
        print("ERROR: Could not import matrix-nio library.")
        print("Make sure it's installed with: pip install matrix-nio")
        sys.exit(1)

from .config import config
from .handlers import MessageHandler


# Silence noisy loggers
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING) 
logging.getLogger('nio').setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MatrixClient:
    """Matrix client for the OSGeo Wiki Bot."""
    
    def __init__(self):
        self.client = AsyncClient(config.HOMESERVER_URL, config.USER_ID)
        self.client.device_id = "OSGeoWikiBot"
        self.rooms = config.ROOM_IDS
        self.handler = MessageHandler(config.MCP_SERVER_URL)
        
        # Extract bot name once
        self.bot_name = config.USER_ID.split(':')[0].lstrip('@')
        logger.info(f"Bot name: {self.bot_name}")
        
        # Track the bot's start time (in milliseconds for compatibility with Matrix timestamps)
        self.start_time = int(time.time() * 1000)
        logger.info(f"Bot started at timestamp: {self.start_time}")
        
        # Set up event callbacks
        self.client.add_event_callback(self.message_callback, RoomMessageText)
        self.client.add_event_callback(self.invite_callback, InviteEvent)

    async def run(self):
        """Run the client."""
        try:
            # Connect to homeserver
            logger.info(f"Connecting to {config.HOMESERVER_URL} as {config.USER_ID}")
            
            # Always authenticate to properly initialize client state
            if config.PASSWORD:
                success = await self.login()
                if not success:
                    logger.error("Failed to authenticate, cannot continue")
                    return 1
            else:
                logger.error("No password configured")
                return 1
            
            # Join rooms
            await self.join_rooms()
            
            # Start sync loop with error handling
            logger.info("Starting sync loop")
            
            while True:
                try:
                    await self.client.sync(timeout=30000)
                except Exception as e:
                    error_str = str(e).lower()
                    if "unauthorized" in error_str or "forbidden" in error_str or "token" in error_str:
                        logger.warning("Token may have expired, attempting to re-authenticate")
                        success = await self.login()
                        if not success:
                            logger.error("Failed to re-authenticate")
                            break
                        # Continue with sync loop after successful re-auth
                        continue
                    else:
                        # For other errors, log and continue
                        logger.error(f"Sync error: {e}")
                        await asyncio.sleep(5)  # Wait before retry
        
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt. Shutting down...")
        except Exception as e:
            logger.error(f"Error in Matrix client: {e}")
            return 1
        finally:
            # Close the client properly
            await self.client.close()
        
        return 0

    async def invite_callback(self, room, event):
        """Handle room invitations."""
        logger.info(f"Received invite to room {room.room_id} from {event.sender}")
        
        # Only join rooms that are explicitly configured
        if room.room_id in self.rooms:
            try:
                await self.client.join(room.room_id)
                logger.info(f"Joined room {room.room_id}")
                
                # Send a welcome message
                welcome_msg = (
                    "Hello! I'm the OSGeo Wiki Bot. I can answer questions about OSGeo's wiki content. "
                    "To ask a question, mention me with my full ID: @osgeo-wiki-bot:matrix.org followed by your question."
                )
                await self.send_message(room.room_id, welcome_msg)
            except Exception as e:
                logger.error(f"Failed to join room {room.room_id}: {e}")
        else:
            logger.info(f"Ignoring invite to room {room.room_id} (not in configured room list)")
    
    async def login(self):
        """Authenticate and get a new access token."""
        try:
            logger.info(f"Authenticating as {config.USER_ID}...")
            resp = await self.client.login(config.PASSWORD, device_name="OSGeoWikiBot")
            
            if isinstance(resp, LoginResponse):
                logger.info("Successfully logged in")
                return True
            else:
                logger.error(f"Failed to log in: {resp}")
                return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
            
    async def join_rooms(self):
        """Join all configured rooms."""
        logger.info(f"Configured to join these rooms: {self.rooms}")
        
        for room_id in self.rooms:
            if not room_id:
                continue
                
            try:
                logger.info(f"Joining room {room_id}")
                await self.client.join(room_id)
                await asyncio.sleep(1)  # Small delay between joins
            except Exception as e:
                logger.error(f"Failed to join room {room_id}: {e}")
                
    async def message_callback(self, room, event):
        """Process incoming room messages."""
        # Skip own messages
        if event.sender == config.USER_ID:
            return
        
        # Only process messages in configured rooms
        if room.room_id not in self.rooms:
            logger.info(f"Ignoring message in non-configured room: {room.room_id}")
            return
        
        # Skip messages older than the bot's start time
        if hasattr(event, 'server_timestamp') and event.server_timestamp < self.start_time:
            logger.info(f"Skipping old message from {event.sender}")
            return
        
        # Log every message we receive (for debugging)
        message_body = event.body
        logger.info(f"Received message from {event.sender}: '{message_body}'")
        
        # Extract the actual query from the message
        query = None
        is_mentioned = False
        
        # Check if message starts with bot name followed by colon
        if message_body.lower().startswith(f"{self.bot_name}:"):
            query = message_body.split(":", 1)[1].strip()
            is_mentioned = True
            logger.info(f"Matched bot name pattern, query: '{query}'")
        # Check if message contains the full Matrix ID
        elif config.USER_ID in message_body:
            parts = message_body.split(config.USER_ID, 1)
            if len(parts) > 1:
                query = parts[1].strip()
                # Remove leading colon if present
                if query.startswith(":"):
                    query = query[1:].strip()
                is_mentioned = True
                logger.info(f"Matched Matrix ID pattern, query: '{query}'")
        # Check for mentions in the source if available
        elif hasattr(event, 'source') and isinstance(event.source, dict):
            content = event.source.get('content', {})
            if 'm.mentions' in content and 'user_ids' in content['m.mentions']:
                if config.USER_ID in content['m.mentions']['user_ids']:
                    # Extract after display name with colon if present
                    if ":" in message_body:
                        query = message_body.split(":", 1)[1].strip()
                    else:
                        query = message_body
                    is_mentioned = True
                    logger.info(f"Matched m.mentions pattern, query: '{query}'")
        
        # Process the extracted query
        if is_mentioned and query:
            logger.info(f"Processing query: '{query}'")
            
            try:
                # Show typing indicator
                logger.info(f"Sending typing indicator to {room.room_id}")
                typing_resp = await self.client.room_typing(room.room_id, typing_state=True, timeout=10000)
                logger.info(f"Typing indicator response: {typing_resp}")
                
                # Process message using handler
                _, response = await self.handler.process_message(
                    room.room_id,
                    event.sender,
                    query,
                    event.event_id
                )
                
                # Only respond if we have a response
                if response:
                    await self.send_message(room.room_id, response)
            except Exception as e:
                logger.error(f"Error during message processing: {e}")
            finally:
                # Always stop typing indicator
                logger.info(f"Stopping typing indicator for {room.room_id}")
                try:
                    stop_resp = await self.client.room_typing(room.room_id, typing_state=False)
                    logger.info(f"Stop typing response: {stop_resp}")
                except Exception as e:
                    logger.error(f"Error stopping typing indicator: {e}")
        else:
            logger.info(f"Message not for bot (is_mentioned={is_mentioned}, query='{query}')")
    
    async def send_message(self, room_id: str, message: str):
        """Send a message to a room."""
        try:
            # Process message to ensure URLs are formatted as links
            formatted_body = self._format_markdown(message)
            
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "format": "org.matrix.custom.html",
                    "body": message,
                    "formatted_body": formatted_body
                }
            )
        except Exception as e:
            logger.error(f"Failed to send message to {room_id}: {e}")
    
    def _format_markdown(self, message: str) -> str:
        """Convert message to HTML for Matrix formatting."""
        # Compress multiple newlines to single newlines
        message = re.sub(r'\n\s*\n', '\n', message)
        
        # Create a copy for HTML formatting
        html = message
        
        # Handle basic formatting
        html = html.replace("\n", "<br>")
        html = html.replace("**", "<b>").replace("**", "</b>")
        html = html.replace("*", "<i>").replace("*", "</i>")
        
        # Make URLs clickable
        url_pattern = r'(https?://[^\s<]+)'
        html = re.sub(url_pattern, r'<a href="\1">\1</a>', html)
        
        # Fix incorrectly nested URLs (like [url](url))
        html = re.sub(r'\[https?://[^\]]+\]\(([^)]+)\)', r'<a href="\1">\1</a>', html)
        
        # Handle code blocks
        if "```" in html:
            html = html.replace("```", "<pre><code>", 1)
            html = html.replace("```", "</code></pre>", 1)
        
        return html

# Main entry point
def main():
    """Run the Matrix client."""
    client = MatrixClient()
    
    # Run the async client
    exit_code = asyncio.run(client.run())
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()