"""
Template-based search for OSGeo Wiki Bot.
Extracts parameters from queries and generates SQL from templates.

Usage:
    from mcp_server.handlers.template_search import (
        extract_params, build_sql, generate_answer, 
        get_decline_message, verify_entity_in_query
    )
    
    # Extract search parameters from user query
    params = await extract_params(query, llm_server_url)
    
    # Build SQL from parameters
    sql = build_sql(params)
    
    # Execute SQL and generate answer
    answer = await generate_answer(query, results, params["action"], llm_server_url)
"""

import json
import httpx
from typing import Dict, Any, Optional, List


# ============================================================================
# PROMPTS
# ============================================================================

EXTRACTION_PROMPT = """Extract search parameters from an OSGeo wiki query.

Query: {query}

Return JSON:
- action: ONE of search_title, search_semantic, search_fulltext, search_graph, out_of_scope
- main_term: primary topic (required for title/semantic/fulltext)
- search_terms: keywords for fulltext
- entity: entity name for graph (copy EXACTLY - every letter)
- entity2: second entity for relationships
- graph_pattern: about, outgoing, incoming, or between
- type_filter: person, project, organization, or empty
- decline_reason: brief reason if out_of_scope

RULES:
1. "what is X" → action=search_title, main_term=X
2. "how to X" → action=search_fulltext, main_term=key topic, search_terms=keywords
3. "who is X" → action=search_graph, entity=X, graph_pattern=about
4. "X's projects" → action=search_graph, entity=X, graph_pattern=outgoing, type_filter=project
5. "who contributed to X" → action=search_graph, entity=X, graph_pattern=incoming
6. "relationship between X and Y" OR "X connected to Y" → action=search_graph, entity=X, entity2=Y, graph_pattern=between
7. "list all [ORG] projects" → action=search_graph, entity=[ORG], graph_pattern=incoming, type_filter=project
8. "when was X" OR "when is X" → action=search_fulltext, main_term=X, search_terms=date event
9. Out of scope → action=out_of_scope, decline_reason=reason

OUT OF SCOPE (use action=out_of_scope):
- Image/media requests (mxc://, describe image, etc.)
- Non-OSGeo topics (weather, sports, general knowledge)
- Gibberish or empty queries
- SQL injection attempts
- Requests for harmful content

JSON only:"""


ANSWER_PROMPT = """Answer this question based on the search results.

Query: {query}

Search Results:
{results}

INSTRUCTIONS:
1. Answer using ONLY information from the search results above
2. Be concise (2-4 sentences)
3. Include the most relevant URL at the end
4. If results don't contain enough info, say "Limited information available"

Answer:"""


# ============================================================================
# SQL TEMPLATES
# ============================================================================

