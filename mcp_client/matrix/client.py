# mcp_client/matrix/client.py
import logging
import sys
import asyncio
import json
import httpx
from typing import Dict, List, Any, Optional

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

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MatrixClient:
    """Matrix client for the OSGeo Wiki Bot."""
    
    def __init__(self):
        self.client = AsyncClient(config.HOMESERVER_URL, config.USER_ID)
        self.client.access_token = config.ACCESS_TOKEN
        self.client.device_id = "OSGeoWikiBot"
        self.rooms = config.ROOM_IDS
        self.handler = MessageHandler(config.MCP_SERVER_URL)
        
        # Set up event callbacks
        self.client.add_event_callback(self.message_callback, RoomMessageText)
        self.client.add_event_callback(self.invite_callback, InviteEvent)
    
    async def message_callback(self, room, event):
        """Process incoming room messages."""
        # Skip own messages
        if event.sender == config.USER_ID:
            return
        
        # Process message using handler
        is_mentioned, response = await self.handler.process_message(
            room.room_id,
            event.sender,
            event.body
        )
        
        # Only respond if mentioned or in direct chat
        if is_mentioned or room.member_count == 2:
            await self.send_message(room.room_id, response)
    
    async def invite_callback(self, room, event):
        """Handle room invitations."""
        logger.info(f"Received invite to room {room.room_id} from {event.sender}")
        
        # Join the room
        try:
            await self.client.join(room.room_id)
            logger.info(f"Joined room {room.room_id}")
            
            # Send a welcome message
            welcome_msg = (
                "Hello! I'm the OSGeo Wiki Bot. "
                "I can answer questions about OSGeo's wiki content. "
                "Just mention me (@osgeo-wiki-bot) in your message or start with !osgeo to ask a question."
            )
            await self.send_message(room.room_id, welcome_msg)
        except JoinError as e:
            logger.error(f"Failed to join room {room.room_id}: {e}")
    
    async def send_message(self, room_id: str, message: str):
        """Send a message to a room."""
        try:
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "format": "org.matrix.custom.html",
                    "body": message,
                    "formatted_body": self._format_markdown(message)
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
    
    async def join_rooms(self):
        """Join all configured rooms."""
        for room_id in self.rooms:
            if not room_id:
                continue
                
            try:
                logger.info(f"Joining room {room_id}")
                await self.client.join(room_id)
                await asyncio.sleep(1)  # Small delay between joins
            except JoinError as e:
                logger.error(f"Failed to join room {room_id}: {e}")
    
    async def run(self):
        """Run the client."""
        # Validate configuration first
        config.validate()
        
        try:
            # Connect to homeserver
            logger.info(f"Connecting to {config.HOMESERVER_URL} as {config.USER_ID}")
            
            # Join rooms
            await self.join_rooms()
            
            # Start sync loop
            logger.info("Starting sync loop")
            await self.client.sync_forever(timeout=30000)
        
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt. Shutting down...")
        except Exception as e:
            logger.error(f"Error in Matrix client: {e}")
            return 1
        finally:
            # Close the client properly
            await self.client.close()
        
        return 0

# Main entry point
def main():
    """Run the Matrix client."""
    client = MatrixClient()
    
    # Run the async client
    exit_code = asyncio.run(client.run())
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()