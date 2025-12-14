#!/usr/bin/env python3
"""
Evaluate Extension Models - Dry-run testing of OpenRouter free models

Tests multiple models on sample wiki pages to compare:
- Output quality (follows format, extracts facts)
- Response time
- Token usage
- Rate limit behavior

Usage:
    python db/evaluate_extension_models.py --pages 3
    python db/evaluate_extension_models.py --models "moonshotai/kimi-k2-instruct:free,mistralai/mistral-small-3.1-24b-instruct:free"
"""

import os
import sys
import json
import asyncio
import time
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

import httpx
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# OpenRouter configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# All available free models on OpenRouter
# Status: OK=working, QUOTA=easy rate limit, 404=not found, EMPTY=empty output, SLOW=very slow
# Score: quality score from testing (0-100), Time: avg response time in seconds
ALL_FREE_MODELS = {
    # TOP TIER - Best quality and reliability
    "mistralai/devstral-2512:free": "OK",  # Score:80, Time:8s, reliable, fast
    "google/gemma-3-27b-it:free": "OK",  # Score:80, Time:13s, good quality
    "tngtech/deepseek-r1t2-chimera:free": "OK",  # Score:100, Time:67s, best quality but slow
    # GOOD - Work well but have issues
    "nvidia/nemotron-nano-9b-v2:free": "QUOTA",  # Score:100, Time:39s, best but easy 429
    "meta-llama/llama-3.3-70b-instruct:free": "QUOTA",  # Score:100, Time:13s, great but quota
    "google/gemma-3-12b-it:free": "OK",  # Score:60, Time:28s, reliable fallback
    "qwen/qwen3-4b:free": "QUOTA",  # Score:80, Time:15s, fast but quota
    "mistralai/mistral-7b-instruct:free": "QUOTA",  # Score:80, Time:27s, decent but quota
    # MEDIOCRE - Work but not ideal
    "amazon/nova-2-lite-v1:free": "QUOTA",  # Score:50, Time:25s, keywords often empty
    "qwen/qwen3-coder:free": "SLOW",  # Score:30, Time:65s, slow, poor format
    "qwen/qwen3-235b-a22b:free": "SLOW",  # Score:30, Time:120s+, very slow
    # BROKEN - Don't use
    "openai/gpt-oss-20b:free": "EMPTY",  # Returns empty resume
    "openai/gpt-oss-120b:free": "404",  # Not found
    "moonshotai/kimi-k2:free": "404",  # Not found
    "nousresearch/hermes-3-llama-3.1-405b:free": "QUOTA",  # Always 429
    "allenai/olmo-3-32b-think:free": "QUOTA",  # Always 429
    "google/gemini-2.0-flash-exp:free": "QUOTA",  # Always 429
    # UNTESTED
    "mistralai/mistral-small-3.1-24b-instruct:free": "QUOTA",  # Good but easy 429
    "nvidia/nemotron-nano-12b-v2-vl:free": "UNTESTED",
}

# Recommended models for production (in priority order)
# Strategy: Try fast reliable models first, fallback to slower ones
RECOMMENDED_MODELS = [
    "mistralai/devstral-2512:free",  # Primary: fast (8s), reliable, score 80
    "google/gemma-3-27b-it:free",  # Fallback 1: good quality (80), 13s
    "google/gemma-3-12b-it:free",  # Fallback 2: reliable (60), 28s
    "tngtech/deepseek-r1t2-chimera:free",  # Fallback 3: best quality but slow (67s)
]

# Models to actually test (whitelist) - modify this list for each test batch
DEFAULT_MODELS = RECOMMENDED_MODELS

# Rate limiting - conservative to avoid 429s across providers
REQUESTS_PER_MINUTE = 8
REQUEST_DELAY = 60 / REQUESTS_PER_MINUTE  # 7.5 seconds

MAX_CONTENT_LENGTH = 8000  # Shorter for evaluation
LLM_TIMEOUT = 120


@dataclass
class ModelResult:
    model: str
    page_title: str
    resume: str
    keywords: str
    resume_time: float
    keywords_time: float
    total_time: float
    resume_tokens: int
    keywords_tokens: int
    error: str | None = None


def get_db_connection():
    """Connect to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "osgeo_wiki"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5432"),
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        return None


def get_sample_pages(conn, limit: int = 3) -> list[dict]:
    """Get sample pages from source_pages for testing."""
    with conn.cursor() as cur:
        # Get pages with reasonable content length, varied types
        cur.execute(
            """
            SELECT id, title, url, content_text, 
                   LENGTH(content_text) as content_length
            FROM source_pages
            WHERE content_text IS NOT NULL 
              AND LENGTH(content_text) > 500
              AND LENGTH(content_text) < 50000
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

        pages = []
        for row in rows:
            content = row[3]
            if len(content) > MAX_CONTENT_LENGTH:
                content = (
                    content[:MAX_CONTENT_LENGTH]
                    + "\n\n[Content truncated for evaluation]"
                )
            pages.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "url": row[2],
                    "content": content,
                    "original_length": row[4],
                }
            )
        return pages


