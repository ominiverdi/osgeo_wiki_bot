#!/usr/bin/env python3
"""
Test SQL template generation for OSGeo Wiki Bot.
End-to-end: Query → LLM extraction → SQL generation → DB execution → Answer

Usage:
    python tests/sql_templates.py        # Run all tests
    python tests/sql_templates.py -v     # Verbose output with results
"""
import os
import sys
import time
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, List
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from template_search module
# When integrated: from mcp_server.handlers.template_search import ...
from mcp_server.handlers.template_search import (
    extract_params,
    build_sql,
    generate_answer,
    get_decline_message,
    normalize_params,
)

load_dotenv()

LLM_SERVER = os.getenv("LLM_SERVER", "http://localhost:8080")

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'osgeo_wiki'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}


# ============================================================================
# DB EXECUTION
# ============================================================================

def get_connection():
    """Get database connection."""
    return psycopg2.connect(**DB_CONFIG)


def execute_sql(conn, sql: str) -> Dict[str, Any]:
    """Execute SQL and return results."""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            results = cur.fetchall()
        return {'success': True, 'results': [dict(r) for r in results], 'count': len(results)}
    except Exception as e:
        return {'success': False, 'error': str(e), 'results': [], 'count': 0}


# ============================================================================
# TEST CASES
# ============================================================================

