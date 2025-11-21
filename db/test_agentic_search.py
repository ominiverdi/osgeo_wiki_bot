#!/usr/bin/env python3
"""
Agentic Search v7 - Bulletproof JSON extraction:
- Aggressive JSON extraction with repair logic
- Handles: extra braces, truncated strings, regex fallback
- Removes reliance on stop sequences (keep for safety)
- All v6 fixes retained
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
    'What is QGIS?',
    'How is GDAL connected to Frank Warmerdam?',
    'What projects did Frank Warmerdam create?',
    'What is OSGeo?',
    'Who is the president of OSGeo?',
    'When was OSGeo founded?',
    'When was the last FOSS4G conference?',
    'Where was FOSS4G 2022 held?',
    'How do I join OSGeo?',
    'What are the OSGeo local chapters?',
    'What projects are part of OSGeo?',
    'Can you explain what GDAL is used for?',
]


async def call_llm(prompt, timeout=60, max_tokens=800, stop=None):
    """Call LLM API with optional stop sequences"""
    payload = {
        "model": "granite-4.0-h-tiny-32k",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1
    }
    
    if stop:
        payload["stop"] = stop
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{LLM_SERVER}/v1/chat/completions",
            json=payload
        )
        result = response.json()
        return result['choices'][0]['message']['content']


def execute_sql(conn, sql):
    """Execute SQL and return results"""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            results = cur.fetchall()
        conn.commit()
        return {'success': True, 'results': results, 'count': len(results)}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'error': str(e), 'results': [], 'count': 0}


def extract_json(text):
    """Bulletproof JSON extraction with aggressive repair logic"""
    text = text.strip()
    
    # Remove markdown code blocks
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    
    # Find JSON boundaries (first { to last })
    start = text.find('{')
    end = text.rfind('}')
    
    if start == -1 or end == -1:
        raise ValueError(f"No valid JSON brackets found in: {text[:100]}")
    
    json_text = text[start:end+1]
    
    # Try parsing as-is
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        # Repair attempt 1: Check for unclosed string
        if json_text.count('"') % 2 != 0:
            # Odd number of quotes - string wasn't closed
            json_text = json_text.rstrip() + '"}'
            try:
                return json.loads(json_text)
            except:
                pass  # Try next repair
        
        # Repair attempt 2: Regex extraction as fallback
        try:
            action_match = re.search(r'"action":\s*"([^"]+)"', json_text)
            reasoning_match = re.search(r'"reasoning":\s*"([^"]*)', json_text)
            
            if action_match:
                reasoning = reasoning_match.group(1) if reasoning_match else "parsing error"
                return {
                    'action': action_match.group(1),
                    'reasoning': reasoning
                }
        except:
            pass
        
        # Repair attempt 3: Try to find can_answer for evaluation responses
        try:
            can_answer_match = re.search(r'"can_answer":\s*(true|false)', json_text)
            reasoning_match = re.search(r'"reasoning":\s*"([^"]*)', json_text)
            
            if can_answer_match:
                reasoning = reasoning_match.group(1) if reasoning_match else "parsing error"
                return {
                    'can_answer': can_answer_match.group(1) == 'true',
                    'reasoning': reasoning
                }
        except:
            pass
        
        # All repairs failed
        raise ValueError(f"Could not parse or repair JSON. Error: {e}\nText: {json_text[:200]}")


def format_results_for_llm(results, result_type):
    """Format results to show LLM actual data"""
    if not results:
        return "No results found"
    
    lines = []
    for i, r in enumerate(results[:5], 1):
        if result_type == 'semantic':
            title = r.get('page_title', 'Unknown')
            resume = r.get('resume', '')[:100]
            lines.append(f"{i}. {title}: {resume}")
        elif result_type == 'graph':
            subj = r.get('subject', '')
            pred = r.get('predicate', '')
            obj = r.get('object', '')
            lines.append(f"{i}. {subj} {pred} {obj}")
        elif result_type == 'fulltext':
            title = r.get('title', 'Unknown')
            text = r.get('chunk_text', '')[:100]
            lines.append(f"{i}. {title}: {text}")
    
    return "\n".join(lines)


async def agentic_search(conn, user_query, max_iterations=3):
    """Agentic search v7 with bulletproof JSON extraction"""
    
    print(f"\n{'='*100}")
    print(f"AGENTIC SEARCH V7: {user_query}")
    print(f"{'='*100}\n")
    
    search_history = []
    total_time = 0
    
    for iteration in range(1, max_iterations + 1):
        print(f"--- Iteration {iteration} ---\n")
        
        # Build list of blocked actions
        blocked = [s['action'] for s in search_history if s['action'] != 'done']
        
        # Build available actions
        all_actions = ['search_semantic', 'search_graph', 'search_fulltext', 'done']
        available = [a for a in all_actions if a not in blocked]
        
        # Build results summary for LLM
        results_text = "None yet"
        if search_history:
            last = search_history[-1]
            if last['formatted_results']:
                results_text = f"Search {iteration-1} - {last['action'].replace('search_', '')}:\n{last['formatted_results']}"
        
        # STEP 1: Decide action
        blocked_text = "\n".join([f"- {b} (already tried)" for b in blocked]) if blocked else "None"
        available_text = "\n".join([f"- {a}" for a in available])
        
        decision_prompt = f"""Query: {user_query}

