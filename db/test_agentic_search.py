#!/usr/bin/env python3
"""
Agentic Search: LLM decides which searches to run, generates SQL,
evaluates results, and can retry with refinements.

The agent has access to three data sources and can iteratively
search until it finds satisfactory results (max 3 iterations).
"""

import os
import time
import json
import re
import asyncio
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'osgeo_wiki'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

LLM_SERVER = os.getenv('LLM_SERVER', 'http://localhost:8080')

TEST_QUERIES = [
    'What is QGIS?',  # Easy - definition query
    'How is GDAL connected to Frank Warmerdam?',  # Medium - simple relationship
    'What projects did Frank Warmerdam create?',  # Hard - requires good SQL
]


async def call_llm(prompt, timeout=60):
    """Call LLM API"""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{LLM_SERVER}/v1/chat/completions",
            json={
                "model": "granite-4.0-h-tiny-32k",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.1
            }
        )
        result = response.json()
        return result['choices'][0]['message']['content']


def execute_sql(conn, sql):
    """Execute SQL and return results"""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            results = cur.fetchall()
        conn.commit()  # Commit successful query
        return {'success': True, 'results': results, 'count': len(results)}
    except Exception as e:
        conn.rollback()  # Rollback on error so next query can run
        return {'success': False, 'error': str(e), 'results': [], 'count': 0}