TEST_CASES = [
    # Type 1: Definition queries
    {
        "query": "What is QGIS?",
        "expect_action": ["search_title", "search_semantic"],
        "expect_entity": "QGIS",
        "min_results": 1
    },
    {
        "query": "What is GDAL?",
        "expect_action": ["search_title", "search_semantic"],
        "expect_entity": "GDAL",
        "min_results": 1
    },
    {
        "query": "What is PostGIS?",
        "expect_action": ["search_title", "search_semantic"],
        "expect_entity": "PostGIS",
        "min_results": 1
    },
    
    # Type 2: How-to queries
    {
        "query": "How to add news to WordPress site",
        "expect_action": ["search_fulltext", "search_semantic"],
        "expect_terms": ["news", "WordPress"],
        "min_results": 0
    },
    {
        "query": "How to join OSGeo",
        "expect_action": ["search_fulltext", "search_semantic"],
        "expect_terms": ["join", "OSGeo"],
        "min_results": 1
    },
    
    # Type 3: Person queries - test spelling preservation
    {
        "query": "Who is ominiverdi?",
        "expect_action": ["search_graph", "search_title"],
        "expect_entity": "ominiverdi",
        "min_results": 1
    },
    {
        "query": "Who is Frank Warmerdam?",
        "expect_action": ["search_graph", "search_title"],
        "expect_entity": "Frank Warmerdam",
        "min_results": 1
    },
    {
        "query": "Who is Venkatesh Raghavan?",
        "expect_action": ["search_graph", "search_title"],
        "expect_entity": "Venkatesh Raghavan",
        "min_results": 0
    },
    
    # Type 4: Relationship queries (single entity)
    {
        "query": "What projects did Frank Warmerdam work on?",
        "expect_action": ["search_graph"],
        "expect_entity": "Frank Warmerdam",
        "expect_pattern": ["outgoing", "about"],
        "min_results": 1
    },
    {
        "query": "Who contributed to GDAL?",
        "expect_action": ["search_graph"],
        "expect_entity": "GDAL",
        "expect_pattern": ["incoming", "about"],
        "min_results": 1
    },
    {
        "query": "Who contributed to MapServer?",
        "expect_action": ["search_graph"],
        "expect_entity": "MapServer",
        "expect_pattern": ["incoming", "about"],
        "min_results": 0
    },
    
    # Type 5: Relationship queries (two entities)
    {
        "query": "What is the relationship between QGIS and OSGeo?",
        "expect_action": ["search_graph"],
        "expect_entity": "QGIS",
        "expect_entity2": "OSGeo",
        "expect_pattern": ["between"],
        "min_results": 1
    },
    {
        "query": "How is GeoServer connected to OSGeo?",
        "expect_action": ["search_graph"],
        "expect_entity": "GeoServer",
        "expect_entity2": "OSGeo",
        "expect_pattern": ["between"],
        "min_results": 0
    },
    
    # Type 6: List queries
    {
        "query": "List all OSGeo projects",
        "expect_action": ["search_graph", "search_semantic"],
        "expect_entity": "OSGeo",
        "expect_pattern": ["incoming"],
        "min_results": 1
    },
    
    # ========================================================================
    # EDGE CASES - Out of scope queries
    # ========================================================================
    
    # Type 7: Image/media requests
    {
        "query": "describe this image in detail mxc://osgeo.org/neEXgRAFlWoRUGRKGBtyDDxv",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    
    # Type 8: Non-OSGeo topics
    {
        "query": "What's the weather in Barcelona?",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    {
        "query": "Who won the World Cup 2022?",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    
    # Type 9: Gibberish
    {
        "query": "asdfghjkl qwerty zxcvbn",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    
    # Type 10: Empty/greeting
    {
        "query": "hi",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    {
        "query": "hello, how are you?",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    
    # Type 11: SQL injection attempt
    {
        "query": "'; DROP TABLE pages; --",
        "expect_action": ["out_of_scope"],
        "expect_decline": True,
        "min_results": 0
    },
    
    # Type 12: Non-English (should still try if OSGeo-related)
    {
        "query": "Qu'est-ce que QGIS?",
        "expect_action": ["search_title", "search_semantic", "out_of_scope"],
        "expect_entity": "QGIS",
        "min_results": 0
    },
    
    # ========================================================================
    # TEMPORAL QUERIES
    # ========================================================================
    
    # Type 13: When queries
    {
        "query": "When was FOSS4G 2022?",
        "expect_action": ["search_fulltext", "search_semantic", "search_title"],
        "expect_terms": ["FOSS4G", "2022"],
        "min_results": 0
    },
    {
        "query": "When was OSGeo founded?",
        "expect_action": ["search_fulltext", "search_semantic", "search_title"],
        "expect_terms": ["OSGeo", "founded"],
        "min_results": 0
    },
]


# ============================================================================
# VALIDATION
# ============================================================================

def validate_extraction(params: Dict[str, Any], test: Dict[str, Any]) -> tuple:
    """
    Validate LLM extraction against expected values.
    Returns (passed: bool, errors: list)
    """
    errors = []
    
    # Check action
    if "expect_action" in test:
        if params.get("action") not in test["expect_action"]:
            errors.append(f"action: got '{params.get('action')}', expected one of {test['expect_action']}")
    
    # For out_of_scope, we only need to validate the action
    if test.get("expect_decline") and params.get("action") == "out_of_scope":
        return True, []
    
    # Check entity (main_term or entity field)
    if "expect_entity" in test:
        entity = params.get("entity") or params.get("main_term", "")
        if entity:
            expected = test["expect_entity"].lower()
            if expected not in entity.lower():
                errors.append(f"entity: got '{entity}', expected '{test['expect_entity']}'")
    
    # Check entity2
    if "expect_entity2" in test:
        entity2 = params.get("entity2", "")
        expected = test["expect_entity2"].lower()
        if expected not in entity2.lower():
            errors.append(f"entity2: got '{entity2}', expected '{test['expect_entity2']}'")
    
    # Check graph pattern
    if "expect_pattern" in test:
        pattern = params.get("graph_pattern", "")
        if pattern not in test["expect_pattern"]:
            errors.append(f"graph_pattern: got '{pattern}', expected one of {test['expect_pattern']}")
    
    # Check search terms
    if "expect_terms" in test:
        search_terms = params.get("search_terms", "")
        if isinstance(search_terms, list):
            search_terms = " ".join(search_terms)
        main_term = params.get("main_term", "")
        if isinstance(main_term, list):
            main_term = " ".join(main_term)
        terms = (search_terms + " " + main_term).lower()
        for expected_term in test["expect_terms"]:
            if expected_term.lower() not in terms:
                errors.append(f"terms: missing '{expected_term}' in '{terms}'")
    
    return len(errors) == 0, errors


# ============================================================================
# TEST RUNNER
# ============================================================================

async def run_pipeline_test(test: Dict[str, Any], conn, verbose: bool = False) -> Dict[str, Any]:
    """Run full pipeline test for one query."""
    query = test["query"]
    result = {
        "query": query,
        "extraction_ok": False,
        "sql_ok": False,
        "db_ok": False,
        "errors": [],
        "params": None,
        "sql": None,
        "db_results": 0,
        "db_rows": [],
        "answer": None,
        "llm_time_ms": 0,
        "db_time_ms": 0,
        "answer_time_ms": 0,
        "total_time_ms": 0
    }
    
    total_start = time.time()
    
    # Step 1: LLM extraction
    try:
        llm_start = time.time()
        params = await extract_params(query, LLM_SERVER)
        result["llm_time_ms"] = int((time.time() - llm_start) * 1000)
        
        if params is None:
            result["errors"].append("LLM returned invalid JSON")
            return result
        
        result["params"] = params
    except Exception as e:
        result["errors"].append(f"LLM error: {e}")
        return result
    
    # Step 2: Validate extraction
    passed, errors = validate_extraction(params, test)
    if not passed:
        result["errors"].extend(errors)
    else:
        result["extraction_ok"] = True
    
    # Handle out_of_scope action
    if params.get("action") == "out_of_scope":
        result["sql_ok"] = True
        result["db_ok"] = True
        decline_reason = params.get("decline_reason", "")
        result["answer"] = get_decline_message(decline_reason)
        result["answer_time_ms"] = 0
        result["total_time_ms"] = int((time.time() - total_start) * 1000)
        return result
    
    # Step 3: Build SQL
    normalized = normalize_params(params)
    sql = build_sql(normalized)
    if sql is None:
        result["errors"].append(f"build_sql returned None for params: {normalized}")
        return result
    result["sql"] = sql
    result["sql_ok"] = True
    
    # Step 4: Execute SQL
    db_start = time.time()
    db_result = execute_sql(conn, sql)
    result["db_time_ms"] = int((time.time() - db_start) * 1000)
    
    if not db_result["success"]:
        result["errors"].append(f"DB error: {db_result['error']}")
        return result
    
    result["db_results"] = db_result["count"]
    result["db_rows"] = db_result["results"][:5]
    if db_result["count"] >= test.get("min_results", 1):
        result["db_ok"] = True
    else:
        result["errors"].append(f"Expected >= {test.get('min_results', 1)} results, got {db_result['count']}")
    
    # Step 5: Generate answer
    if db_result["count"] > 0:
        try:
            answer_start = time.time()
            answer = await generate_answer(query, db_result["results"][:5], normalized["action"], LLM_SERVER)
            result["answer_time_ms"] = int((time.time() - answer_start) * 1000)
            result["answer"] = answer
        except Exception as e:
            result["errors"].append(f"Answer generation error: {e}")
            result["answer"] = None
            result["answer_time_ms"] = 0
    else:
        result["answer"] = "No results found to generate answer."
        result["answer_time_ms"] = 0
    
    result["total_time_ms"] = int((time.time() - total_start) * 1000)
    
    return result


async def run_tests(verbose: bool = False) -> tuple:
    """Run all test cases and return (passed, failed) counts."""
    conn = get_connection()
    passed = 0
    failed = 0
    total_llm_time = 0
    total_db_time = 0
    total_answer_time = 0
    
    for i, test in enumerate(TEST_CASES, 1):
        result = await run_pipeline_test(test, conn, verbose)
        
        all_ok = result["extraction_ok"] and result["sql_ok"] and result["db_ok"]
        total_llm_time += result["llm_time_ms"]
        total_db_time += result["db_time_ms"]
        total_answer_time += result.get("answer_time_ms", 0)
        
        timing = f"[Extract:{result['llm_time_ms']}ms DB:{result['db_time_ms']}ms Answer:{result.get('answer_time_ms', 0)}ms Total:{result['total_time_ms']}ms]"
        
        if all_ok:
            print(f"[{i}] PASS: {result['query']}")
            print(f"     {timing}")
            if result.get("answer"):
                print(f"     ANSWER: {result['answer']}")
            if verbose:
                print(f"     Params: {result['params']}")
                print(f"     DB results: {result['db_results']}")
                if result.get('db_rows'):
                    print(f"     Results:")
                    for j, row in enumerate(result['db_rows'][:5], 1):
                        title = row.get('page_title') or row.get('title') or row.get('subject', '')
                        url = row.get('wiki_url') or row.get('url') or row.get('source_page_url', '')
                        if 'predicate' in row:
                            print(f"       {j}. {row.get('subject')} --{row.get('predicate')}--> {row.get('object')}")
                            if url:
                                print(f"          {url}")
                        else:
                            print(f"       {j}. {title}")
                            if url:
                                print(f"          {url}")
            passed += 1
        else:
            print(f"[{i}] FAIL: {result['query']}")
            print(f"     {timing}")
            print(f"     Params: {result['params']}")
            for err in result["errors"]:
                print(f"     - {err}")
            if verbose and result["sql"]:
                print(f"     SQL: {result['sql'][:200]}...")
            failed += 1
        
        print()
    
    conn.close()
    
    total_time = total_llm_time + total_db_time + total_answer_time
    print("="*80)
    print(f"Timing breakdown:")
    print(f"  Extraction LLM: {total_llm_time}ms total, {total_llm_time // len(TEST_CASES)}ms avg")
    print(f"  DB queries:     {total_db_time}ms total, {total_db_time // len(TEST_CASES)}ms avg")
    print(f"  Answer LLM:     {total_answer_time}ms total, {total_answer_time // len(TEST_CASES)}ms avg")
    print(f"  TOTAL:          {total_time}ms total, {total_time // len(TEST_CASES)}ms avg per query")
    
    return passed, failed


if __name__ == "__main__":
    print("="*80)
    print("SQL TEMPLATE PIPELINE TESTS")
    print("="*80 + "\n")
    
    verbose = "-v" in sys.argv
    
    passed, failed = asyncio.run(run_tests(verbose=verbose))
    
    print("\n" + "="*80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*80)
    
    sys.exit(0 if failed == 0 else 1)