# mcp_server/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Load environment variables from .env file
load_dotenv(ENV_PATH)

class Settings:
    """Application settings loaded from environment variables."""
    
    # Database settings
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    
    # Ollama settings
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
    SQL_MODEL = os.getenv("SQL_MODEL")
    RESPONSE_MODEL = os.getenv("RESPONSE_MODEL")
    
    # Server settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    
    # MCP settings
    CONTEXT_HISTORY_SIZE = int(os.getenv("CONTEXT_HISTORY_SIZE", "10"))

# Create settings instance
settings = Settings()

# Debug output to verify settings are loaded correctly
print(f"Using SQL model: {settings.SQL_MODEL}")
print(f"Using Response model: {settings.RESPONSE_MODEL}")
print(f"Database: {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
print(f"Debug mode: {settings.DEBUG}")