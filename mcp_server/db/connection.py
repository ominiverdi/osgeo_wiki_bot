# mcp_server/db/connection.py
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

from mcp_server.config import settings

def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD
    )

@contextmanager
def get_cursor():
    """Context manager for database cursor."""
    conn = None
    try:
        conn = get_connection()
        # Create a cursor that returns dictionaries
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cursor
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# Test database connection
def test_connection():
    """Test the database connection and return version info."""
    with get_cursor() as cursor:
        cursor.execute("SELECT version();")
        return cursor.fetchone()["version"]