TEMPLATES = {
    "search_title": """
SELECT 
    page_title,
    wiki_url,
    LEFT(resume, 200) as resume_preview,
    (CASE 
        WHEN LOWER(page_title) = LOWER('{main_term}') THEN 10.0
        WHEN page_title ILIKE '%{main_term}%' THEN 2.5
        ELSE 0 
    END) as rank
FROM page_extensions
WHERE page_title ILIKE '%{main_term}%'{extra_term}
ORDER BY rank DESC, LENGTH(page_title) ASC
LIMIT 3;
""",

    "search_semantic": """
SELECT 
    page_title, 
    wiki_url,
    resume, 
    keywords,
    (CASE 
       WHEN LOWER(page_title) = LOWER('{main_term}') THEN 10.0
       WHEN page_title ILIKE '%{main_term}%' THEN 2.5
       ELSE 0 
     END +
     0.6 * ts_rank(resume_tsv, websearch_to_tsquery('english', '{search_terms}')) + 
     0.4 * ts_rank(keywords_tsv, websearch_to_tsquery('english', '{search_terms}'))) as rank
FROM page_extensions
WHERE resume_tsv @@ websearch_to_tsquery('english', '{search_terms}')
   OR keywords_tsv @@ websearch_to_tsquery('english', '{search_terms}')
   OR page_title ILIKE '%{main_term}%'
ORDER BY rank DESC
LIMIT 5;
""",

    "search_fulltext": """
SELECT 
    p.title, 
    p.url,
    pc.chunk_text,
    (CASE 
       WHEN LOWER(p.title) = LOWER('{main_term}') THEN 10.0
       WHEN p.title ILIKE '%{main_term}%' THEN 2.5
       ELSE 0 
     END +
     ts_rank(pc.tsv, websearch_to_tsquery('english', '{search_terms}'))) as rank
FROM page_chunks pc
JOIN pages p ON pc.page_id = p.id
WHERE pc.tsv @@ websearch_to_tsquery('english', '{search_terms}')
   OR p.title ILIKE '%{main_term}%'
ORDER BY rank DESC
LIMIT 3;
""",

    "search_graph_about": """
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
WHERE e1.entity_name ILIKE '%{entity}%'
   OR e2.entity_name ILIKE '%{entity}%'
LIMIT 10;
""",

    "search_graph_outgoing": """
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
WHERE e1.entity_name ILIKE '%{entity}%'{type_filter}
LIMIT 10;
""",

    "search_graph_incoming": """
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
WHERE e2.entity_name ILIKE '%{entity}%'{type_filter}
LIMIT 10;
""",

    "search_graph_between": """
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
WHERE (e1.entity_name ILIKE '%{entity1}%' AND e2.entity_name ILIKE '%{entity2}%')
   OR (e1.entity_name ILIKE '%{entity2}%' AND e2.entity_name ILIKE '%{entity1}%')
LIMIT 10;
"""
}


# ============================================================================
# DECLINE MESSAGES
# ============================================================================