ALREADY TRIED:
{blocked_text}

RESULTS SO FAR:
{results_text}

YOU CANNOT USE: {', '.join(blocked) if blocked else 'none'}

CHOOSE FROM:
{available_text}

Return JSON: {{"action": "...", "reasoning": "one sentence, max 20 words"}}"""

        step1_start = time.time()
        action_response = await call_llm(
            decision_prompt, 
            timeout=20, 
            max_tokens=250,
            stop=["<|im_start|>", "<|im_sep|>"]
        )
        step1_time = time.time() - step1_start
        
        print(f"[STEP 1] Decision ({step1_time*1000:.0f}ms)")
        
        try:
            decision = extract_json(action_response)
            print(f"  Action: {decision['action']}")
            print(f"  Reasoning: {decision['reasoning']}")
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"  ERROR: Failed to parse: {e}")
            print(f"  Response: {action_response[:200]}")
            break
        
        # STEP 2: If done, generate answer
        if decision['action'] == 'done':
            if not search_history:
                print("  ERROR: Chose 'done' but no searches performed")
                break
            
            answer_prompt = f"""Query: {user_query}

RESULTS:
{search_history[-1]['formatted_results']}

Provide a clear answer (plain text, not JSON)."""

            step2_start = time.time()
            answer = await call_llm(answer_prompt, timeout=20)
            step2_time = time.time() - step2_start
            total_time += step1_time + step2_time
            
            print(f"\n[STEP 2] Answer generation ({step2_time*1000:.0f}ms)")
            print(f"ANSWER: {answer[:200]}...")
            
            return {
                'answer': answer,
                'iterations': iteration,
                'total_time_ms': total_time * 1000,
                'search_history': search_history
            }
        
        # STEP 2: Generate SQL
        if decision['action'] == 'search_graph':
            sql_prompt = f"""Generate SQL for entity relationships.

Query: {user_query}

Tables: entities (id, entity_type, entity_name), entity_relationships (subject_id, predicate, object_id)

Template:
SELECT e1.entity_name as subject, er.predicate, e2.entity_name as object
FROM entity_relationships er
JOIN entities e1 ON er.subject_id = e1.id
JOIN entities e2 ON er.object_id = e2.id
WHERE <your conditions with ILIKE>
LIMIT 10;

Return ONLY the SQL, no explanation."""

        elif decision['action'] == 'search_semantic':
            sql_prompt = f"""Generate SQL for semantic search.

Query: {user_query}

Table: page_extensions (page_title, resume, keywords, resume_tsv, keywords_tsv)

Template:
SELECT page_title, resume, keywords
FROM page_extensions
WHERE resume_tsv @@ websearch_to_tsquery('english', '<terms>')
ORDER BY ts_rank(resume_tsv, websearch_to_tsquery('english', '<terms>')) DESC
LIMIT 5;

Return ONLY the SQL, no explanation."""

        elif decision['action'] == 'search_fulltext':
            sql_prompt = f"""Generate SQL for fulltext search.

Query: {user_query}

Tables: page_chunks (chunk_text, tsv), pages (id, title, url)

IMPORTANT: Use tsv column for ts_rank, not chunk_text

Template:
SELECT p.title, pc.chunk_text
FROM page_chunks pc
JOIN pages p ON pc.page_id = p.id
WHERE pc.tsv @@ websearch_to_tsquery('english', '<terms>')
ORDER BY ts_rank(pc.tsv, websearch_to_tsquery('english', '<terms>')) DESC
LIMIT 5;

