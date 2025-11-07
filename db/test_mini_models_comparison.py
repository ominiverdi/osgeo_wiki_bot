# db/test_3models_speed.py
import os
import sys
import json
import time
import logging
import asyncio
import re
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

MODELS = [
    {
        "name": "granite-4.0-h-tiny",
        "url": "http://localhost:8080/v1/chat/completions"
    },
    {
        "name": "qwen3-8b-8k",
        "url": "http://localhost:8081/v1/chat/completions"
    },
    {
        "name": "smollm2-1.7b",
        "url": "http://localhost:8084/v1/chat/completions"
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
SAMPLE_SIZE = 4
OUTPUT_FILE = 'model_comparison_mini_results.json'


def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return None


def find_wiki_file_by_url(wiki_dump_path, target_url):
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
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        url = lines[0].replace('URL: ', '').strip() if len(lines) > 0 else ''
        title = lines[1].replace('Title: ', '').strip() if len(lines) > 1 else ''
        
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


def strip_thinking_tags(text):
    """Remove <think> reasoning chains from responses."""
    if not text:
        return text
    
    # Remove everything between <think> and </think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return text.strip()


async def call_llama_cpp(model_url, model_name, prompt, timeout=180):
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
                logger.error(f"API error {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error calling {model_name}: {e}")
        return None


async def generate_resume(model_url, model_name, title, content):
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
    response = strip_thinking_tags(response)
    elapsed = time.time() - start_time
    
    return {
        'resume': response,
        'processing_time': elapsed
    }


async def generate_keywords(model_url, model_name, title, content):
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
    response = strip_thinking_tags(response)
    elapsed = time.time() - start_time
    
    return {
        'keywords': response,
        'processing_time': elapsed
    }


async def process_page_with_model(model_config, page_data):
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
        logger.error(f"Error processing with {model_config['name']}: {e}")
        return {'model': model_config['name'], 'error': str(e)}


async def process_single_page(page, wiki_dump_path, page_num, total_pages):
    filepath = find_wiki_file_by_url(wiki_dump_path, page['url'])
    if not filepath:
        logger.warning(f"[{page_num}/{total_pages}] Wiki file not found: {page['url']}")
        return None
    
    wiki_data = read_wiki_file(filepath)
    if not wiki_data:
        logger.warning(f"[{page_num}/{total_pages}] Failed to read: {page['title']}")
        return None
    
    logger.info(f"\n[{page_num}/{total_pages}] Processing: {page['title'][:60]}")
    
    results = {
        'page_id': page['id'],
        'page_title': page['title'],
        'page_url': page['url'],
        'content_length': wiki_data['content_length'],
        'models': []
    }
    
    for model in MODELS:
        logger.info(f"  → {model['name']}: generating...")
        result = await process_page_with_model(model, wiki_data)
        
        if 'error' in result:
            logger.error(f"  ✗ {model['name']} failed: {result['error']}")
        else:
            logger.info(f"  ✓ {model['name']} completed in {result['total_processing_time']:.1f}s")
        
        results['models'].append(result)
    
    return results


def save_results(all_results, timestamp):
    output_path = Path(OUTPUT_FILE)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'test_config': {
                'models': [m['name'] for m in MODELS],
                'sample_size': len(all_results),
                'processing_strategy': 'serial_3models_fixed',
                'timestamp': timestamp
            },
            'results': all_results
        }, f, indent=2, ensure_ascii=False)


async def main():
    start_time = time.time()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    logger.info("="*70)
    logger.info("3-Model Speed Test - Fixed <think> tag handling")
    logger.info("="*70)
    logger.info(f"Testing models: {', '.join([m['name'] for m in MODELS])}")
    logger.info(f"Sample size: {SAMPLE_SIZE} pages")
    logger.info("="*70 + "\n")
    
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return
    
    logger.info("Selecting random pages...")
    pages = get_random_pages(conn, SAMPLE_SIZE)
    logger.info(f"Selected {len(pages)} pages\n")
    
    conn.close()
    
    all_results = []
    
    for i, page in enumerate(pages, 1):
        result = await process_single_page(page, WIKI_DUMP_PATH, i, len(pages))
        
        if result:
            all_results.append(result)
        else:
            logger.warning(f"✗ Skipped page {i}")
    
    total_time = time.time() - start_time
    logger.info(f"\n{'='*70}")
    logger.info(f"Test complete!")
    logger.info(f"Total pages: {len(all_results)}/{len(pages)}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")
    logger.info(f"Average per page: {total_time/len(all_results):.1f}s")
    logger.info(f"{'='*70}\n")
    
    save_results(all_results, timestamp)
    logger.info(f"✓ Results saved to {OUTPUT_FILE}")
    
    # Quick speed summary
    logger.info("\n" + "="*70)
    logger.info("QUICK SPEED COMPARISON")
    logger.info("="*70)
    
    for model in MODELS:
        times = []
        for result in all_results:
            for m in result['models']:
                if m.get('model') == model['name'] and 'total_processing_time' in m:
                    times.append(m['total_processing_time'])
        
        if times:
            avg_time = sum(times) / len(times)
            logger.info(f"{model['name']:<25} Average: {avg_time:.1f}s")
    
    logger.info("="*70)
    logger.info("\nRun 'python analysis/evaluate_3models.py' for full analysis")


if __name__ == "__main__":
    asyncio.run(main())