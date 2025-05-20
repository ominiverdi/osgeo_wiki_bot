# db/test_extensions.py
import os
import psycopg2
import asyncio
import httpx
from pathlib import Path
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/api/generate"
LLM_MODEL = os.getenv("LLM_MODEL", "gemma3:latest")
MIN_CONTENT_LENGTH = 500  # Minimum characters required to generate a resume
MAX_CONTENT_LENGTH = 30000  # Maximum characters to send to the LLM

def get_db_connection():
    """Connect to the PostgreSQL database."""
    try:
        # Get connection parameters from environment variables
        db_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "database": os.getenv("DB_NAME", "osgeo_wiki"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
            "port": os.getenv("DB_PORT", "5432")
        }
        
        # Connect to the database
        conn = psycopg2.connect(**db_params)
        conn.autocommit = True
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to PostgreSQL database: {e}")
        return None

async def generate_resume(title, content):
    """Generate a resume using the LLM - English only."""
    prompt = f"""You are generating a database-optimized factual summary of "{title}" ({MIN_CONTENT_LENGTH} characters).

OUTPUT FORMAT: Bullet list of key facts only.
* Start each point with an asterisk
* Include all names, dates, URLs, and precise details
* No introductions, conclusions, or questions
* No headings or sections
* Use plain text only (no bold/formatting)

CONTENT:
{content[:MAX_CONTENT_LENGTH]}
"""

    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 2048
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_API_URL,
                json=payload,
                timeout=120.0  # Increased timeout for larger content
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error generating resume: {str(e)}"

# Add this function after the generate_resume function
async def generate_keywords(title, content):
    """Generate searchable keywords using the LLM."""
    prompt = f"""You are generating searchable keywords for a database index of "{title}".

Extract ONLY terms and phrases that ACTUALLY APPEAR in the content. Focus on:

1. Names of people, organizations, projects, and places
2. Technical terms and their variations
3. Important dates, versions, and events
4. Relationship patterns (e.g., person-role, project-version combinations)

RULES:
- Include ONLY terms present in the original content
- Use space separation between terms
- Keep keywords concise (1-3 words per concept)
- Do not invent or add any terms not in the original text
- Use commas to separate terms (no line breaks)
- Between 20-50 words total
- Do not include explanatory text or descriptions in your response"

CONTENT:
{content[:MAX_CONTENT_LENGTH]}
"""

    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1024
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_API_URL,
                json=payload,
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error generating keywords: {str(e)}"

def count_words(text):
    """Count the number of words in text."""
    return len(re.findall(r'\w+', text))

def is_suspicious_content(text, input_length):
    """Check if the generated content seems suspicious (likely hallucinated)."""
    words = count_words(text)
    chars = len(text)
    
    # Suspicious if word count is more than 5x the input length in chars
    # (assuming average word is ~5 chars)
    if input_length < 100 and words > input_length / 2:
        return True
    
    # Suspicious if too many words for the character count
    if words > chars / 4:  # Normal text has ~5-6 chars per word on average
        return True
        
    return False

async def main_async():
    print("=== Querying 10 random pages and generating resumes ===")
    
    # Connect to database
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database")
        return
    
    try:
        # Get random pages
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, url FROM pages 
                ORDER BY RANDOM() 
                LIMIT 10
            """)
            pages = cur.fetchall()
        
        # Process each page
        for page_id, title, url in pages:
            print(f"\nPage: {title}")
            print(f"Wiki URL: {url}")
            
            # Get page content
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT string_agg(chunk_text, ' ' ORDER BY chunk_index) as full_content 
                    FROM page_chunks 
                    WHERE page_id = %s
                """, (page_id,))
                result = cur.fetchone()
                content = result[0] if result else ""
                
            if not content:
                print("No content found for this page")
                continue
                
            content_length = len(content)
            content_word_count = count_words(content)
            print(f"Content length: ({content_word_count} words, {content_length} characters)")
            
            # Check if content meets minimum length
            if content_length < MIN_CONTENT_LENGTH:
                print(f"Content too short (< {MIN_CONTENT_LENGTH} chars). Skipping resume generation.")
                print("Using original content as the resume.")
                print(f"Original content: ({count_words(content)} words, {content_length} characters)")
                print("-" * 80)
                continue
            
            # Generate resume
            print("Generating resume...")
            resume = await generate_resume(title, content)
            
            # Count words and characters
            resume_word_count = count_words(resume)
            resume_char_count = len(resume)
            
            # Check if the content seems suspicious
            if is_suspicious_content(resume, content_length):
                print(f"SUSPICIOUS CONTENT WARNING: Generated content may contain hallucinations")
                print(f"Content length: {content_length} chars, Resume length: {char_count} chars, Words: {word_count}")
            
            # Generate keywords
            print("Generating keywords...")
            keywords = await generate_keywords(title, content)
            # Count words for keywords
            keywords_word_count = count_words(keywords)
            keywords_char_count = len(keywords)

            # Print the resume with stats
            print(f"\nResume: ({resume_word_count} words, {resume_char_count} characters)")
            print(resume)
            print(f"\nKeywords: ({keywords_word_count} words, {keywords_char_count} characters)")
            print(keywords)
            print("-" * 80)
            
    finally:
        if conn:
            conn.close()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()