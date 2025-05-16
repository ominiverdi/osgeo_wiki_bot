# mcp_server/config.py
import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    # Database settings
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.getenv("DB_NAME", "osgeo_wiki")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
    
    # Ollama settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    SQL_MODEL: str = os.getenv("SQL_MODEL", "codellama:7b")
    RESPONSE_MODEL: str = os.getenv("RESPONSE_MODEL", "mistral:7b")
    
    # Server settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # MCP settings
    CONTEXT_HISTORY_SIZE: int = int(os.getenv("CONTEXT_HISTORY_SIZE", "10"))
    
    class Config:
        env_file = ".env"

settings = Settings()