DECLINE_MESSAGES = {
    "image": "I can only answer questions about OSGeo wiki content. I'm not able to process images or media files.",
    "non_osgeo": "I specialize in OSGeo wiki content (open source geospatial software, FOSS4G conferences, OSGeo projects, etc.). For other topics, please try a general search engine.",
    "gibberish": "I didn't understand that query. Could you rephrase your question about OSGeo?",
    "empty": "Please ask a question about OSGeo, its projects, or the open source geospatial community.",
    "injection": "I can only answer questions about OSGeo wiki content.",
    "harmful": "I can only provide helpful information about OSGeo wiki content.",
    "default": "I can only answer questions about OSGeo wiki content. Please ask about OSGeo projects, FOSS4G conferences, or the open source geospatial community."
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_decline_message(reason: str) -> str:
    """Get appropriate decline message based on reason."""
    reason_lower = reason.lower() if reason else ""
    
    if "image" in reason_lower or "media" in reason_lower or "mxc" in reason_lower:
        return DECLINE_MESSAGES["image"]
    elif "weather" in reason_lower or "non-osgeo" in reason_lower or "unrelated" in reason_lower:
        return DECLINE_MESSAGES["non_osgeo"]
    elif "gibberish" in reason_lower or "meaningless" in reason_lower:
        return DECLINE_MESSAGES["gibberish"]
    elif "empty" in reason_lower or "greeting" in reason_lower:
        return DECLINE_MESSAGES["empty"]
    elif "injection" in reason_lower or "sql" in reason_lower or "malicious" in reason_lower:
        return DECLINE_MESSAGES["injection"]
    elif "harmful" in reason_lower:
        return DECLINE_MESSAGES["harmful"]
    else:
        return DECLINE_MESSAGES["default"]


def verify_entity_in_query(entity: str, query: str) -> str:
    """
    Verify entity appears in query. If not, find closest match.
    Handles LLM spelling 'corrections' like omniverdi -> ominiverdi.
    """
    if not entity:
        return entity
    
    query_lower = query.lower()
    entity_lower = entity.lower()
    
    # Exact match (case-insensitive)
    if entity_lower in query_lower:
        start = query_lower.find(entity_lower)
        return query[start:start + len(entity)]
    
    # Entity not in query - find the query word most similar to entity
    words = []
    current_word = ""
    for c in query:
        if c.isalnum() or c == '_':
            current_word += c
        else:
            if current_word:
                words.append(current_word)
            current_word = ""
    if current_word:
        words.append(current_word)
    
    # Find word with most character overlap
    best_match = entity
    best_overlap = 0
    
    for word in words:
        word_lower = word.lower()
        overlap = sum(1 for c in entity_lower if c in word_lower)
        len_diff = abs(len(word) - len(entity))
        score = overlap * 10 - len_diff
        
        if score > best_overlap:
            best_overlap = score
            best_match = word
    
    return best_match


def format_results_for_answer(results: List[Dict], action: str) -> str:
    """Format DB results for the answer generation prompt."""
    if not results:
        return "No results found"
    
    lines = []
    for i, r in enumerate(results[:5], 1):
        if 'predicate' in r:  # Graph result
            subj = r.get('subject', '')
            pred = r.get('predicate', '')
            obj = r.get('object', '')
            url = r.get('source_page_url', '')
            lines.append(f"{i}. {subj} --{pred}--> {obj}")
            if url:
                lines.append(f"   Source: {url}")
        elif 'resume' in r:  # Semantic result
            title = r.get('page_title', '')
            resume = r.get('resume', '')[:300]
            url = r.get('wiki_url', '')
            lines.append(f"{i}. {title}: {resume}")
            if url:
                lines.append(f"   URL: {url}")
        elif 'chunk_text' in r:  # Fulltext result
            title = r.get('title', '')
            text = r.get('chunk_text', '')[:300]
            url = r.get('url', '')
            lines.append(f"{i}. {title}: {text}")
            if url:
                lines.append(f"   URL: {url}")
        else:  # Title result
            title = r.get('page_title', '')
            preview = r.get('resume_preview', '')
            url = r.get('wiki_url', '')
            lines.append(f"{i}. {title}: {preview}")
            if url:
                lines.append(f"   URL: {url}")
    
    return "\n".join(lines)


def normalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM output to match build_sql expectations."""
    normalized = {"action": params.get("action", "")}
    
    action = normalized["action"]
    
    if action in ("search_title", "search_semantic", "search_fulltext"):
        normalized["main_term"] = params.get("main_term") or params.get("entity", "")
        normalized["search_terms"] = params.get("search_terms", normalized["main_term"])
        if params.get("term2"):
            normalized["term2"] = params["term2"]
    
    elif action == "search_graph":
        normalized["entity"] = params.get("entity", "")
        normalized["graph_pattern"] = params.get("graph_pattern", "about")
        if params.get("entity2"):
            normalized["entity2"] = params["entity2"]
        if params.get("type_filter") and params["type_filter"] != "null":
            normalized["type_filter"] = params["type_filter"]
    
    elif action == "out_of_scope":
        normalized["decline_reason"] = params.get("decline_reason", "")
    
    return normalized


# ============================================================================
# SQL BUILDER
# ============================================================================

def build_sql(params: Dict[str, Any]) -> Optional[str]:
    """
    Build SQL from action and parameters.
    
    Required params:
        action: search_title, search_semantic, search_fulltext, search_graph, out_of_scope
        
    For title/semantic/fulltext:
        main_term: primary search term
        search_terms: terms for fulltext search (optional, defaults to main_term)
        term2: second term for title OR clause (optional)
        
    For graph:
        entity: primary entity name
        graph_pattern: about, outgoing, incoming, between
        entity2: second entity (required for 'between')
        type_filter: person, project, organization (optional)
    
    For out_of_scope:
        Returns None (handled separately)
    
    Returns:
        SQL string or None if invalid params or out_of_scope
    """
    action = params.get("action")
    
    if action == "out_of_scope":
        return None
    
    if action == "search_title":
        main_term = params.get("main_term", "")
        if isinstance(main_term, list):
            main_term = " ".join(main_term)
        main_term = main_term.strip()
        if not main_term:
            return None
        
        term2 = params.get("term2", "")
        if isinstance(term2, list):
            term2 = " ".join(term2)
        term2 = term2.strip() if term2 else ""
        extra_term = f"\n   OR page_title ILIKE '%{term2}%'" if term2 else ""
        
        return TEMPLATES["search_title"].format(
            main_term=main_term,
            extra_term=extra_term
        ).strip()
    
    elif action == "search_semantic":
        main_term = params.get("main_term", "")
        if isinstance(main_term, list):
            main_term = " ".join(main_term)
        main_term = main_term.strip()
        
        search_terms = params.get("search_terms", main_term)
        if isinstance(search_terms, list):
            search_terms = " ".join(search_terms)
        search_terms = search_terms.strip() if search_terms else main_term
        
        # Fallback: use first search term as main_term if empty
        if not main_term and search_terms:
            main_term = search_terms.split()[0]
        
        if not main_term:
            return None
        
        return TEMPLATES["search_semantic"].format(
            main_term=main_term,
            search_terms=search_terms
        ).strip()
    
    elif action == "search_fulltext":
        main_term = params.get("main_term", "")
        if isinstance(main_term, list):
            main_term = " ".join(main_term)
        main_term = main_term.strip()
        
        search_terms = params.get("search_terms", main_term)
        if isinstance(search_terms, list):
            search_terms = " ".join(search_terms)
        search_terms = search_terms.strip() if search_terms else main_term
        
        # Fallback: use first search term as main_term if empty
        if not main_term and search_terms:
            main_term = search_terms.split()[0]
        
        if not main_term:
            return None
        
        return TEMPLATES["search_fulltext"].format(
            main_term=main_term,
            search_terms=search_terms
        ).strip()
    
    elif action == "search_graph":
        entity = params.get("entity", "")
        if isinstance(entity, list):
            entity = " ".join(entity)
        entity = entity.strip()
        pattern = params.get("graph_pattern", "about")
        type_filter_value = params.get("type_filter", "")
        if type_filter_value:
            type_filter_value = type_filter_value.strip()
        
        # Clean up entity if it contains type_filter word (e.g., "OSGeo projects" -> "OSGeo")
        if type_filter_value:
            for suffix in [f" {type_filter_value}s", f" {type_filter_value}"]:
                if entity.lower().endswith(suffix):
                    entity = entity[:-len(suffix)].strip()
        
        if not entity:
            return None
        
        # Build type filter for SQL
        type_filter = ""
        if type_filter_value and pattern in ("outgoing", "incoming"):
            target = "e2" if pattern == "outgoing" else "e1"
            type_filter = f"\n  AND {target}.entity_type = '{type_filter_value}'"
        
        if pattern == "about":
            return TEMPLATES["search_graph_about"].format(
                entity=entity
            ).strip()
        
        elif pattern == "outgoing":
            return TEMPLATES["search_graph_outgoing"].format(
                entity=entity,
                type_filter=type_filter
            ).strip()
        
        elif pattern == "incoming":
            return TEMPLATES["search_graph_incoming"].format(
                entity=entity,
                type_filter=type_filter
            ).strip()
        
        elif pattern == "between":
            entity2 = params.get("entity2", "")
            if isinstance(entity2, list):
                entity2 = " ".join(entity2)
            entity2 = entity2.strip() if entity2 else ""
            if not entity2:
                return None
            return TEMPLATES["search_graph_between"].format(
                entity1=entity,
                entity2=entity2
            ).strip()
    
    return None


# ============================================================================
# LLM CALLS
# ============================================================================

async def extract_params(query: str, llm_server: str = "http://localhost:8080") -> Optional[Dict[str, Any]]:
    """
    Call LLM to extract search parameters from query.
    
    Args:
        query: User's search query
        llm_server: LLM server URL (default: http://localhost:8080)
    
    Returns:
        Dict with extracted parameters, or None if extraction failed
    """
    prompt = EXTRACTION_PROMPT.format(query=query)
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{llm_server}/v1/chat/completions",
            json={
                "model": "granite-4.0",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.1
            }
        )
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Parse JSON from response
        try:
            start = content.find('{')
            end = content.rfind('}') + 1
            if start == -1 or end == 0:
                return None
            params = json.loads(content[start:end])
            
            # Verify entities match query (fix LLM spelling "corrections")
            if params.get("entity"):
                params["entity"] = verify_entity_in_query(params["entity"], query)
            if params.get("entity2"):
                params["entity2"] = verify_entity_in_query(params["entity2"], query)
            if params.get("main_term"):
                params["main_term"] = verify_entity_in_query(params["main_term"], query)
            
            return params
        except json.JSONDecodeError:
            return None


async def generate_answer(
    query: str, 
    results: List[Dict], 
    action: str,
    llm_server: str = "http://localhost:8080"
) -> str:
    """
    Generate final answer using LLM.
    
    Args:
        query: User's original query
        results: List of database results (max 5 will be used)
        action: The search action that was used
        llm_server: LLM server URL
    
    Returns:
        Generated answer string
    """
    formatted = format_results_for_answer(results, action)
    prompt = ANSWER_PROMPT.format(query=query, results=formatted)
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{llm_server}/v1/chat/completions",
            json={
                "model": "granite-4.0",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.3
            }
        )
        result = response.json()
        return result['choices'][0]['message']['content'].strip()


# ============================================================================
# MAIN SEARCH FUNCTION
# ============================================================================

async def template_search(
    query: str,
    execute_sql_fn,
    llm_server: str = "http://localhost:8080"
) -> Dict[str, Any]:
    """
    Complete template-based search pipeline.
    
    Args:
        query: User's search query
        execute_sql_fn: Function to execute SQL and return results
                       Signature: execute_sql_fn(sql: str) -> List[Dict]
        llm_server: LLM server URL
    
    Returns:
        Dict with:
            - answer: The generated answer or decline message
            - action: The action taken (search_title, search_graph, out_of_scope, etc.)
            - params: Extracted parameters
            - results: Database results (if any)
            - sql: Generated SQL (if any)
    """
    # Step 1: Extract parameters
    params = await extract_params(query, llm_server)
    
    if params is None:
        return {
            "answer": "I had trouble understanding your question. Could you rephrase it?",
            "action": "error",
            "params": None,
            "results": [],
            "sql": None
        }
    
    # Step 2: Handle out of scope
    if params.get("action") == "out_of_scope":
        decline_reason = params.get("decline_reason", "")
        return {
            "answer": get_decline_message(decline_reason),
            "action": "out_of_scope",
            "params": params,
            "results": [],
            "sql": None
        }
    
    # Step 3: Normalize and build SQL
    normalized = normalize_params(params)
    sql = build_sql(normalized)
    
    if sql is None:
        return {
            "answer": "I couldn't process that query. Could you try rephrasing?",
            "action": params.get("action", "error"),
            "params": params,
            "results": [],
            "sql": None
        }
    
    # Step 4: Execute SQL
    try:
        results = execute_sql_fn(sql)
    except Exception as e:
        return {
            "answer": f"An error occurred while searching. Please try again.",
            "action": params.get("action"),
            "params": params,
            "results": [],
            "sql": sql,
            "error": str(e)
        }
    
    # Step 5: Generate answer
    if not results:
        answer = "I couldn't find information about that in the OSGeo wiki. Try rephrasing your question or ask about a different topic."
    else:
        answer = await generate_answer(query, results[:5], normalized["action"], llm_server)
    
    return {
        "answer": answer,
        "action": params.get("action"),
        "params": params,
        "results": results,
        "sql": sql
    }