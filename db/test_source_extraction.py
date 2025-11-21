#!/usr/bin/env python3
"""
Test source extraction logic before integrating into MCP server.
Simulates agentic search results and tests URL extraction.
"""

def extract_sources(search_history, max_sources=3):
    """Extract source URLs from the last successful search."""
    for search in reversed(search_history):
        if search['result_count'] > 0:
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
                
                if url and title:
                    sources.append({'title': title, 'url': url})
            
            # Deduplicate by URL
            seen_urls = set()
            unique_sources = []
            for source in sources:
                if source['url'] not in seen_urls:
                    seen_urls.add(source['url'])
                    unique_sources.append(source)
            
            return unique_sources[:max_sources]
    
    return []


def build_mcp_response(agentic_result):
    """Build MCP protocol response with sources."""
    sources = extract_sources(agentic_result['search_history'])
    
    return {
        "message": {
            "role": "assistant",
            "content": agentic_result['answer']
        },
        "sources": sources,
        "metadata": {
            "iterations": agentic_result['iterations'],
            "total_time_ms": agentic_result['total_time_ms'],
            "search_path": " → ".join([
                s['action'].replace('search_', '') 
                for s in agentic_result['search_history']
            ])
        }
    }


# TEST CASE 1: Graph search (Frank Warmerdam projects)
test_case_1 = {
    'answer': 'Frank Warmerdam contributed to several projects including GDAL/OGR, GeoTools, and GEOS.',
    'iterations': 1,
    'total_time_ms': 10500,
    'search_history': [
        {
            'iteration': 1,
            'action': 'search_graph',
            'result_count': 5,
            'results': [
                {
                    'subject': 'Frank Warmerdam',
                    'predicate': 'contributed_to',
                    'object': 'GDAL/OGR',
                    'source_page_id': 587,
                    'source_page_title': 'Annual General Meeting 2007',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/AGM_2007'
                },
                {
                    'subject': 'Frank Warmerdam',
                    'predicate': 'contributed_to',
                    'object': 'GeoTools',
                    'source_page_id': 349,
                    'source_page_title': 'IncCom Meeting4',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/IncCom_Meeting4'
                },
                {
                    'subject': 'Frank Warmerdam',
                    'predicate': 'is_member_of',
                    'object': 'GEOS',
                    'source_page_id': 187,
                    'source_page_title': 'GEOS Incubation Status',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/GEOS_Incubation_Status'
                }
            ]
        }
    ]
}

# TEST CASE 2: Fulltext → Semantic (What is QGIS?)
test_case_2 = {
    'answer': 'QGIS is an open-source desktop GIS application that supports viewing, editing, and analysis of geospatial data.',
    'iterations': 2,
    'total_time_ms': 12000,
    'search_history': [
        {
            'iteration': 1,
            'action': 'search_fulltext',
            'result_count': 5,
            'results': [
                {
                    'title': 'QGIS',
                    'url': 'https://wiki.osgeo.org/wiki/QGIS',
                    'chunk_text': 'QGIS is a user friendly Open Source Geographic Information System...'
                },
                {
                    'title': 'Desktop GIS',
                    'url': 'https://wiki.osgeo.org/wiki/Desktop_GIS',
                    'chunk_text': 'QGIS (previously known as Quantum GIS) is a cross-platform...'
                }
            ]
        },
        {
            'iteration': 2,
            'action': 'search_semantic',
            'result_count': 3,
            'results': [
                {
                    'page_title': 'QGIS',
                    'wiki_url': 'https://wiki.osgeo.org/wiki/QGIS',
                    'resume': '* QGIS is an open-source desktop GIS application...',
                    'keywords': 'QGIS, GIS, open source, desktop mapping'
                },
                {
                    'page_title': 'Introduction to Free/Libre and Open Source GIS v.1.0',
                    'wiki_url': 'https://wiki.osgeo.org/wiki/Introduction_to_Free/Libre_and_Open_Source_GIS_v.1.0',
                    'resume': '* QGIS is a project of OSGeo Foundation...',
                    'keywords': 'QGIS, OSGeo, FOSS, GIS'
                }
            ]
        }
    ]
}

# TEST CASE 3: No results (should return empty sources)
test_case_3 = {
    'answer': 'Unable to find relevant information',
    'iterations': 3,
    'total_time_ms': 15000,
    'search_history': [
        {
            'iteration': 1,
            'action': 'search_semantic',
            'result_count': 0,
            'results': []
        },
        {
            'iteration': 2,
            'action': 'search_fulltext',
            'result_count': 0,
            'results': []
        }
    ]
}

# TEST CASE 4: Duplicate URLs (should deduplicate)
test_case_4 = {
    'answer': 'QGIS is an OSGeo project.',
    'iterations': 1,
    'total_time_ms': 8000,
    'search_history': [
        {
            'iteration': 1,
            'action': 'search_graph',
            'result_count': 5,
            'results': [
                {
                    'subject': 'QGIS',
                    'predicate': 'is_project_of',
                    'object': 'OSGeo',
                    'source_page_id': 3,
                    'source_page_title': 'Introduction to Free/Libre and Open Source GIS v.1.0',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/Introduction_to_Free/Libre_and_Open_Source_GIS_v.1.0'
                },
                {
                    'subject': 'QGIS',
                    'predicate': 'is_project_of',
                    'object': 'OSGeo',
                    'source_page_id': 3,  # SAME PAGE
                    'source_page_title': 'Introduction to Free/Libre and Open Source GIS v.1.0',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/Introduction_to_Free/Libre_and_Open_Source_GIS_v.1.0'
                },
                {
                    'subject': 'QGIS',
                    'predicate': 'is_project_of',
                    'object': 'OSGeo',
                    'source_page_id': 61,
                    'source_page_title': 'Ireland/Symposium2017',
                    'source_page_url': 'https://wiki.osgeo.org/wiki/Ireland/Symposium2017'
                }
            ]
        }
    ]
}


def run_tests():
    """Run all test cases and display results."""
    test_cases = [
        ("Graph search (Frank Warmerdam)", test_case_1),
        ("Fulltext → Semantic (QGIS)", test_case_2),
        ("No results found", test_case_3),
        ("Duplicate URLs", test_case_4)
    ]
    
    print("="*80)
    print("SOURCE EXTRACTION LOGIC TESTS")
    print("="*80)
    
    for test_name, test_data in test_cases:
        print(f"\n{'='*80}")
        print(f"TEST: {test_name}")
        print(f"{'='*80}")
        
        # Build MCP response
        mcp_response = build_mcp_response(test_data)
        
        # Display results
        print(f"\nAnswer: {mcp_response['message']['content'][:80]}...")
        print(f"\nMetadata:")
        print(f"  Iterations: {mcp_response['metadata']['iterations']}")
        print(f"  Time: {mcp_response['metadata']['total_time_ms']}ms")
        print(f"  Path: {mcp_response['metadata']['search_path']}")
        
        print(f"\nSources ({len(mcp_response['sources'])} found):")
        if mcp_response['sources']:
            for i, source in enumerate(mcp_response['sources'], 1):
                print(f"  {i}. {source['title']}")
                print(f"     {source['url']}")
        else:
            print("  (none)")
    
    print(f"\n{'='*80}")
    print("All tests completed")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    run_tests()