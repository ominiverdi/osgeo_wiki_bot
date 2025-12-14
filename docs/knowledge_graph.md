# Knowledge Graph Options

This document explores options for evolving our entity store into a more capable knowledge graph system.

## Current State

We have a PostgreSQL database with:
- `entities` table (name, type, description)
- `entity_relationships` table (subject_id, predicate, object_id)

This supports:
- Direct lookups ("who is strk?")
- Single-hop queries ("who contributes to QGIS?")
- Predicate-based queries ("list all presidents of OSGeo")

Limitations:
- No multi-hop traversal without complex JOINs
- No inference (can't derive "A is connected to C" from "A->B" and "B->C")
- No formal schema validation
- Predicates are just strings (no formal definitions)

## Option 1: Enhanced PostgreSQL with Recursive Queries

**Effort**: Low | **Infrastructure**: None (use existing PostgreSQL)

### Description

Keep the current schema but add recursive CTEs (Common Table Expressions) for multi-hop queries. This is the simplest enhancement with no new infrastructure.

### Implementation

#### Multi-hop Entity Traversal

```sql
-- Find all entities connected to 'OSGeo' within 2 hops
WITH RECURSIVE connected AS (
    -- Base case: start entity
    SELECT e.id, e.entity_name, e.entity_type, 0 AS depth, 
           ARRAY[e.id] AS path
    FROM entities e 
    WHERE e.entity_name = 'OSGeo'
    
    UNION
    
    -- Recursive case: follow relationships
    SELECT e.id, e.entity_name, e.entity_type, c.depth + 1,
           c.path || e.id
    FROM entities e
    JOIN entity_relationships r ON (e.id = r.subject_id OR e.id = r.object_id)
    JOIN connected c ON (r.subject_id = c.id OR r.object_id = c.id)
    WHERE c.depth < 2
      AND NOT e.id = ANY(c.path)  -- Prevent cycles
)
SELECT DISTINCT entity_name, entity_type, depth
FROM connected
ORDER BY depth, entity_name;
```

#### Find Path Between Two Entities

```sql
-- Find shortest path from 'strk' to 'QGIS'
WITH RECURSIVE paths AS (
    SELECT e.id, e.entity_name, ARRAY[e.entity_name] AS path, 0 AS depth
    FROM entities e
    WHERE e.entity_name = 'strk'
    
    UNION
    
    SELECT e.id, e.entity_name, p.path || e.entity_name, p.depth + 1
    FROM entities e
    JOIN entity_relationships r ON (e.id = r.subject_id OR e.id = r.object_id)
    JOIN paths p ON (r.subject_id = p.id OR r.object_id = p.id)
    WHERE p.depth < 5
      AND NOT e.entity_name = ANY(p.path)
)
SELECT path, depth
FROM paths
WHERE entity_name = 'QGIS'
ORDER BY depth
LIMIT 1;
```

#### Materialized View for Common Queries

```sql
-- Pre-compute 2-hop connections for faster queries
CREATE MATERIALIZED VIEW entity_connections_2hop AS
WITH RECURSIVE connected AS (
    SELECT 
        e1.id AS source_id,
        e1.entity_name AS source_name,
        e2.id AS target_id,
        e2.entity_name AS target_name,
        r.predicate,
        1 AS hops
    FROM entities e1
    JOIN entity_relationships r ON e1.id = r.subject_id
    JOIN entities e2 ON r.object_id = e2.id
    
    UNION
    
    SELECT 
        c.source_id,
        c.source_name,
        e.id AS target_id,
        e.entity_name AS target_name,
        c.predicate || ' -> ' || r.predicate,
        c.hops + 1
    FROM connected c
    JOIN entity_relationships r ON c.target_id = r.subject_id
    JOIN entities e ON r.object_id = e.id
    WHERE c.hops < 2
)
SELECT DISTINCT * FROM connected;

CREATE INDEX idx_connections_source ON entity_connections_2hop(source_name);
CREATE INDEX idx_connections_target ON entity_connections_2hop(target_name);

-- Refresh periodically
-- REFRESH MATERIALIZED VIEW entity_connections_2hop;
```

### Pros
- No new infrastructure
- Works immediately
- Familiar SQL
- Can be added incrementally

### Cons
- Complex queries become hard to read
- Performance degrades with deep traversals
- No inference
- No formal schema

### When to Use
- You need occasional multi-hop queries
- Dataset is small to medium (< 100k entities)
- You want to avoid new infrastructure

---

## Option 2: Apache AGE (Graph Extension for PostgreSQL)

**Effort**: Medium | **Infrastructure**: PostgreSQL extension

### Description

Apache AGE adds graph database capabilities to PostgreSQL, allowing openCypher queries alongside SQL. You keep your existing PostgreSQL database and add graph query support.

### Installation

```bash
# Ubuntu/Debian
sudo apt install postgresql-16-age

# Or build from source
git clone https://github.com/apache/age.git
cd age
make install

# Enable in PostgreSQL
psql -d osgeo_wiki -c "CREATE EXTENSION age;"
psql -d osgeo_wiki -c "LOAD 'age';"
psql -d osgeo_wiki -c "SET search_path = ag_catalog, public;"
```

### Implementation

#### Create Graph Schema

```sql
-- Create a graph
SELECT create_graph('osgeo_graph');

-- Create vertices from existing entities
SELECT * FROM cypher('osgeo_graph', $$
    CREATE (n:Entity {name: 'OSGeo', type: 'organization'})
    RETURN n
$$) as (n agtype);

-- Or bulk load from existing tables
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT entity_name, entity_type FROM entities LOOP
        EXECUTE format(
            'SELECT * FROM cypher(''osgeo_graph'', $q$
                CREATE (n:%s {name: %L})
            $q$) as (n agtype)',
            r.entity_type, r.entity_name
        );
    END LOOP;
END $$;
```

#### Sync Script: PostgreSQL Tables to AGE Graph

```python
# db/sync_to_age.py
"""Sync entity tables to Apache AGE graph."""

import psycopg2

def sync_entities_to_graph(conn):
    """Create graph vertices from entities table."""
    cur = conn.cursor()
    
    # Clear existing graph
    cur.execute("SELECT drop_graph('osgeo_graph', true);")
    cur.execute("SELECT create_graph('osgeo_graph');")
    
    # Load entities as vertices
    cur.execute("""
        SELECT id, entity_name, entity_type 
        FROM entities
    """)
    
    for entity_id, name, etype in cur.fetchall():
        # Escape for Cypher
        safe_name = name.replace("'", "\\'")
        cur.execute(f"""
            SELECT * FROM cypher('osgeo_graph', $$
                CREATE (n:{etype} {{id: {entity_id}, name: '{safe_name}'}})
            $$) as (n agtype)
        """)
    
    # Load relationships as edges
    cur.execute("""
        SELECT r.subject_id, r.predicate, r.object_id,
               s.entity_type as stype, o.entity_type as otype
        FROM entity_relationships r
        JOIN entities s ON r.subject_id = s.id
        JOIN entities o ON r.object_id = o.id
    """)
    
    for subj_id, predicate, obj_id, stype, otype in cur.fetchall():
        cur.execute(f"""
            SELECT * FROM cypher('osgeo_graph', $$
                MATCH (s:{stype} {{id: {subj_id}}}), (o:{otype} {{id: {obj_id}}})
                CREATE (s)-[r:{predicate}]->(o)
                RETURN r
            $$) as (r agtype)
        """)
    
    conn.commit()
    print("Graph sync complete")
```

#### Query Examples

```sql
-- Find all people who contribute to OSGeo projects
SELECT * FROM cypher('osgeo_graph', $$
    MATCH (p:person)-[:contributes_to]->(proj)-[:part_of]->(o:organization)
    WHERE o.name = 'OSGeo'
    RETURN p.name, proj.name
$$) as (person agtype, project agtype);

-- Find path between two entities
SELECT * FROM cypher('osgeo_graph', $$
    MATCH path = shortestPath((a)-[*..5]-(b))
    WHERE a.name = 'strk' AND b.name = 'PostGIS'
    RETURN path
$$) as (path agtype);

-- Find all entities within 2 hops of QGIS
SELECT * FROM cypher('osgeo_graph', $$
    MATCH (start {name: 'QGIS'})-[*1..2]-(connected)
    RETURN DISTINCT connected.name, labels(connected)
$$) as (name agtype, labels agtype);

-- Count relationships by type
SELECT * FROM cypher('osgeo_graph', $$
    MATCH ()-[r]->()
    RETURN type(r) as relationship, count(*) as count
    ORDER BY count DESC
$$) as (relationship agtype, count agtype);
```

#### Integration with Matrix Agent

```python
# In matrix-llmagent knowledge base tool
async def graph_query(self, cypher: str) -> list[dict]:
    """Execute Cypher query via Apache AGE."""
    async with self.pool.acquire() as conn:
        await conn.execute("LOAD 'age';")
        await conn.execute("SET search_path = ag_catalog, public;")
        
        # Wrap Cypher in AGE function
        sql = f"""
            SELECT * FROM cypher('osgeo_graph', $$
                {cypher}
            $$) as (result agtype)
        """
        rows = await conn.fetch(sql)
        return [dict(r) for r in rows]
```

### Pros
- Single database (PostgreSQL)
- Native graph queries (Cypher)
- Can mix SQL and Cypher
- Path queries, variable-length patterns
- Good performance for graph operations

### Cons
- Extra extension to maintain
- Need to sync data from relational tables to graph
- No inference engine
- Limited ecosystem compared to Neo4j

### When to Use
- You need real graph queries but want to keep PostgreSQL
- Multi-hop traversals are common
- You want path-finding capabilities

---

## Option 3: Neo4j (Dedicated Graph Database)

**Effort**: High | **Infrastructure**: Separate Neo4j instance

### Description

Neo4j is the most popular graph database with a mature ecosystem, visualization tools, and native Cypher support. This option adds Neo4j alongside PostgreSQL.

### Installation

```bash
# Docker (recommended)
docker run -d \
    --name neo4j \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/password \
    -v neo4j_data:/data \
    neo4j:latest

# Or install directly
# https://neo4j.com/docs/operations-manual/current/installation/
```

### Implementation

#### Sync Script: PostgreSQL to Neo4j

```python
# db/sync_to_neo4j.py
"""Sync PostgreSQL entities to Neo4j graph database."""

import psycopg2
from neo4j import GraphDatabase

class Neo4jSync:
    def __init__(self, pg_conn_string: str, neo4j_uri: str, neo4j_auth: tuple):
        self.pg_conn = psycopg2.connect(pg_conn_string)
        self.neo4j = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
    
    def sync_all(self):
        """Full sync from PostgreSQL to Neo4j."""
        self._clear_graph()
        self._sync_entities()
        self._sync_relationships()
        self._create_indexes()
    
    def _clear_graph(self):
        with self.neo4j.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    
    def _sync_entities(self):
        cur = self.pg_conn.cursor()
        cur.execute("SELECT id, entity_name, entity_type, url FROM entities")
        
        with self.neo4j.session() as session:
            for entity_id, name, etype, url in cur.fetchall():
                session.run(
                    f"""
                    CREATE (n:{etype} {{
                        pg_id: $id,
                        name: $name,
                        url: $url
                    }})
                    """,
                    id=entity_id, name=name, url=url
                )
        print(f"Synced {cur.rowcount} entities")
    
    def _sync_relationships(self):
        cur = self.pg_conn.cursor()
        cur.execute("""
            SELECT r.subject_id, r.predicate, r.object_id, r.confidence
            FROM entity_relationships r
        """)
        
        with self.neo4j.session() as session:
            for subj_id, predicate, obj_id, confidence in cur.fetchall():
                # Dynamic relationship type from predicate
                session.run(
                    f"""
                    MATCH (s {{pg_id: $subj_id}}), (o {{pg_id: $obj_id}})
                    CREATE (s)-[r:{predicate} {{confidence: $confidence}}]->(o)
                    """,
                    subj_id=subj_id, obj_id=obj_id, confidence=confidence
                )
        print(f"Synced {cur.rowcount} relationships")
    
    def _create_indexes(self):
        with self.neo4j.session() as session:
            session.run("CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)")
            session.run("CREATE INDEX entity_pg_id IF NOT EXISTS FOR (n:Entity) ON (n.pg_id)")

if __name__ == "__main__":
    sync = Neo4jSync(
        pg_conn_string="postgresql:///osgeo_wiki",
        neo4j_uri="bolt://localhost:7687",
        neo4j_auth=("neo4j", "password")
    )
    sync.sync_all()
```

#### Query Examples

```cypher
// Find all paths between strk and OSGeo (max 4 hops)
MATCH path = (a:person {name: 'strk'})-[*1..4]-(b:organization {name: 'OSGeo'})
RETURN path

// Find influential people (high connectivity)
MATCH (p:person)-[r]-()
RETURN p.name, count(r) as connections
ORDER BY connections DESC
LIMIT 10

// Find communities (people who share projects)
MATCH (p1:person)-[:contributes_to]->(proj)<-[:contributes_to]-(p2:person)
WHERE p1 <> p2
RETURN p1.name, p2.name, collect(proj.name) as shared_projects

// Recommend connections (friends of friends)
MATCH (p:person {name: 'strk'})-[:contributes_to]->()<-[:contributes_to]-(other)
WHERE p <> other
AND NOT (p)-[:knows]-(other)
RETURN other.name, count(*) as common_projects
ORDER BY common_projects DESC

// Find all FOSS4G conferences and their details
MATCH (f:event)-[r]->(related)
WHERE f.name STARTS WITH 'FOSS4G'
RETURN f.name, type(r), related.name
ORDER BY f.name
```

#### Integration with Matrix Agent

```python
# matrix_llmagent/tools/neo4j_search.py
from neo4j import AsyncGraphDatabase

class Neo4jSearchExecutor:
    def __init__(self, uri: str, auth: tuple):
        self.driver = AsyncGraphDatabase.driver(uri, auth=auth)
    
    async def execute(self, query: str, entity: str = None) -> str:
        """Execute a graph search query."""
        async with self.driver.session() as session:
            # Pattern-based query selection
            if "path" in query.lower() or "connected" in query.lower():
                result = await self._find_paths(session, entity)
            elif "who" in query.lower():
                result = await self._find_people(session, query)
            else:
                result = await self._general_search(session, entity)
            
            return self._format_results(result)
    
    async def _find_paths(self, session, entity: str):
        result = await session.run(
            """
            MATCH path = (a {name: $entity})-[*1..3]-(b)
            RETURN DISTINCT b.name as connected, length(path) as distance
            ORDER BY distance
            LIMIT 20
            """,
            entity=entity
        )
        return await result.data()
```

### Pros
- Best-in-class graph database
- Rich visualization (Neo4j Browser)
- Mature ecosystem, good documentation
- Graph algorithms library (centrality, community detection, etc.)
- Native Cypher query language

### Cons
- Separate database to maintain
- Data sync complexity
- Additional cost (Enterprise features)
- Learning curve

### When to Use
- Complex graph analytics are core to your use case
- You need visualization
- Dataset is large and graph-heavy
- You want graph algorithms (PageRank, community detection)

---

## Option 4: RDF/SPARQL with Formal Ontology

**Effort**: Very High | **Infrastructure**: Triple store

### Description

Convert to RDF (Resource Description Framework) with a formal OWL ontology. This enables inference, links to external knowledge (Wikidata), and standard SPARQL queries.

### Implementation Sketch

#### Define Ontology (OWL)

```turtle
# osgeo_ontology.ttl
@prefix osgeo: <https://wiki.osgeo.org/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

# Classes
osgeo:Person a owl:Class ;
    rdfs:label "Person" .

osgeo:Project a owl:Class ;
    rdfs:label "Software Project" .

osgeo:Organization a owl:Class ;
    rdfs:label "Organization" .

osgeo:Event a owl:Class ;
    rdfs:label "Event" .

# Properties
osgeo:contributesTo a owl:ObjectProperty ;
    rdfs:domain osgeo:Person ;
    rdfs:range osgeo:Project ;
    rdfs:label "contributes to" .

osgeo:partOf a owl:ObjectProperty ;
    rdfs:domain osgeo:Project ;
    rdfs:range osgeo:Organization ;
    rdfs:label "is part of" .

osgeo:locatedIn a owl:ObjectProperty ;
    rdfs:domain osgeo:Event ;
    rdfs:range osgeo:Location ;
    rdfs:label "located in" .

# Inference rules
osgeo:involvedWith a owl:ObjectProperty ;
    owl:propertyChainAxiom (osgeo:contributesTo osgeo:partOf) ;
    rdfs:comment "If person contributes to project and project is part of org, person is involved with org" .
```

#### Convert Data to RDF

```python
# db/export_rdf.py
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS

OSGEO = Namespace("https://wiki.osgeo.org/entity/")
OSGEO_ONT = Namespace("https://wiki.osgeo.org/ontology#")

def export_to_rdf(pg_conn) -> Graph:
    g = Graph()
    g.bind("osgeo", OSGEO)
    g.bind("osgeo-ont", OSGEO_ONT)
    
    cur = pg_conn.cursor()
    
    # Export entities
    cur.execute("SELECT id, entity_name, entity_type FROM entities")
    for entity_id, name, etype in cur.fetchall():
        uri = OSGEO[f"entity/{entity_id}"]
        type_uri = OSGEO_ONT[etype.capitalize()]
        
        g.add((uri, RDF.type, type_uri))
        g.add((uri, RDFS.label, Literal(name)))
    
    # Export relationships
    cur.execute("""
        SELECT subject_id, predicate, object_id 
        FROM entity_relationships
    """)
    for subj_id, predicate, obj_id in cur.fetchall():
        subj_uri = OSGEO[f"entity/{subj_id}"]
        obj_uri = OSGEO[f"entity/{obj_id}"]
        pred_uri = OSGEO_ONT[predicate]
        
        g.add((subj_uri, pred_uri, obj_uri))
    
    return g

# Save as Turtle
g = export_to_rdf(conn)
g.serialize("osgeo_knowledge.ttl", format="turtle")
```

#### SPARQL Queries

```sparql
# Find all people involved with OSGeo (with inference)
PREFIX osgeo: <https://wiki.osgeo.org/ontology#>

SELECT ?person ?personName WHERE {
    ?person a osgeo:Person ;
            rdfs:label ?personName ;
            osgeo:involvedWith ?org .
    ?org rdfs:label "OSGeo" .
}

# Find conferences and their locations
SELECT ?event ?eventName ?location ?locationName WHERE {
    ?event a osgeo:Event ;
           rdfs:label ?eventName ;
           osgeo:locatedIn ?location .
    ?location rdfs:label ?locationName .
    FILTER(STRSTARTS(?eventName, "FOSS4G"))
}

# Link to Wikidata (federated query)
SELECT ?project ?projectName ?wikidataLink WHERE {
    ?project a osgeo:Project ;
             rdfs:label ?projectName .
    SERVICE <https://query.wikidata.org/sparql> {
        ?wikidataLink rdfs:label ?projectName .
        ?wikidataLink wdt:P31 wd:Q7397 .  # instance of software
    }
}
```

### Pros
- Formal semantics and inference
- Can link to external knowledge (Wikidata, DBpedia)
- Standards-based (W3C)
- Rich query language (SPARQL)

### Cons
- Steep learning curve
- Complex tooling
- Performance can be challenging
- Overkill for most use cases

### When to Use
- You need formal reasoning/inference
- Linking to external knowledge bases is important
- You're building a semantic web application

---

## Recommendation

For the OSGeo Wiki Database project, we recommend a phased approach:

### Phase 1: Enhanced PostgreSQL (Now)
- Add recursive queries for multi-hop traversal
- Create materialized views for common patterns
- **Effort**: Days
- **Value**: Handle 90% of graph-like queries

### Phase 2: Apache AGE (When Needed)
- Install when recursive CTEs become unwieldy
- Enables native Cypher queries
- **Effort**: 1-2 weeks
- **Trigger**: When you need path-finding or complex traversals

### Phase 3: Neo4j (If Required)
- Only if you need visualization or graph algorithms
- Keep PostgreSQL as source of truth, sync to Neo4j
- **Effort**: 2-4 weeks
- **Trigger**: Analytics, visualization, or scale requirements

### Skip: RDF/SPARQL
- Unless you specifically need to link to Wikidata/DBpedia
- The overhead isn't justified for our use case

## Implementation Checklist

### Phase 1 Tasks
- [ ] Add recursive query examples to `db/` scripts
- [ ] Create materialized view for 2-hop connections
- [ ] Add graph query functions to test scripts
- [ ] Document common query patterns

### Phase 2 Tasks
- [ ] Install Apache AGE extension
- [ ] Create sync script from entities to graph
- [ ] Add Cypher query wrapper for Matrix agent
- [ ] Benchmark against recursive CTEs

### Phase 3 Tasks
- [ ] Set up Neo4j instance (Docker)
- [ ] Create full sync pipeline
- [ ] Add Neo4j executor to Matrix agent
- [ ] Set up Neo4j Browser for visualization
