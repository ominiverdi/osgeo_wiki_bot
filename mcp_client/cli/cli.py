# mcp_client/cli/cli.py
import asyncio
import json
import httpx
import argparse
from typing import Dict, List, Any, Optional
import os
import sys
from datetime import datetime

# Default server URL
DEFAULT_SERVER_URL = "http://localhost:8000/v1"

# ANSI color codes for prettier output
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class MCPClient:
    """Client for interacting with the OSGeo Wiki MCP server."""
    
    def __init__(self, server_url: str = DEFAULT_SERVER_URL):
        self.server_url = server_url
        self.context = None
        self.conversation_history = []
    
    async def send_query(self, query: str) -> Dict[str, Any]:
        """Send a query to the MCP server and return the response."""
        # Build the full conversation history for the request
        messages = self.conversation_history.copy()
        messages.append({"role": "user", "content": query})
        
        request_data = {
            "messages": messages,
            "context": self.context
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.server_url,
                    json=request_data,
                    timeout=60.0  # Long timeout for complex queries
                )
                
                if response.status_code != 200:
                    print(f"{Colors.RED}Error: Server returned status code {response.status_code}{Colors.ENDC}")
                    print(response.text)
                    return None
                
                response_data = response.json()
                
                # Update internal state
                self.context = response_data.get("context")
                if "message" in response_data and response_data["message"]["role"] == "assistant":
                    self.conversation_history.append(response_data["message"])
                
                return response_data
        except httpx.ConnectError:
            print(f"{Colors.RED}Error: Could not connect to the server at {self.server_url}{Colors.ENDC}")
            print(f"{Colors.YELLOW}Make sure the MCP server is running.{Colors.ENDC}")
            return None
        except Exception as e:
            print(f"{Colors.RED}Error: {str(e)}{Colors.ENDC}")
            return None
    
    def save_conversation(self, filename: str = None) -> str:
        """Save conversation context and history to a file."""
        if not filename:
            # Generate default filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.json"
        
        data = {
            "context": self.context,
            "history": self.conversation_history
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        return filename
    
    def load_conversation(self, filename: str) -> bool:
        """Load conversation context and history from a file."""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            self.context = data.get("context")
            self.conversation_history = data.get("history", [])
            return True
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"{Colors.RED}Error loading conversation: {str(e)}{Colors.ENDC}")
            return False
    
    def print_conversation(self):
        """Print the current conversation history."""
        if not self.conversation_history:
            print(f"{Colors.YELLOW}No conversation history.{Colors.ENDC}")
            return
        
        print(f"\n{Colors.UNDERLINE}Conversation History:{Colors.ENDC}\n")
        for msg in self.conversation_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                print(f"{Colors.BLUE}{Colors.BOLD}You:{Colors.ENDC}")
                print(f"{content}\n")
            elif role == "assistant":
                print(f"{Colors.GREEN}{Colors.BOLD}Assistant:{Colors.ENDC}")
                print(f"{content}\n")
    
    def clear_conversation(self):
        """Clear the current conversation history and context."""
        self.context = None
        self.conversation_history = []
        print(f"{Colors.YELLOW}Conversation cleared.{Colors.ENDC}")

async def interactive_mode(client: MCPClient):
    """Run in interactive conversation mode."""
    print(f"{Colors.BOLD}{Colors.CYAN}===== OSGeo Wiki Bot CLI ====={Colors.ENDC}")
    print(f"Server: {client.server_url}")
    print("\nCommands:")
    print("  /exit             - Exit the program")
    print("  /save [filename]  - Save conversation")
    print("  /load [filename]  - Load conversation")
    print("  /history          - Show conversation history")
    print("  /clear            - Clear current conversation")
    print("  /help             - Show this help message")
    
    while True:
        query = input(f"\n{Colors.BLUE}{Colors.BOLD}You:{Colors.ENDC} ")
        
        # Process commands
        if query.startswith("/"):
            cmd_parts = query.split()
            cmd = cmd_parts[0].lower()
            
            if cmd == "/exit":
                break
            elif cmd == "/save":
                filename = cmd_parts[1] if len(cmd_parts) > 1 else None
                saved_file = client.save_conversation(filename)
                print(f"{Colors.CYAN}Conversation saved to {saved_file}{Colors.ENDC}")
            elif cmd == "/load":
                if len(cmd_parts) < 2:
                    print(f"{Colors.YELLOW}Usage: /load filename{Colors.ENDC}")
                    continue
                if client.load_conversation(cmd_parts[1]):
                    print(f"{Colors.CYAN}Conversation loaded from {cmd_parts[1]}{Colors.ENDC}")
            elif cmd == "/history":
                client.print_conversation()
            elif cmd == "/clear":
                client.clear_conversation()
            elif cmd == "/help":
                print("\nCommands:")
                print("  /exit             - Exit the program")
                print("  /save [filename]  - Save conversation")
                print("  /load [filename]  - Load conversation")
                print("  /history          - Show conversation history")
                print("  /clear            - Clear current conversation")
                print("  /help             - Show this help message")
            else:
                print(f"{Colors.YELLOW}Unknown command: {cmd}{Colors.ENDC}")
            continue
        elif not query.strip():
            continue
        
        # Show "thinking" indicator
        print(f"{Colors.YELLOW}Thinking...{Colors.ENDC}", end="\r")
        
        # Send query to server
        response = await client.send_query(query)
        if response and "message" in response:
            message = response["message"]
            content = message.get("content", "")
            print(f"\n{Colors.GREEN}{Colors.BOLD}Assistant:{Colors.ENDC}")
            print(f"{content}")

async def single_query_mode(client: MCPClient, query: str):
    """Run a single query and exit."""
    print(f"{Colors.BLUE}{Colors.BOLD}Query:{Colors.ENDC} {query}")
    print(f"{Colors.YELLOW}Thinking...{Colors.ENDC}", end="\r")
    
    response = await client.send_query(query)
    if response and "message" in response:
        message = response["message"]
        content = message.get("content", "")
        print(f"\n{Colors.GREEN}{Colors.BOLD}Assistant:{Colors.ENDC}")
        print(f"{content}")

def main():
    parser = argparse.ArgumentParser(description="OSGeo Wiki MCP Client")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER_URL,
                        help=f"MCP server URL (default: {DEFAULT_SERVER_URL})")
    parser.add_argument("--load", "-l", help="Load conversation from file")
    parser.add_argument("query", nargs="*", help="Query to send (if not provided, enters interactive mode)")
    
    args = parser.parse_args()
    
    # Create client
    client = MCPClient(args.server)
    
    # Load conversation if specified
    if args.load:
        if client.load_conversation(args.load):
            print(f"{Colors.CYAN}Conversation loaded from {args.load}{Colors.ENDC}")
    
    if args.query:
        # Single query mode
        asyncio.run(single_query_mode(client, " ".join(args.query)))
    else:
        # Interactive mode
        try:
            asyncio.run(interactive_mode(client))
        except KeyboardInterrupt:
            print("\nExiting...")

if __name__ == "__main__":
    main()