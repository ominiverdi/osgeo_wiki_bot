# tests/test_user_entities_sql_preview.py
import psycopg2
import os
from collections import defaultdict
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

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
    if not value:
        return True
    if value.startswith('[[') or value.startswith('{{{'):
        return True
    if value in ['Loading map...', 'OSGeo Member']:
        return True
    return False

def parse_user_page(title, chunk_text):
    fields = {'username': title.replace('User:', '')}
    lines = chunk_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        if line.endswith(':'):
            field_name = line[:-1].lower().replace(' ', '_').replace('(', '').replace(')', '')
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.endswith(':') and not is_placeholder(next_line):
                    fields[field_name] = next_line
        i += 1
    
    return fields

def get_user_pages():
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

def generate_sql_statements():
    """Generate all SQL statements that would be executed."""
    
    pages = get_user_pages()
    
    entity_inserts = []
    relationship_inserts = []
    stats = defaultdict(int)
    
    for page_id, title, chunk_text, url in pages:
        fields = parse_user_page(title, chunk_text)
        username = fields.get('username')
        
        stats['pages_processed'] += 1
        
        # SQL for username entity
        entity_inserts.append({
            'sql': f"""INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url, confidence)
VALUES ('person', '{username}', {page_id}, '{url}', 1.0)
ON CONFLICT (entity_name, entity_type) DO NOTHING;""",
            'page': title,
            'entity': username,
            'type': 'person'
        })
        
        # Track entity IDs we'd need (in real script, would come from RETURNING clause)
        username_entity_id = f"<id for {username}>"
        
        # Process whitelisted fields
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                value = fields[field_name]
                # Escape single quotes for SQL
                value_escaped = value.replace("'", "''")
                
                # Entity insert
                entity_inserts.append({
                    'sql': f"""INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url, confidence)
VALUES ('{entity_type}', '{value_escaped}', {page_id}, '{url}', 1.0)
ON CONFLICT (entity_name, entity_type) DO NOTHING;""",
                    'page': title,
                    'entity': value,
                    'type': entity_type
                })
                stats[f'entities_{entity_type}'] += 1
                
                # Relationship insert
                value_entity_id = f"<id for {value}>"
                relationship_inserts.append({
                    'sql': f"""-- Get entity IDs first, then:
INSERT INTO entity_relationships (subject_id, predicate, object_id, source_page_id, confidence)
VALUES ({username_entity_id}, '{predicate}', {value_entity_id}, {page_id}, 1.0)
ON CONFLICT DO NOTHING;""",
                    'page': title,
                    'subject': username,
                    'predicate': predicate,
                    'object': value
                })
                stats[f'relationships_{predicate}'] += 1
    
    return entity_inserts, relationship_inserts, stats

def show_sql_preview():
    print("SQL PREVIEW - User Entity Population")
    print("=" * 70)
    
    entity_inserts, relationship_inserts, stats = generate_sql_statements()
    
    # Summary
    print(f"\nPages to process: {stats['pages_processed']}")
    print(f"Total entity INSERTs: {len(entity_inserts)}")
    print(f"Total relationship INSERTs: {len(relationship_inserts)}")
    
    print(f"\nEntity breakdown:")
    print(f"  - person:       {stats['entities_person']}")
    print(f"  - location:     {stats['entities_location']}")
    print(f"  - organization: {stats['entities_organization']}")
    
    print(f"\nRelationship breakdown:")
    for key in sorted(stats.keys()):
        if key.startswith('relationships_'):
            predicate = key.replace('relationships_', '')
            print(f"  - {predicate:20} {stats[key]:3}")
    
    # Show first 3 complete examples
    print("\n" + "=" * 70)
    print("DETAILED SQL EXAMPLES (first 3 users):\n")
    
    pages = get_user_pages()
    shown = 0
    
    for page_id, title, chunk_text, url in pages:
        if shown >= 3:
            break
        
        fields = parse_user_page(title, chunk_text)
        username = fields.get('username')
        
        # Skip if no data
        has_data = any(f in fields for f in ENTITY_FIELDS.keys())
        if not has_data:
            continue
        
        print(f"-- Page: {title}")
        print(f"-- URL: {url}\n")
        
        # Username entity
        print(f"-- Create username entity")
        print(f"INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url, confidence)")
        print(f"VALUES ('person', '{username}', {page_id}, '{url}', 1.0)")
        print(f"ON CONFLICT (entity_name, entity_type) DO NOTHING;\n")
        
        # Field entities
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                value = fields[field_name].replace("'", "''")
                print(f"-- Create {field_name} entity")
                print(f"INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url, confidence)")
                print(f"VALUES ('{entity_type}', '{value}', {page_id}, '{url}', 1.0)")
                print(f"ON CONFLICT (entity_name, entity_type) DO NOTHING;\n")
        
        # Relationships
        print(f"-- Create relationships")
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                value = fields[field_name].replace("'", "''")
                print(f"-- {username} | {predicate} | {value}")
                print(f"-- (Would need to fetch entity IDs first)")
        
        print("\n" + "-" * 70 + "\n")
        shown += 1
    
    # Check current state
    print("=" * 70)
    print("CURRENT DATABASE STATE CHECK:\n")
    
    conn = connect_db()
    cur = conn.cursor()
    
    # Check if any user entities already exist
    cur.execute("""
        SELECT COUNT(*) 
        FROM entities 
        WHERE source_page_id IN (
            SELECT id FROM pages WHERE title LIKE 'User:%'
        )
    """)
    existing_from_users = cur.fetchone()[0]
    
    # Check total entities
    cur.execute("SELECT COUNT(*) FROM entities")
    total_entities = cur.fetchone()[0]
    
    # Check total relationships
    cur.execute("SELECT COUNT(*) FROM entity_relationships")
    total_relationships = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    print(f"Current entities in database: {total_entities}")
    print(f"  - From User: pages: {existing_from_users}")
    print(f"Current relationships: {total_relationships}")
    
    print(f"\nAfter population would have:")
    print(f"  - Entities: ~{total_entities + len(entity_inserts)}")
    print(f"  - Relationships: ~{total_relationships + len(relationship_inserts)}")
    
    print("\n" + "=" * 70)
    print("NOTES:")
    print("- ON CONFLICT clauses prevent duplicates")
    print("- Script would need to fetch entity IDs after INSERT")
    print("- Relationships use entity IDs, not names")
    print("- Quotes in names are properly escaped")

if __name__ == "__main__":
    show_sql_preview()