Return ONLY the SQL, no explanation."""

        else:
            print(f"  ERROR: Unknown action '{decision['action']}'")
            break
        
        # Call LLM for SQL
        step2_start = time.time()
        sql_response = await call_llm(sql_prompt, timeout=30, max_tokens=300)
        step2_time = time.time() - step2_start
        
        sql = sql_response.strip()
        sql = re.sub(r'^```sql\s*', '', sql)
        sql = re.sub(r'^```\s*', '', sql)
        sql = re.sub(r'\s*```$', '', sql)
        
        print(f"\n[STEP 2] SQL generation ({step2_time*1000:.0f}ms)")
        print(f"  SQL: {sql.replace(chr(10), ' ')[:80]}...")
        
        # STEP 3: Execute
        step3_start = time.time()
        result = execute_sql(conn, sql)
        step3_time = time.time() - step3_start
        total_time += step1_time + step2_time + step3_time
        
        print(f"\n[STEP 3] Execution ({step3_time*1000:.0f}ms)")
        print(f"  Results: {result['count']} rows")
        
        if not result['success']:
            print(f"  SQL ERROR: {result['error']}")
            formatted_results = "SQL error"
        elif result['count'] == 0:
            print(f"  No results")
            formatted_results = "No results"
        else:
            # Format results for display
            search_type = decision['action'].replace('search_', '')
            formatted_results = format_results_for_llm(result['results'], search_type)
            print(f"  Sample: {formatted_results.split(chr(10))[0][:80]}...")
        
        # Save to history
        search_history.append({
            'iteration': iteration,
            'action': decision['action'],
            'reasoning': decision['reasoning'],
            'result_count': result['count'],
            'results': result['results'][:5] if result['success'] else [],
            'formatted_results': formatted_results,
            'error': result.get('error') if not result['success'] else None
        })
        
        # STEP 4: Evaluate if we can answer
        if result['success'] and result['count'] > 0:
            eval_prompt = f"""Query: {user_query}

FOUND:
{formatted_results}

Can you answer the query with this information?

Return EXACTLY ONE JSON object:
{{"can_answer": true or false, "reasoning": "one sentence"}}"""

            step4_start = time.time()
            eval_response = await call_llm(
                eval_prompt, 
                timeout=15, 
                max_tokens=150,
                stop=["<|im_start|>", "<|im_sep|>"]
            )
            step4_time = time.time() - step4_start
            total_time += step4_time
            
            print(f"\n[STEP 4] Evaluation ({step4_time*1000:.0f}ms)")
            
            try:
                evaluation = extract_json(eval_response)
                print(f"  Can answer: {evaluation['can_answer']}")
                print(f"  Reasoning: {evaluation['reasoning']}")
                
                if evaluation['can_answer']:
                    # Generate final answer
                    answer_prompt = f"""Query: {user_query}

RESULTS:
{formatted_results}

Provide clear answer (plain text, not JSON)."""

                    step5_start = time.time()
                    answer = await call_llm(answer_prompt, timeout=20)
                    step5_time = time.time() - step5_start
                    total_time += step5_time
                    
                    print(f"\n[STEP 5] Answer generation ({step5_time*1000:.0f}ms)")
                    print(f"ANSWER: {answer[:200]}...")
                    
                    return {
                        'answer': answer,
                        'iterations': iteration,
                        'total_time_ms': total_time * 1000,
                        'search_history': search_history
                    }
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"  ERROR: Failed to parse evaluation: {e}")
                print(f"  Response: {eval_response[:200]}")
        
        print()
    
    # Max iterations reached
    print(f"\nMax iterations ({max_iterations}) reached")
    print(f"Total time: {total_time*1000:.0f}ms")
    
    # Generate best-effort answer
    if search_history and search_history[-1]['result_count'] > 0:
        answer_prompt = f"""Query: {user_query}

RESULTS (limited search):
{search_history[-1]['formatted_results']}

Provide answer based on available data (plain text)."""

        answer = await call_llm(answer_prompt, timeout=20)
    else:
        answer = 'Unable to find relevant information'
    
    return {
        'answer': answer,
        'iterations': max_iterations,
        'total_time_ms': total_time * 1000,
        'search_history': search_history
    }


async def main():
    print("="*100)
    print("AGENTIC SEARCH TEST V7")
    print("="*100)
    print("\nBulletproof JSON extraction:")
    print("- Handles extra braces, truncated strings")
    print("- Regex fallback for malformed JSON")
    print("- All v6 fixes retained")
    print("="*100)
    
    conn = psycopg2.connect(**DB_CONFIG)
    
    try:
        for query in TEST_QUERIES:
            result = await agentic_search(conn, query, max_iterations=3)
            
            print(f"\n{'='*100}")
            print("SUMMARY")
            print(f"{'='*100}")
            print(f"Query: {query}")
            print(f"Answer: {result['answer'][:150]}...")
            print(f"Iterations: {result['iterations']}")
            print(f"Total time: {result['total_time_ms']:.0f}ms")
            print(f"Search path: {' → '.join([s['action'] for s in result['search_history']])}")
            print()
    
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())