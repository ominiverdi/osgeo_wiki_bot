# db/test_large_pages.py
import os
import sys
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Test with granite-4.0-h-tiny only
# MODEL = {
#     "name": "granite-4.0-h-tiny",
#     "url": "http://localhost:8080/v1/chat/completions"
# }
MODEL = {
    "name": "mistral-small-128k",
    "url": "http://localhost:8080/v1/chat/completions"
}
WIKI_DUMP_PATH = Path(os.getenv('WIKI_DUMP_PATH', './wiki_dump'))
OUTPUT_FILE = 'large_pages_stress_test.json'

# Specific large files to test
TEST_FILES = [
    # Huge pages (>20KB)
    ('VXNlcm1hcC1kZXZlbG9w', 'Usermap-develop', 650644),
    ('T1NHZW9fQW1iYXNzYWRvcg', 'OSGeo Advocate', 615232),
    ('SmVmZl9NY0tlbm5h', 'Jeff McKenna', 531040),
    # Large pages (10-20KB) - we'll find these
    # Medium pages (5-10KB) - baseline
]


# Around line 34-57, replace the read_wiki_file function:

def read_wiki_file(filepath):
    """Read and parse a wiki dump file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        url = lines[0].replace('URL: ', '').strip() if lines else ''
        title = lines[1].replace('Title: ', '').strip() if len(lines) > 1 else ''
        
        # Find where content starts (after "Content:" line)
        content_start = 0
        for i, line in enumerate(lines):
            if line.strip() == 'Content:':
                content_start = i + 1
                break
        
        page_content = '\n'.join(lines[content_start:]).strip()
        
        # TRUNCATE TO 20KB IF NEEDED
        MAX_CONTENT_SIZE = 20000
        was_truncated = False
        if len(page_content) > MAX_CONTENT_SIZE:
            page_content = page_content[:MAX_CONTENT_SIZE]
            page_content += "\n\n[Content truncated at 20KB for processing]"
            was_truncated = True
        
        return {
            'url': url,
            'title': title,
            'content': page_content,
            'content_length': len(page_content),
            'was_truncated': was_truncated,
            'original_length': len('\n'.join(lines[content_start:]).strip())
        }
    except Exception as e:
        logger.error(f"Error reading file {filepath}: {e}")
        return None

async def generate_resume(model_config, content):
    """Generate resume from content."""
    prompt = f"""Extract factual information from this wiki page content and create a structured summary.

CRITICAL RULES:
- Preserve ALL names, usernames, email addresses, and website URLs exactly as written
- Maintain ALL date information precisely (years, months, events)
- Convert tables into explicit statements of relationships
- Include ALL project names, committee roles, and organizational structures
- Begin each distinct fact with "* " to create an implicit list structure

WHAT TO EMPHASIZE:
- Facts over descriptions
- Relationships over general information
- Specific details over broad concepts

WHAT TO AVOID:
- Do NOT use unnecessary language like "This page describes" or "The content explains that"
- Do NOT reorganize information by themes
- Do NOT add interpretive summaries

Output ONLY the factual bullet points, nothing else.

Page content:
{content}

FACTUAL SUMMARY (200-300 words):"""

    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                model_config['url'],
                json={
                    "model": model_config['name'],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 4096
                }
            )
            response.raise_for_status()
            result = response.json()
            resume = result['choices'][0]['message']['content'].strip()
            
            processing_time = time.time() - start_time
            return {
                'resume': resume,
                'processing_time': processing_time
            }
    except Exception as e:
        logger.error(f"Error generating resume: {e}")
        return {
            'resume': f"ERROR: {str(e)}",
            'processing_time': time.time() - start_time
        }


async def generate_keywords(model_config, content):
    """Generate keywords from content."""
    prompt = f"""Extract important keywords from this wiki page content.

EXTRACT:
- Names of people, organizations, projects, and places
- Technical terms and their variations
- Important dates, versions, and events
- Key concepts that distinguish this page

RULES:
- Extract terms that actually appear in the content
- Each keyword should appear only once
- Return ONLY the keywords as a simple comma-separated list

LIMIT: 20-30 keywords maximum

Page content:
{content}

