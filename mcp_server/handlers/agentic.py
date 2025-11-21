# mcp_server/handlers/agentic.py
"""
Agentic search system for OSGeo Wiki Bot.
Intelligently tries multiple search strategies until finding good answers.
"""
import json
import re
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Dict[str, Any]:
    """
    Bulletproof JSON extraction with aggressive repair logic.
    
    Args:
        text: Raw LLM response that may contain JSON
        
    Returns:
        Parsed JSON dict
        
    Raises:
        ValueError: If JSON cannot be extracted or repaired
    """
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
            json_text = json_text.rstrip() + '"}'
            try:
                return json.loads(json_text)
            except:
                pass
        
        # Repair attempt 2: Regex extraction for action/reasoning
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
        
        # Repair attempt 3: Extract can_answer for evaluation responses
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


def format_results_for_llm(results: List[Dict[str, Any]], result_type: str) -> str:
    """
    Format search results to show LLM actual data.
    
    Args:
        results: List of search result dicts
        result_type: 'semantic', 'graph', or 'fulltext'
        
    Returns:
        Formatted string showing top results
    """
    if not results:
        return "No results found"
    
    lines = []
    for i, r in enumerate(results[:5], 1):
        if result_type == 'semantic':
            title = r.get('page_title', 'Unknown')
            resume = r.get('resume', '')
            lines.append(f"{i}. {title}: {resume}")
        elif result_type == 'graph':
            subj = r.get('subject', '')
            pred = r.get('predicate', '')
            obj = r.get('object', '')
            lines.append(f"{i}. {subj} {pred} {obj}")
        elif result_type == 'fulltext':
            title = r.get('title', 'Unknown')
            text = r.get('chunk_text', '')
            lines.append(f"{i}. {title}: {text}")
    
    return "\n".join(lines)


def extract_sources(search_history: List[Dict[str, Any]], max_sources: int = 3) -> List[Dict[str, str]]:
    """
    Extract source URLs from the last successful search.
    
    Args:
        search_history: List of search attempts with results
        max_sources: Maximum number of sources to return
        
    Returns:
        List of dicts with 'title' and 'url' keys
    """
    # Find last search that had results
    for search in reversed(search_history):
        if search['result_count'] > 0:
            # Skip sources for graph searches
            if search['action'] == 'search_graph':
                return []

            sources = []
            
            for result in search['results'][:max_sources]:
                title = None
                url = None
                
                # Graph results format
                if 'source_page_url' in result:
                    url = result['source_page_url']
                    title = result['source_page_title']
                
                # Semantic results format
                elif 'wiki_url' in result:
                    url = result['wiki_url']
                    title = result['page_title']
                
                # Fulltext results format
                elif 'url' in result:
                    url = result['url']
                    title = result['title']
                
                # Only add if we have both title and URL
                if url and title:
                    sources.append({
                        'title': title,
                        'url': url
                    })
            
            # Deduplicate by URL while preserving order
            seen_urls = set()
            unique_sources = []
            for source in sources:
                if source['url'] not in seen_urls:
                    seen_urls.add(source['url'])
                    unique_sources.append(source)
            
            return unique_sources[:max_sources]
    
    return []


