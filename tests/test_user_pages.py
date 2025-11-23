# tests/test_user_pages.py
import psycopg2
import os
from collections import defaultdict
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

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
    # Wiki template syntax
    if value.startswith('[[') or value.startswith('{{{'):
        return True
    # Other non-informative values
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
        
        # Check if it's a field label (ends with ':')
        if line.endswith(':'):
            field_name = line[:-1].lower().replace(' ', '_').replace('(', '').replace(')', '')
            
            # Look at next line for value
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                
                # Value is valid if:
                # - Not another field label
                # - Not a placeholder
                # - Not empty
                if next_line and \
                   not next_line.endswith(':') and \
                   not is_placeholder(next_line):
                    fields[field_name] = next_line
        
        i += 1
    
    return fields

def analyze_user_pages(limit=None):
    """Analyze all user pages and show what could be extracted."""
    conn = connect_db()
    cur = conn.cursor()
    
    query = """
        SELECT p.title, pc.chunk_text, p.url
        FROM pages p
        JOIN page_chunks pc ON p.id = pc.page_id
        WHERE p.title LIKE 'User:%'
        AND pc.chunk_index = 0
        ORDER BY p.title
    """
    if limit:
        query += f" LIMIT {limit}"
    
    cur.execute(query)
    
    results = []
    field_stats = defaultdict(int)
    all_fields_seen = set()
    
    for title, chunk_text, url in cur.fetchall():
        fields = parse_user_page(title, chunk_text)
        
        # Track all field names we've seen
        all_fields_seen.update(fields.keys())
        
        # Count non-empty fields
        for key, value in fields.items():
            if value:
                field_stats[key] += 1
        
        results.append({
            'title': title,
            'url': url,
            'fields': fields
        })
    
    cur.close()
    conn.close()
    
    return results, field_stats, all_fields_seen

def print_entities_and_relationships(user_data):
    """Print what entities and relationships would be created."""
    fields = user_data['fields']
    username = fields.get('username')
    real_name = fields.get('name')
    location = fields.get('address') or fields.get('city')
    
    print(f"\n{'='*60}")
    print(f"Page: {user_data['title']}")
    print(f"URL: {user_data['url']}")
    print(f"\nExtracted fields:")
    
    if len(fields) <= 1:  # Only username
        print("  [No usable data]")
        return
    
    for key, value in sorted(fields.items()):
        if value and key != 'username':
            print(f"  {key}: {value}")
    
    print(f"\nEntities to create:")
    if username:
        print(f"  - {username} (person)")
    if real_name:
        print(f"  - {real_name} (person)")
    if location:
        print(f"  - {location} (location)")
    
    if not (username and real_name):
        print("  [Insufficient data for relationships]")
        return
    
    print(f"\nRelationships to create:")
    if username and real_name:
        print(f"  - {username} | is_alias_of | {real_name}")
    if username and location:
        print(f"  - {username} | lives_in | {location}")
    if real_name and location:
        print(f"  - {real_name} | lives_in | {location}")

if __name__ == "__main__":
    print("Analyzing User: pages...")
    
    # Analyze all user pages
    results, field_stats, all_fields = analyze_user_pages()
    
    total = len(results)
    print(f"\nTotal User: pages: {total}")
    
    print(f"\nAll template fields found:")
    for field in sorted(all_fields):
        count = field_stats[field]
        pct = 100 * count / total
        print(f"  {field:25} {count:3}/{total} ({pct:5.1f}%)")
    
    # Count users with complete data (name + some location)
    complete_users = []
    for r in results:
        f = r['fields']
        has_name = bool(f.get('name'))
        has_location = bool(f.get('address') or f.get('city'))
        if has_name and has_location:
            complete_users.append(r)
    
    print(f"\n{'='*60}")
    print("DETAILED EXAMPLES (first 5 with data):")
    shown = 0
    for user_data in results:
        if shown >= 5:
            break
        if len(user_data['fields']) > 1:  # Has more than just username
            print_entities_and_relationships(user_data)
            shown += 1
    
    print(f"\n{'='*60}")
    print(f"USERS WITH COMPLETE DATA (name + location):")
    print(f"\nFound {len(complete_users)} users")
    for user_data in complete_users[:15]:
        f = user_data['fields']
        loc = f.get('address') or f.get('city') or '?'
        print(f"  - {f['username']}: {f.get('name', '?')} ({loc})")