KEYWORDS:"""

    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                model_config['url'],
                json={
                    "model": model_config['name'],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1024
                }
            )
            response.raise_for_status()
            result = response.json()
            keywords = result['choices'][0]['message']['content'].strip()
            
            processing_time = time.time() - start_time
            return {
                'keywords': keywords,
                'processing_time': processing_time
            }
    except Exception as e:
        logger.error(f"Error generating keywords: {e}")
        return {
            'keywords': f"ERROR: {str(e)}",
            'processing_time': time.time() - start_time
        }


async def process_file(filename, title, expected_size):
    """Process a single large file."""
    filepath = WIKI_DUMP_PATH / filename
    
    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return None
    
    logger.info(f"\nProcessing: {title}")
    logger.info(f"  Expected size: {expected_size:,} bytes")
    
    # Read file
    wiki_data = read_wiki_file(filepath)
    if not wiki_data:
        return None
    
    actual_size = wiki_data['content_length']
    logger.info(f"  Actual content size: {actual_size:,} chars")
    
    # Generate resume
    logger.info("  → Generating resume...")
    resume_result = await generate_resume(MODEL, wiki_data['content'])
    logger.info(f"  ✓ Resume completed in {resume_result['processing_time']:.1f}s")
    
    # Generate keywords
    logger.info("  → Generating keywords...")
    keywords_result = await generate_keywords(MODEL, wiki_data['content'])
    logger.info(f"  ✓ Keywords completed in {keywords_result['processing_time']:.1f}s")
    
    total_time = resume_result['processing_time'] + keywords_result['processing_time']
    logger.info(f"  ✓ Total: {total_time:.1f}s")
    
    return {
        'filename': filename,
        'title': title,
        'expected_size': expected_size,
        'actual_content_size': actual_size,
        'was_truncated': wiki_data.get('was_truncated', False),  
        'original_size': wiki_data.get('original_length', actual_size), 
        'resume': resume_result['resume'],
        'resume_length': len(resume_result['resume']),
        'resume_time': resume_result['processing_time'],
        'keywords': keywords_result['keywords'],
        'keywords_time': keywords_result['processing_time'],
        'total_time': total_time,
        'time_per_kb': total_time / (actual_size / 1000) if actual_size > 0 else 0
    }


def find_additional_test_files():
    """Find some large (10-20KB) and medium (5-10KB) files for comparison."""
    additional = []
    
    for filepath in WIKI_DUMP_PATH.glob('*'):
        if filepath.name == 'url_map.json':
            continue
            
        size = filepath.stat().st_size
        
        # Skip if already in TEST_FILES
        if filepath.name in [f[0] for f in TEST_FILES]:
            continue
        
        # Get title
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                title = lines[1].replace('Title: ', '').strip() if len(lines) > 1 else filepath.name
        except:
            title = filepath.name
        
        # Collect large and medium files
        if 10000 <= size <= 20000 and len([f for f in additional if 10000 <= f[2] <= 20000]) < 2:
            additional.append((filepath.name, title, size))
        elif 5000 <= size <= 10000 and len([f for f in additional if 5000 <= f[2] <= 10000]) < 2:
            additional.append((filepath.name, title, size))
        
        # Stop when we have enough
        if len([f for f in additional if 10000 <= f[2] <= 20000]) >= 2 and \
           len([f for f in additional if 5000 <= f[2] <= 10000]) >= 2:
            break
    
    return additional


async def main():
    import asyncio
    
    start_time = time.time()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    logger.info("="*70)
    logger.info("LARGE PAGES STRESS TEST")
    logger.info("="*70)
    logger.info(f"Model: {MODEL['name']}")
    logger.info(f"Testing pages from 5KB to 650KB")
    logger.info("="*70 + "\n")
    
    # Find additional test files
    logger.info("Finding additional test files...")
    additional_files = find_additional_test_files()
    
    all_test_files = TEST_FILES + additional_files
    logger.info(f"Total test files: {len(all_test_files)}\n")
    
    # Sort by size
    all_test_files = sorted(all_test_files, key=lambda x: x[2])
    
    results = []
    
    for filename, title, size in all_test_files:
        result = await process_file(filename, title, size)
        if result:
            results.append(result)
    
    total_time = time.time() - start_time
    
    logger.info(f"\n{'='*70}")
    logger.info("STRESS TEST COMPLETE")
    logger.info(f"{'='*70}")
    logger.info(f"Total files processed: {len(results)}/{len(all_test_files)}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")
    logger.info(f"Average per file: {total_time/len(results):.1f}s")
    logger.info(f"{'='*70}\n")
    
    # Analysis
    logger.info("PROCESSING TIME ANALYSIS")
    logger.info("-"*70)
    for result in results:
        size_kb = result['actual_content_size'] / 1000
        logger.info(f"{result['title'][:50]:<50} {size_kb:>6.1f}KB  {result['total_time']:>6.1f}s  {result['time_per_kb']:>5.2f}s/KB")
    
    # Save results
    output_path = Path(OUTPUT_FILE)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'test_config': {
                'model': MODEL['name'],
                'file_count': len(results),
                'timestamp': timestamp
            },
            'results': results
        }, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n✓ Results saved to {OUTPUT_FILE}")
    
    # Check for problems
    logger.info("\n" + "="*70)
    logger.info("QUALITY CHECK")
    logger.info("="*70)
    
    problems = []
    for result in results:
        if 'ERROR' in result['resume']:
            problems.append(f"❌ {result['title']}: Resume generation failed")
        elif len(result['resume']) < 100:
            problems.append(f"⚠ {result['title']}: Resume too short ({result['resume_length']} chars)")
        elif result['total_time'] > 300:
            problems.append(f"⚠ {result['title']}: Very slow ({result['total_time']:.1f}s)")
    
    if problems:
        logger.info("Issues found:")
        for p in problems:
            logger.info(f"  {p}")
    else:
        logger.info("✓ No major issues detected")
    
    logger.info("\n" + "="*70)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())