async def call_openrouter(
    model: str, prompt: str, timeout: int = LLM_TIMEOUT
) -> tuple[str, int, float]:
    """
    Call OpenRouter API.

    Returns:
        Tuple of (response_text, tokens_used, elapsed_time)
    """
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set in environment")

    start = time.time()

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com/osgeo/wiki_bot",
                "X-Title": "OSGeo Wiki Bot Evaluation",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )

        elapsed = time.time() - start

        # Log rate limit info from headers
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining:
            logger.debug(f"  Rate limit remaining: {remaining}, reset: {reset}")

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise Exception(f"Rate limited (429), retry after: {retry_after}s")

        response.raise_for_status()
        result = response.json()

        text = result["choices"][0]["message"]["content"].strip()
        tokens = result.get("usage", {}).get("total_tokens", 0)

        return text, tokens, elapsed


def build_resume_prompt(content: str) -> str:
    """Build the resume extraction prompt."""
    return f"""Extract ONLY the facts that appear in this text. Do not explain or expand.

Rules:
- Start each line with "* "
- Copy names, dates, URLs exactly
- If text is 1-2 sentences, just repeat it with "* " prefix
- Never explain what terms mean
- Maximum 15 bullet points

Text:
{content}

BULLET POINTS:"""


def build_keywords_prompt(content: str) -> str:
    """Build the keywords extraction prompt."""
    return f"""Extract keywords that appear in this text. Do not add related terms.

Include: names, organizations, projects, technical terms, dates.
Maximum 30 keywords, comma-separated.
If minimal content, write: placeholder

Text:
{content}

KEYWORDS:"""


async def evaluate_model_on_page(model: str, page: dict) -> ModelResult:
    """Evaluate a single model on a single page."""
    title = page["title"]
    content = page["content"]

    logger.info(f"  Testing {model} on '{title}'...")

    try:
        # Generate resume
        resume_prompt = build_resume_prompt(content)
        resume, resume_tokens, resume_time = await call_openrouter(model, resume_prompt)

        # Rate limit delay
        await asyncio.sleep(REQUEST_DELAY)

        # Generate keywords
        keywords_prompt = build_keywords_prompt(content)
        keywords, keywords_tokens, keywords_time = await call_openrouter(
            model, keywords_prompt
        )

        return ModelResult(
            model=model,
            page_title=title,
            resume=resume,
            keywords=keywords,
            resume_time=resume_time,
            keywords_time=keywords_time,
            total_time=resume_time + keywords_time,
            resume_tokens=resume_tokens,
            keywords_tokens=keywords_tokens,
        )

    except Exception as e:
        logger.error(f"  Error with {model}: {e}")
        return ModelResult(
            model=model,
            page_title=title,
            resume="",
            keywords="",
            resume_time=0,
            keywords_time=0,
            total_time=0,
            resume_tokens=0,
            keywords_tokens=0,
            error=str(e),
        )


def analyze_result(result: ModelResult) -> dict:
    """Analyze quality of a model result."""
    analysis = {
        "model": result.model,
        "page": result.page_title,
        "error": result.error,
    }

    if result.error:
        analysis["quality_score"] = 0
        return analysis

    # Resume quality checks
    resume_lines = [l for l in result.resume.split("\n") if l.strip()]
    resume_bullet_lines = [l for l in resume_lines if l.strip().startswith("*")]

    analysis["resume_lines"] = len(resume_lines)
    analysis["resume_bullet_lines"] = len(resume_bullet_lines)
    analysis["resume_format_ok"] = len(resume_bullet_lines) >= len(resume_lines) * 0.8
    analysis["resume_length"] = len(result.resume)

    # Keywords quality checks
    keywords_list = [k.strip() for k in result.keywords.split(",") if k.strip()]
    analysis["keywords_count"] = len(keywords_list)
    analysis["keywords_format_ok"] = (
        len(keywords_list) > 0 and "placeholder" not in result.keywords.lower()
    )

    # Timing
    analysis["resume_time"] = round(result.resume_time, 2)
    analysis["keywords_time"] = round(result.keywords_time, 2)
    analysis["total_time"] = round(result.total_time, 2)
    analysis["total_tokens"] = result.resume_tokens + result.keywords_tokens

    # Quality score (simple heuristic)
    score = 0
    if analysis["resume_format_ok"]:
        score += 30
    if 3 <= analysis["resume_bullet_lines"] <= 15:
        score += 20
    if analysis["keywords_format_ok"]:
        score += 30
    if 5 <= analysis["keywords_count"] <= 30:
        score += 20

    analysis["quality_score"] = score

    return analysis


