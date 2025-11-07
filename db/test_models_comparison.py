# db/test_models_llamacpp.py
import os
import sys
import json
import time
import random
import logging
import asyncio
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import httpx

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

# Configuration
MODELS = [
    {
        "name": "granite-3.3-8b-65k",
        "url": "http://localhost:8080/v1/chat/completions"
    },
    {
        "name": "qwen3-8b-8k",
        "url": "http://localhost:8081/v1/chat/completions"
    }
]

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'osgeo_wiki'),
    'user': os.getenv('DB_USER', 'ominiverdi'),
    'password': os.getenv('DB_PASSWORD', ''),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

WIKI_DUMP_PATH = Path(os.getenv('WIKI_DUMP_PATH', './wiki_dump'))
SAMPLE_SIZE = 20
OUTPUT_FILE = 'model_comparison_results.json'


def get_db_connection():
    """Get database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return None


def find_wiki_file_by_url(wiki_dump_path, target_url):
    """Find wiki file by matching URL in file content."""
    for filepath in wiki_dump_path.iterdir():
        if filepath.is_file():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                    if first_line.startswith('URL: ') and target_url in first_line:
                        return filepath
            except:
                continue
    return None


def read_wiki_file(filepath):
    """Read content from wiki dump file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Parse the file format
        url = lines[0].replace('URL: ', '').strip() if len(lines) > 0 else ''
        title = lines[1].replace('Title: ', '').strip() if len(lines) > 1 else ''
        
        # Find where content starts (after "Content:")
        content_start = 0
        for i, line in enumerate(lines):
            if line.startswith('Content:'):
                content_start = i + 1
                break
        
        content = ''.join(lines[content_start:]).strip()
        
        return {
            'url': url,
            'title': title,
            'content': content,
            'content_length': len(content)
        }
    except Exception as e:
        logger.error(f"Failed to read file {filepath}: {e}")
        return None


def get_random_pages(conn, sample_size):
    """Get random sample of pages from database."""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, title, url 
                FROM pages 
                ORDER BY RANDOM() 
                LIMIT %s
            """, (sample_size,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to get random pages: {e}")
        return []


async def call_llama_cpp(model_url, model_name, prompt, timeout=180):
    """Call llama.cpp server using OpenAI-compatible API."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2048,
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content']
            else:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                return None
    except httpx.TimeoutException:
        logger.error(f"Timeout calling {model_name}")
        return None
    except Exception as e:
        logger.error(f"Error calling {model_name}: {e}")
        return None


async def generate_resume(model_url, model_name, title, content):
    """Generate resume using specified model."""
    prompt = f"""You are creating a database-optimized summary of OSGeo wiki pages for search retrieval.
For this page titled "{title}", create:

FACTUAL SUMMARY (200-300 words):
* Preserve ALL names, usernames, email addresses, and website URLs exactly as written
* Maintain ALL date information precisely (years, months, events)
* Convert tables into explicit statements of relationships
* Include ALL project names, committee roles, and organizational structures
* Begin each distinct fact with "* " to create an implicit list structure

Ensure the summary emphasizes FACTS over descriptions, RELATIONSHIPS over general information, and SPECIFIC DETAILS over broad concepts.

Avoid unnecessary language like "This page describes" or "The content explains that".
Focus on raw information density while maintaining readability.

Page content:
{content}

Summary:"""

    start_time = time.time()
    response = await call_llama_cpp(model_url, model_name, prompt)
    elapsed = time.time() - start_time
    
    return {
        'resume': response,
        'processing_time': elapsed
    }


async def generate_keywords(model_url, model_name, title, content):
    """Generate keywords using specified model."""
    prompt = f"""You are generating searchable keywords for a database index of "{title}".

Extract ONLY terms and phrases that ACTUALLY APPEAR in the content about {title}.

EXTRACT EXACTLY:
1. Names of people, organizations, projects, and places
2. Technical terms and their variations
3. Important dates, versions, and events
4. Key concepts that distinguish this page

FORMAT: Return a simple comma-separated list with NO explanation text.
LIMIT: 20-30 keywords maximum
RULE: Each concept should appear only ONCE

Page content:
{content}

Keywords:"""

    start_time = time.time()
    response = await call_llama_cpp(model_url, model_name, prompt)
    elapsed = time.time() - start_time
    
    return {
        'keywords': response,
        'processing_time': elapsed
    }


