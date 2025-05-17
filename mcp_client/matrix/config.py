# mcp_client/matrix/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Load environment variables from .env file
load_dotenv(ENV_PATH)

class MatrixConfig:
    """Matrix client configuration loaded from environment variables."""
    
    # Matrix settings
    HOMESERVER_URL = os.getenv("MATRIX_HOMESERVER_URL", "https://matrix.org")
    ACCESS_TOKEN = os.getenv("MATRIX_ACCESS_TOKEN")
    USER_ID = os.getenv("MATRIX_USER_ID")
    ROOM_IDS = os.getenv("MATRIX_ROOM_IDS", "").split(",")
    
    # MCP Server settings
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/v1")
    
    # Client settings
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    
    @classmethod
    def validate(cls):
        """Validate configuration."""
        missing = []
        
        if not cls.ACCESS_TOKEN:
            missing.append("MATRIX_ACCESS_TOKEN")
        
        if not cls.USER_ID:
            missing.append("MATRIX_USER_ID")
        
        if not cls.ROOM_IDS or not cls.ROOM_IDS[0]:
            missing.append("MATRIX_ROOM_IDS")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True

# Create config instance
config = MatrixConfig()

# Validate on import
if __name__ != "__main__":  # Don't validate when run directly
    try:
        config.validate()
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please set the required environment variables in the .env file.")