async def agentic_search(
    llm_client,
    db_execute_fn,
    user_query: str,
    max_iterations: int = 3
) -> Dict[str, Any]:
    """
    Agentic search that tries multiple strategies until finding good answers.
    
    Args:
        llm_client: LLMClient instance for LLM calls
        db_execute_fn: Function to execute SQL queries (returns list of dicts)
        user_query: User's natural language query
        max_iterations: Maximum search iterations to try
        
    Returns:
        Dict with 'answer', 'iterations', 'total_time_ms', 'search_history'
    """
    logger.info(f"Starting agentic search for: {user_query}")
    
    # Get current date for temporal context
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    search_history = []
    total_time = 0
    
    for iteration in range(1, max_iterations + 1):
        logger.debug(f"Iteration {iteration}/{max_iterations}")
        
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
        
        decision_prompt = f"""TODAY'S DATE: {current_date}

Query: {user_query}

QUERY ANALYSIS:
- If query asks about relationships, connections, or "how X relates to Y" → prefer search_graph
- If query asks "what is" or definitions → prefer search_semantic or search_fulltext
- If previous search gave partial results → try different method

ALREADY TRIED:
{blocked_text}

RESULTS SO FAR:
{results_text}

YOU CANNOT USE: {', '.join(blocked) if blocked else 'none'}

CHOOSE FROM:
{available_text}

Return JSON: {{"action": "...", "reasoning": "one sentence, max 20 words"}}"""

        step1_start = time.time()
        action_response = await llm_client.generate(
            prompt=decision_prompt,
            temperature=0.1,
            max_tokens=250
        )
        step1_time = time.time() - step1_start
        
        logger.debug(f"Decision step took {step1_time*1000:.0f}ms")
        
        try:
            decision = extract_json(action_response)
            logger.info(f"Action: {decision['action']} - {decision['reasoning']}")
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse decision: {e}")
            logger.error(f"Response was: {action_response[:200]}")
            break
        
        # STEP 2: If done, generate answer
        if decision['action'] == 'done':
            if not search_history:
                logger.warning("Chose 'done' but no searches performed")
                break
            
            answer_prompt = f"""TODAY'S DATE: {current_date}

Query: {user_query}

RESULTS:
{search_history[-1]['formatted_results']}

Provide a clear answer (plain text, not JSON)."""

            step2_start = time.time()
            answer = await llm_client.generate(prompt=answer_prompt, temperature=0.7)
            step2_time = time.time() - step2_start
            total_time += step1_time + step2_time
            
            logger.info(f"Generated final answer in {step2_time*1000:.0f}ms")
            
            return {
                'answer': answer,
                'success': True,
                'iterations': iteration,
                'total_time_ms': total_time * 1000,
                'search_history': search_history
            }
        
        # STEP 2: Generate SQL based on action
        sql_prompt = _create_sql_prompt(decision['action'], user_query)
        if not sql_prompt:
            logger.error(f"Unknown action: {decision['action']}")
            break
        
        step2_start = time.time()
        sql_response = await llm_client.generate(
            prompt=sql_prompt,
            temperature=0.1,
            max_tokens=300
        )
        step2_time = time.time() - step2_start
        
        # Clean up SQL
        sql = sql_response.strip()
        sql = re.sub(r'^```sql\s*', '', sql)
        sql = re.sub(r'^```\s*', '', sql)
        sql = re.sub(r'\s*```$', '', sql)
        
        logger.debug(f"Generated SQL in {step2_time*1000:.0f}ms")
        logger.debug(f"SQL: {sql[:100]}...")
        
        # STEP 3: Execute SQL
        step3_start = time.time()
        results = await db_execute_fn(sql)
        step3_time = time.time() - step3_start
        total_time += step1_time + step2_time + step3_time

        # Deduplicate fulltext results by URL (keeps highest-ranked chunk per page)
        if decision['action'] == 'search_fulltext' and results:
            seen_urls = set()
            deduplicated = []
            for r in results:
                url = r.get('url')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduplicated.append(r)
            results = deduplicated
            logger.debug(f"Deduplicated {len(results)} unique pages")
        
        logger.info(f"Query returned {len(results)} results in {step3_time*1000:.0f}ms")
        
        if not results:
            formatted_results = "No results"
        else:
            search_type = decision['action'].replace('search_', '')
            formatted_results = format_results_for_llm(results, search_type)
        
        # Save to history
        search_history.append({
            'iteration': iteration,
            'action': decision['action'],
            'reasoning': decision['reasoning'],
            'result_count': len(results),
            'results': results[:5],  # Keep top 5
            'formatted_results': formatted_results
        })
        
        # STEP 4: Evaluate if we can answer
        if results:
            eval_prompt = f"""TODAY'S DATE: {current_date}

Query: {user_query}

FOUND:
{formatted_results}

Can you answer the query with this information?

Return EXACTLY ONE JSON object:
{{"can_answer": true or false, "reasoning": "one sentence"}}"""

            step4_start = time.time()
            eval_response = await llm_client.generate(
                prompt=eval_prompt,
                temperature=0.1,
                max_tokens=150
            )
            step4_time = time.time() - step4_start
            total_time += step4_time
            
            logger.debug(f"Evaluation took {step4_time*1000:.0f}ms")
            
            try:
                evaluation = extract_json(eval_response)
                logger.info(f"Can answer: {evaluation['can_answer']} - {evaluation['reasoning']}")
                
                if evaluation['can_answer']:
                    # Generate final answer
                    answer_prompt = f"""TODAY'S DATE: {current_date}

Query: {user_query}

RESULTS:
{formatted_results}

CRITICAL INSTRUCTIONS:
1. Answer ONLY using the search results above - DO NOT use any other knowledge
2. If results are graph relationships (like "X is_project_of Y"):
   - Convert to natural language: "X is a project of Y"
   - State each unique relationship once only
   - Synthesize into a clear sentence
3. If search results are insufficient, say "The wiki has limited information on this"
4. Keep answer concise: 2-3 sentences for simple queries, max 5 sentences for complex ones
5. Do NOT repeat the same information multiple times

Provide clear answer (plain text, not JSON)."""

                    logger.debug(f"ANSWER PROMPT - formatted_results length: {len(formatted_results)}")
                    logger.debug(f"ANSWER PROMPT - formatted_results preview: {formatted_results[:500]}")

                    step5_start = time.time()
                    answer = await llm_client.generate(prompt=answer_prompt, temperature=0.7)
                    step5_time = time.time() - step5_start
                    total_time += step5_time
                    
                    logger.info(f"Generated final answer in {step5_time*1000:.0f}ms")
                    
                    return {
                        'answer': answer,
                        'success': True, 
                        'iterations': iteration,
                        'total_time_ms': total_time * 1000,
                        'search_history': search_history
                    }
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Failed to parse evaluation: {e}")
                logger.error(f"Response was: {eval_response[:200]}")
    
    # Max iterations reached
    logger.warning(f"Max iterations ({max_iterations}) reached")
    
    # Generate best-effort answer
    if search_history and search_history[-1]['result_count'] > 0:
        answer_prompt = f"""TODAY'S DATE: {current_date}

Query: {user_query}

RESULTS (limited search):
{search_history[-1]['formatted_results']}

Provide answer based on available data (plain text)."""

        answer = await llm_client.generate(prompt=answer_prompt, temperature=0.7)
    else:
        answer = 'Unable to find relevant information in the OSGeo wiki.'
    
    return {
        'answer': answer,
        'success': False,
        'iterations': max_iterations,
        'total_time_ms': total_time * 1000,
        'search_history': search_history
    }