async def process_page_with_model(model_config, page_data):
    """Process a single page with a specific model."""
    try:
        resume_result = await generate_resume(
            model_config['url'], 
            model_config['name'],
            page_data['title'], 
            page_data['content']
        )
        
        if resume_result['resume'] is None:
            return {'model': model_config['name'], 'error': 'Resume generation failed'}
        
        keywords_result = await generate_keywords(
            model_config['url'],
            model_config['name'],
            page_data['title'], 
            page_data['content']
        )
        
        if keywords_result['keywords'] is None:
            return {'model': model_config['name'], 'error': 'Keyword generation failed'}
        
        return {
            'model': model_config['name'],
            'resume': resume_result['resume'],
            'resume_processing_time': resume_result['processing_time'],
            'keywords': keywords_result['keywords'],
            'keywords_processing_time': keywords_result['processing_time'],
            'total_processing_time': resume_result['processing_time'] + keywords_result['processing_time']
        }
    except Exception as e:
        logger.error(f"Error processing page with {model_config['name']}: {e}")
        return {'model': model_config['name'], 'error': str(e)}


async def process_single_page(page, wiki_dump_path, page_num, total_pages):
    """Process a single page with both models sequentially."""
    
    # Find wiki file
    filepath = find_wiki_file_by_url(wiki_dump_path, page['url'])
    if not filepath:
        logger.warning(f"[{page_num}/{total_pages}] Wiki file not found: {page['url']}")
        return None
    
    # Read content
    wiki_data = read_wiki_file(filepath)
    if not wiki_data:
        logger.warning(f"[{page_num}/{total_pages}] Failed to read: {page['title']}")
        return None
    
    logger.info(f"\n[{page_num}/{total_pages}] Processing: {page['title'][:60]}")
    
    # Process with model 1
    logger.info(f"  → {MODELS[0]['name']}: generating...")
    result1 = await process_page_with_model(MODELS[0], wiki_data)
    
    if 'error' in result1:
        logger.error(f"  ✗ {MODELS[0]['name']} failed: {result1['error']}")
    else:
        logger.info(f"  ✓ {MODELS[0]['name']} completed in {result1['total_processing_time']:.1f}s")
    
    # Process with model 2
    logger.info(f"  → {MODELS[1]['name']}: generating...")
    result2 = await process_page_with_model(MODELS[1], wiki_data)
    
    if 'error' in result2:
        logger.error(f"  ✗ {MODELS[1]['name']} failed: {result2['error']}")
    else:
        logger.info(f"  ✓ {MODELS[1]['name']} completed in {result2['total_processing_time']:.1f}s")
    
    return {
        'page_id': page['id'],
        'page_title': page['title'],
        'page_url': page['url'],
        'content_length': wiki_data['content_length'],
        'models': [result1, result2]
    }


def save_results(all_results, timestamp):
    """Save results to JSON file."""
    output_path = Path(OUTPUT_FILE)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'test_config': {
                'models': [m['name'] for m in MODELS],
                'sample_size': len(all_results),
                'processing_strategy': 'fully_serial_llamacpp',
                'timestamp': timestamp
            },
            'results': all_results
        }, f, indent=2, ensure_ascii=False)


async def main():
    """Main processing function."""
    start_time = time.time()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    logger.info("="*70)
    logger.info("Model Comparison Test - llama.cpp Servers")
    logger.info("="*70)
    logger.info(f"Testing models: {', '.join([m['name'] for m in MODELS])}")
    logger.info(f"Sample size: {SAMPLE_SIZE} pages")
    logger.info(f"Strategy: One page at a time, both models sequentially")
    logger.info("="*70 + "\n")
    
    # Connect to database
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return
    
    # Get random pages
    logger.info("Selecting random pages...")
    pages = get_random_pages(conn, SAMPLE_SIZE)
    logger.info(f"Selected {len(pages)} pages\n")
    
    conn.close()
    
    # Process pages one at a time
    all_results = []
    successful = 0
    
    for i, page in enumerate(pages, 1):
        result = await process_single_page(page, WIKI_DUMP_PATH, i, len(pages))
        
        if result:
            all_results.append(result)
            successful += 1
            
            # Save progress every 10 pages
            if successful % 10 == 0:
                save_results(all_results, timestamp)
                elapsed = time.time() - start_time
                logger.info(f"\n💾 Progress saved: {successful} pages in {elapsed/60:.1f} minutes\n")
        else:
            logger.warning(f"✗ Skipped page {i}")
    
    # Save final results
    total_time = time.time() - start_time
    logger.info(f"\n{'='*70}")
    logger.info(f"Processing complete!")
    logger.info(f"Total pages processed: {len(all_results)}/{len(pages)}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")
    logger.info(f"Average time per page: {total_time/len(all_results):.1f}s")
    logger.info(f"{'='*70}\n")
    
    save_results(all_results, timestamp)
    logger.info(f"✓ Results saved to {OUTPUT_FILE}")
    logger.info(f"\nNext step: Run 'python analysis/evaluate_model_comparison.py' to analyze results")


if __name__ == "__main__":
    asyncio.run(main())