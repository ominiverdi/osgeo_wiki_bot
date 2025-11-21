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
    
    # LLM settings (renamed from OLLAMA)
    LLM_BASE_URL = os.getenv("LLM_BASE_URL")
    LLM_MODEL = os.getenv("LLM_MODEL")

    # LLM temperature settings
    KEYWORD_TEMPERATURE = float(os.getenv("KEYWORD_TEMPERATURE", "0.3"))
    RESPONSE_TEMPERATURE = float(os.getenv("RESPONSE_TEMPERATURE", "0.7"))
    
    # Server settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # Query alternative settings
    QUERY_ALTERNATIVES_MIN = int(os.getenv("QUERY_ALTERNATIVES_MIN", "3"))
    QUERY_ALTERNATIVES_MAX = int(os.getenv("QUERY_ALTERNATIVES_MAX", "5"))
    
    # MCP settings
    CONTEXT_HISTORY_SIZE = int(os.getenv("CONTEXT_HISTORY_SIZE", "10"))

# Create settings instance
settings = Settings()

# Debug output to verify settings are loaded correctly
print(f"Using LLM model: {settings.LLM_MODEL}")
print(f"LLM endpoint: {settings.LLM_BASE_URL}")
print(f"Database: {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
print(f"Debug mode: {settings.DEBUG}")