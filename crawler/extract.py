import requests
import psycopg2
import re

API_URL = "https://wiki.osgeo.org/api.php"

def get_all_pages():
    session = requests.Session()
    apcontinue = None
    titles = []
    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "aplimit": "max",
            "format": "json"
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        res = session.get(API_URL, params=params).json()
        titles += [p["title"] for p in res["query"]["allpages"]]
        if "continue" not in res:
            break
        apcontinue = res["continue"]["apcontinue"]
    return titles

def get_page_content(title):
    res = requests.get(API_URL, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "format": "json",
        "titles": title
    }).json()
    pages = res["query"]["pages"]
    content = next(iter(pages.values()))["revisions"][0]["*"]
    return content

def extract_code_blocks(content):
    return re.findall(r"<syntaxhighlight.*?>(.*?)</syntaxhighlight>", content, re.DOTALL)

# Connect to PostgreSQL
conn = psycopg2.connect("dbname=osgeo_wiki user=ominiverdi")
cur = conn.cursor()

# Store a page and its snippets
for title in get_all_pages():
    content = get_page_content(title)
    cur.execute("INSERT INTO pages (title, content, tsv) VALUES (%s, %s, to_tsvector(%s)) RETURNING id",
                (title, content, content))
    page_id = cur.fetchone()[0]
    for snippet in extract_code_blocks(content):
        cur.execute("INSERT INTO code_snippets (page_id, snippet, language) VALUES (%s, %s, %s)",
                    (page_id, snippet.strip(), 'unknown'))
    conn.commit()