def _create_sql_prompt(action: str, user_query: str) -> Optional[str]:
    """
    Create SQL generation prompt based on search action.
    
    Args:
        action: Search action (search_graph, search_semantic, search_fulltext)
        user_query: User's query
        
    Returns:
        SQL generation prompt or None if action unknown
    """
    if action == 'search_graph':
        return f"""Generate SQL for entity relationships.

Query: {user_query}

Tables: 
- entities (id, entity_type, entity_name)
- entity_relationships (subject_id, predicate, object_id, source_page_id)
- pages (id, title, url)

IMPORTANT: Always include source page information.

Template:
SELECT 
    e1.entity_name as subject, 
    er.predicate, 
    e2.entity_name as object,
    er.source_page_id,
    p.title as source_page_title,
    p.url as source_page_url
FROM entity_relationships er
JOIN entities e1 ON er.subject_id = e1.id
JOIN entities e2 ON er.object_id = e2.id
LEFT JOIN pages p ON er.source_page_id = p.id
WHERE <your conditions with ILIKE>
LIMIT 10;

Return ONLY the SQL, no explanation."""

    elif action == 'search_semantic':
        return f"""Generate SQL for semantic search using page summaries.

Query: {user_query}

Table: page_extensions (page_title, wiki_url, resume, keywords, resume_tsv, keywords_tsv)

CRITICAL INSTRUCTIONS:
1. Exact title match gets 10.0 point boost
2. Partial title match gets 2.5 point boost
3. Use LOWER() for exact comparison
4. Search both resume_tsv and keywords_tsv

Template:
SELECT 
    page_title, 
    wiki_url,
    resume, 
    keywords,
    (CASE 
       WHEN LOWER(page_title) = LOWER('<main_term>') THEN 10.0
       WHEN page_title ILIKE '%<main_term>%' THEN 2.5
       ELSE 0 
     END +
     0.6 * ts_rank(resume_tsv, websearch_to_tsquery('english', '<terms>')) + 
     0.4 * ts_rank(keywords_tsv, websearch_to_tsquery('english', '<terms>'))) as rank
FROM page_extensions
WHERE resume_tsv @@ websearch_to_tsquery('english', '<terms>')
   OR keywords_tsv @@ websearch_to_tsquery('english', '<terms>')
   OR page_title ILIKE '%<main_term>%'
ORDER BY rank DESC
LIMIT 5;

Replace <main_term> with the primary search term (e.g., 'GDAL', 'PostGIS', 'QGIS').
Replace <terms> with full search terms.

Return ONLY the SQL, no explanation."""

    elif action == 'search_fulltext':
        return f"""Generate SQL for fulltext search using page chunks.

Query: {user_query}

Tables: 
- page_chunks (page_id, chunk_text, tsv)
- pages (id, title, url)

CRITICAL INSTRUCTIONS:
1. Exact title match gets 10.0 point boost
2. Partial title match gets 2.5 point boost
3. Use LOWER() for exact comparison
4. Use tsv column for ts_rank (NOT chunk_text)

Template:
SELECT 
    p.title, 
    p.url,
    pc.chunk_text,
    (CASE 
       WHEN LOWER(p.title) = LOWER('<main_term>') THEN 10.0
       WHEN p.title ILIKE '%<main_term>%' THEN 2.5
       ELSE 0 
     END +
     ts_rank(pc.tsv, websearch_to_tsquery('english', '<terms>'))) as rank
FROM page_chunks pc
JOIN pages p ON pc.page_id = p.id
WHERE pc.tsv @@ websearch_to_tsquery('english', '<terms>')
   OR p.title ILIKE '%<main_term>%'
ORDER BY rank DESC
LIMIT 5;

Replace <main_term> with the primary search term.
Replace <terms> with full search terms.

Return ONLY the SQL, no explanation."""

    else:
        return None