def save_to_database(
    conn, result: ModelResult, analysis: dict, page_id: int | None = None
):
    """Save evaluation result to database."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_evaluation 
                (model, page_title, page_id, resume, keywords, 
                 resume_time, keywords_time, total_tokens, quality_score, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result.model,
                    result.page_title,
                    page_id,
                    result.resume if not result.error else None,
                    result.keywords if not result.error else None,
                    result.resume_time if not result.error else None,
                    result.keywords_time if not result.error else None,
                    analysis.get("total_tokens"),
                    analysis.get("quality_score"),
                    result.error,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save to database: {e}")
        conn.rollback()


def print_comparison(results: list[ModelResult], analyses: list[dict]):
    """Print comparison table."""
    print("\n" + "=" * 80)
    print("MODEL COMPARISON RESULTS")
    print("=" * 80)

    # Group by page
    pages = {}
    for result, analysis in zip(results, analyses):
        page = result.page_title
        if page not in pages:
            pages[page] = []
        pages[page].append((result, analysis))

    for page_title, page_results in pages.items():
        print(f"\n--- Page: {page_title} ---\n")

        # Sort by quality score
        page_results.sort(key=lambda x: x[1]["quality_score"], reverse=True)

        for result, analysis in page_results:
            model_short = result.model.split("/")[-1].replace(":free", "")

            if analysis["error"]:
                print(f"  {model_short}: ERROR - {analysis['error']}")
                continue

            print(f"  {model_short}:")
            print(f"    Quality: {analysis['quality_score']}/100")
            print(
                f"    Resume: {analysis['resume_bullet_lines']} bullets, {analysis['resume_time']:.1f}s"
            )
            print(
                f"    Keywords: {analysis['keywords_count']} keywords, {analysis['keywords_time']:.1f}s"
            )
            print(f"    Tokens: {analysis['total_tokens']}")

            # Show first 2 resume lines as sample
            lines = [l for l in result.resume.split("\n") if l.strip()][:2]
            for line in lines:
                print(f"      {line[:70]}{'...' if len(line) > 70 else ''}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY (Average across all pages)")
    print("=" * 80)

    model_stats = {}
    for analysis in analyses:
        model = analysis["model"]
        if model not in model_stats:
            model_stats[model] = {"scores": [], "times": [], "errors": 0}

        if analysis["error"]:
            model_stats[model]["errors"] += 1
        else:
            model_stats[model]["scores"].append(analysis["quality_score"])
            model_stats[model]["times"].append(analysis["total_time"])

    print(f"\n{'Model':<45} {'Avg Score':>10} {'Avg Time':>10} {'Errors':>8}")
    print("-" * 75)

    for model, stats in sorted(
        model_stats.items(), key=lambda x: -sum(x[1]["scores"]) if x[1]["scores"] else 0
    ):
        model_short = model.split("/")[-1].replace(":free", "")
        avg_score = (
            sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0
        )
        avg_time = sum(stats["times"]) / len(stats["times"]) if stats["times"] else 0
        print(
            f"{model_short:<45} {avg_score:>10.1f} {avg_time:>9.1f}s {stats['errors']:>8}"
        )


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Evaluate OpenRouter models for extension generation"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of sample pages to test (default: 3)",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated list of models to test (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="model_evaluation_results.json",
        help="Output file for results (default: model_evaluation_results.json)",
    )

    args = parser.parse_args()

    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set in .env file")
        print("Add: OPENROUTER_API_KEY=your_key_here")
        sys.exit(1)

    models = args.models.split(",") if args.models else DEFAULT_MODELS

    print(f"Evaluating {len(models)} models on {args.pages} pages")
    print(f"Models: {', '.join(m.split('/')[-1] for m in models)}")

    # Get sample pages
    conn = get_db_connection()
    if not conn:
        print("ERROR: Could not connect to database")
        sys.exit(1)

    pages = get_sample_pages(conn, args.pages)

    if not pages:
        print("ERROR: No sample pages found in source_pages")
        conn.close()
        sys.exit(1)

    print(f"\nSample pages:")
    for p in pages:
        print(f"  - {p['title']} ({p['original_length']} chars)")

    # Evaluate each model on each page
    all_results = []
    all_analyses = []

    for page in pages:
        print(f"\n--- Testing page: {page['title']} ---")

        for model in models:
            result = await evaluate_model_on_page(model, page)
            analysis = analyze_result(result)

            # Save to database
            save_to_database(conn, result, analysis, page.get("id"))

            all_results.append(result)
            all_analyses.append(analysis)

            # Rate limit between models
            await asyncio.sleep(REQUEST_DELAY)

    conn.close()

    # Print comparison
    print_comparison(all_results, all_analyses)

    # Save full results
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "models_tested": models,
        "pages_tested": [p["title"] for p in pages],
        "results": [asdict(r) for r in all_results],
        "analyses": all_analyses,
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nFull results saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
