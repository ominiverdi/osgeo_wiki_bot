# tests/test_user_entities_dry_run.py
import psycopg2
import os
from collections import defaultdict
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Whitelist of fields to extract
ENTITY_FIELDS = {
    'name': ('person', 'is_alias_of'),
    'address': ('location', 'lives_at'),
    'city': ('location', 'lives_in_city'),
    'state': ('location', 'lives_in_state'),
    'country': ('location', 'lives_in_country'),
    'company': ('organization', 'works_for'),
    'local_chapter': ('organization', 'member_of'),
}

def connect_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "osgeo_wiki"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        port=os.getenv("DB_PORT", "5432")
    )

def is_placeholder(value):
    """Check if a value is a placeholder/empty."""
    if not value:
        return True
    if value.startswith('[[') or value.startswith('{{{'):
        return True
    if value in ['Loading map...', 'OSGeo Member']:
        return True
    return False

def parse_user_page(title, chunk_text):
    """Extract fields from user page template."""
    fields = {'username': title.replace('User:', '')}
    
    lines = chunk_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        if line.endswith(':'):
            field_name = line[:-1].lower().replace(' ', '_').replace('(', '').replace(')', '')
            
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                
                if next_line and \
                   not next_line.endswith(':') and \
                   not is_placeholder(next_line):
                    fields[field_name] = next_line
        
        i += 1
    
    return fields

def get_user_pages():
    """Get all user pages from database."""
    conn = connect_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT p.id, p.title, pc.chunk_text, p.url
        FROM pages p
        JOIN page_chunks pc ON p.id = pc.page_id
        WHERE p.title LIKE 'User:%'
        AND pc.chunk_index = 0
        ORDER BY p.title
    """)
    
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    return results

def dry_run():
    """Simulate what would be inserted."""
    
    print("DRY RUN - User Entity Extraction")
    print("=" * 70)
    
    pages = get_user_pages()
    
    # Track what would be created
    entities_to_create = []
    relationships_to_create = []
    
    stats = defaultdict(int)
    
    for page_id, title, chunk_text, url in pages:
        fields = parse_user_page(title, chunk_text)
        username = fields.get('username')
        
        # Track processing
        stats['pages_processed'] += 1
        
        # Process username entity
        entities_to_create.append({
            'name': username,
            'type': 'person',
            'source_page': title,
            'source_url': url
        })
        stats['entities_username'] += 1
        
        # Process whitelisted fields
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                value = fields[field_name]
                
                # Create entity
                entities_to_create.append({
                    'name': value,
                    'type': entity_type,
                    'source_page': title,
                    'source_url': url
                })
                stats[f'entities_{entity_type}'] += 1
                
                # Create relationship
                relationships_to_create.append({
                    'subject': username,
                    'predicate': predicate,
                    'object': value,
                    'source_page': title
                })
                stats[f'relationships_{predicate}'] += 1
    
    # Print summary
    print(f"\nPages processed: {stats['pages_processed']}")
    
    print(f"\nEntities to create: {len(entities_to_create)}")
    print(f"  - person:       {stats['entities_person']}")
    print(f"  - location:     {stats['entities_location']}")
    print(f"  - organization: {stats['entities_organization']}")
    
    print(f"\nRelationships to create: {len(relationships_to_create)}")
    for key in sorted(stats.keys()):
        if key.startswith('relationships_'):
            predicate = key.replace('relationships_', '')
            print(f"  - {predicate:20} {stats[key]:3}")
    
    # Show examples
    print("\n" + "=" * 70)
    print("EXAMPLES (first 3 users with data):\n")
    
    shown = 0
    for page_id, title, chunk_text, url in pages:
        if shown >= 3:
            break
            
        fields = parse_user_page(title, chunk_text)
        username = fields.get('username')
        
        # Skip if no extractable data
        has_data = any(f in fields for f in ENTITY_FIELDS.keys())
        if not has_data:
            continue
        
        print(f"Page: {title}")
        print(f"URL: {url}\n")
        
        print("Entities:")
        print(f"  {username} (person)")
        
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                print(f"  {fields[field_name]} ({entity_type})")
        
        print("\nRelationships:")
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                print(f"  {username} | {predicate} | {fields[field_name]}")
        
        print("\n" + "-" * 70 + "\n")
        shown += 1
    
    # Check for potential duplicates
    print("=" * 70)
    print("DUPLICATE CHECK:\n")
    
    entity_counts = defaultdict(int)
    for e in entities_to_create:
        key = (e['name'], e['type'])
        entity_counts[key] += 1
    
    duplicates = [(k, v) for k, v in entity_counts.items() if v > 1]
    print(f"Entities that appear multiple times: {len(duplicates)}")
    
    if duplicates:
        print("\nTop 10 duplicates:")
        for (name, etype), count in sorted(duplicates, key=lambda x: -x[1])[:10]:
            print(f"  {name} ({etype}): {count} times")
    
    print("\n" + "=" * 70)
    print("NOTE: Duplicates are expected and will be handled by")
    print("      ON CONFLICT (entity_name, entity_type) DO NOTHING")

if __name__ == "__main__":
    dry_run()