async def agentic_search(conn, user_query, max_iterations=3):
    """
    Agentic search with multiple LLM calls per iteration:
    1. Decide action (semantic/fulltext/graph/done)
    2. Generate SQL (if searching)
    3. Evaluate results (after search)
    """
    
    print(f"\n{'='*100}")
    print(f"AGENTIC SEARCH: {user_query}")
    print(f"{'='*100}\n")
    
    search_history = []
    total_time = 0
    
    for iteration in range(1, max_iterations + 1):
        print(f"--- Iteration {iteration} ---\n")
        
        # STEP 1: Decide action type
        decision_prompt = f"""You are a search agent. Analyze this query and decide next action.

USER QUERY: "{user_query}"

PREVIOUS SEARCHES:
{json.dumps(search_history, indent=2) if search_history else "None"}

DATA SOURCES:
- SEMANTIC: LLM summaries (good for definitions, explanations)
- GRAPH: Entity relationships (good for "who did what", connections)
- FULLTEXT: Raw text (fallback)

Return JSON with just:
{{
  "action": "search_semantic" OR "search_graph" OR "search_fulltext" OR "done",
  "reasoning": "brief why"
}}

If previous results answered the query, return action="done".
If no previous results or they were poor, choose best data source.

JSON:"""

        # Call 1: Get action decision
        step1_start = time.time()
        action_response = await call_llm(decision_prompt, timeout=20)
        step1_time = time.time() - step1_start
        
        print(f"[STEP 1] Decision ({step1_time*1000:.0f}ms)")
        
        try:
            action_response = action_response.strip()
            action_response = re.sub(r'^```json\s*', '', action_response)
            action_response = re.sub(r'^```\s*', '', action_response)
            action_response = re.sub(r'\s*```$', '', action_response)
            decision = json.loads(action_response)
            
            print(f"  Action: {decision['action']}")
            print(f"  Reasoning: {decision['reasoning']}")
            
        except json.JSONDecodeError as e:
            print(f"  ERROR: Failed to parse: {e}")
            print(f"  Response: {action_response[:150]}")
            break
        
        # STEP 2: If done, generate final answer
        if decision['action'] == 'done':
            answer_prompt = f"""Based on search results, answer the user's query.

USER QUERY: "{user_query}"

SEARCH RESULTS:
{json.dumps(search_history, indent=2)}

Provide a clear, concise answer based on the data found.
Return plain text answer (not JSON)."""

            step2_start = time.time()
            answer = await call_llm(answer_prompt, timeout=20)
            step2_time = time.time() - step2_start
            total_time += step1_time + step2_time
            
            print(f"\n[STEP 2] Answer generation ({step2_time*1000:.0f}ms)")
            print(f"FINAL ANSWER: {answer}")
            print(f"\nTotal time: {total_time*1000:.0f}ms across {iteration} iterations")
            
            return {
                'answer': answer,
                'iterations': iteration,
                'total_time_ms': total_time * 1000,
                'search_history': search_history
            }
        
        # STEP 2: Generate SQL for chosen action
        if decision['action'] == 'search_graph':
            sql_prompt = f"""Generate SQL to search entity relationships.

QUERY: "{user_query}"

Tables:
- entities: id, entity_type, entity_name
- entity_relationships: subject_id, predicate, object_id

Generate SQL to find relationships. Use ILIKE for matching. LIMIT 10.

Example:
SELECT e1.entity_name as subject, er.predicate, e2.entity_name as object
FROM entity_relationships er
JOIN entities e1 ON er.subject_id = e1.id
JOIN entities e2 ON er.object_id = e2.id
WHERE e1.entity_name ILIKE '%GDAL%' OR e2.entity_name ILIKE '%GDAL%'
LIMIT 10;

Return ONLY the SQL query, nothing else."""

        elif decision['action'] == 'search_semantic':
            sql_prompt = f"""Generate SQL to search LLM summaries and keywords.

QUERY: "{user_query}"

Table: page_extensions
Columns: page_title, wiki_url, resume, keywords, resume_tsv, keywords_tsv

Generate SQL with websearch_to_tsquery. Use ts_rank for ranking. LIMIT 5.

Example:
SELECT page_title, resume
FROM page_extensions
WHERE resume_tsv @@ websearch_to_tsquery('english', 'QGIS')
ORDER BY ts_rank(resume_tsv, websearch_to_tsquery('english', 'QGIS')) DESC
LIMIT 5;

Return ONLY the SQL query, nothing else."""

        elif decision['action'] == 'search_fulltext':
            sql_prompt = f"""Generate SQL to search raw text chunks.

QUERY: "{user_query}"

Tables: page_chunks (chunk_text, tsv), pages (id, title, url)

Generate SQL with websearch_to_tsquery. Join on page_id. LIMIT 5.

Example:
SELECT p.title, pc.chunk_text
FROM page_chunks pc
JOIN pages p ON pc.page_id = p.id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'QGIS')
LIMIT 5;

Return ONLY the SQL query, nothing else."""

        else:
            print(f"  ERROR: Unknown action {decision['action']}")
            break
        
        # Call 2: Generate SQL
        step2_start = time.time()
        sql_response = await call_llm(sql_prompt, timeout=30)
        step2_time = time.time() - step2_start
        
        sql = sql_response.strip()
        sql = re.sub(r'^```sql\s*', '', sql)
        sql = re.sub(r'^```\s*', '', sql)
        sql = re.sub(r'\s*```$', '', sql)
        
        print(f"\n[STEP 2] SQL generation ({step2_time*1000:.0f}ms)")
        print(f"  SQL: {sql[:100]}...")
        
        # Execute search
        step3_start = time.time()
        result = execute_sql(conn, sql)
        step3_time = time.time() - step3_start
        total_time += step1_time + step2_time + step3_time
        
        print(f"\n[STEP 3] Query execution ({step3_time*1000:.0f}ms)")
        print(f"  Results: {result['count']} rows")
        
        if result['success'] and result['count'] > 0:
            preview = str(result['results'][0])[:100]
            print(f"  Sample: {preview}...")
        elif not result['success']:
            print(f"  SQL ERROR: {result['error']}")
        else:
            print(f"  No results found")
        
        # Add to history
        search_history.append({
            'iteration': iteration,
            'action': decision['action'],
            'reasoning': decision['reasoning'],
            'result_count': result['count'],
            'results': result['results'][:3] if result['success'] else [],
            'error': result.get('error') if not result['success'] else None
        })
        
        # STEP 4: Evaluate results - should we continue or are we done?
        if result['success'] and result['count'] > 0:
            eval_prompt = f"""Look at these search results. Can you answer the user's query?

USER QUERY: "{user_query}"

SEARCH RESULTS:
{json.dumps(result['results'][:5], indent=2, default=str)}

Return JSON:
{{
  "sufficient": true OR false,
  "reasoning": "why these results do or don't answer the query"
}}

If results contain the answer, return sufficient=true.
If results are irrelevant or incomplete, return sufficient=false."""

            step4_start = time.time()
            eval_response = await call_llm(eval_prompt, timeout=20)
            step4_time = time.time() - step4_start
            total_time += step4_time
            
            print(f"[STEP 4] Result evaluation ({step4_time*1000:.0f}ms)")
            
            try:
                eval_response = eval_response.strip()
                eval_response = re.sub(r'^```json\s*', '', eval_response)
                eval_response = re.sub(r'^```\s*', '', eval_response)  
                eval_response = re.sub(r'\s*```$', '', eval_response)
                evaluation = json.loads(eval_response)
                
                print(f"  Sufficient: {evaluation['sufficient']}")
                print(f"  Reasoning: {evaluation['reasoning']}")
                
                if evaluation['sufficient']:
                    # Generate final answer
                    answer_prompt = f"""Based on these results, answer the user's query concisely.

USER QUERY: "{user_query}"

RESULTS:
{json.dumps(result['results'][:5], indent=2, default=str)}

Provide a clear answer (plain text, not JSON)."""

                    step5_start = time.time()
                    answer = await call_llm(answer_prompt, timeout=20)
                    step5_time = time.time() - step5_start
                    total_time += step5_time
                    
                    print(f"\n[STEP 5] Answer generation ({step5_time*1000:.0f}ms)")
                    print(f"FINAL ANSWER: {answer}")
                    print(f"\nTotal time: {total_time*1000:.0f}ms across {iteration} iterations")
                    
                    return {
                        'answer': answer,
                        'iterations': iteration,
                        'total_time_ms': total_time * 1000,
                        'search_history': search_history
                    }
                    
            except json.JSONDecodeError as e:
                print(f"  ERROR: Failed to parse evaluation: {e}")
        
        print()
    
    # Max iterations reached
    print(f"\nMax iterations ({max_iterations}) reached")
    print(f"Total time: {total_time*1000:.0f}ms")
    
    return {
        'answer': 'Unable to complete search within iteration limit',
        'iterations': max_iterations,
        'total_time_ms': total_time * 1000,
        'search_history': search_history
    }


async def main():
    print("="*100)
    print("AGENTIC SEARCH TEST")
    print("="*100)
    print("\nThe LLM agent can:")
    print("- Choose which data source to search (semantic/fulltext/graph)")
    print("- Generate custom SQL queries")
    print("- Evaluate results")
    print("- Retry with different approaches if unsatisfied")
    print("- Stop when it has a good answer")
    print("="*100)
    
    conn = psycopg2.connect(**DB_CONFIG)
    
    try:
        for query in TEST_QUERIES:
            result = await agentic_search(conn, query, max_iterations=3)
            
            # Summary
            print(f"\n{'='*100}")
            print("SUMMARY")
            print(f"{'='*100}")
            print(f"Query: {query}")
            print(f"Answer: {result['answer']}")
            print(f"Iterations: {result['iterations']}")
            print(f"Total time: {result['total_time_ms']:.0f}ms")
            print(f"Search path: {' → '.join([s['action'] for s in result['search_history']])}")
            print()
    
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())