# Entity Extraction

This document describes the entity extraction and knowledge graph construction process.

## Entity Types

### People
- OSGeo board members
- Project contributors
- Community members
- Charter members

### Projects
- OSGeo projects (QGIS, GDAL, PostGIS, etc.)
- Incubating projects
- Community projects

### Organizations
- OSGeo Foundation
- Local chapters
- Partner organizations
- Sponsors

### Events
- FOSS4G conferences
- Code sprints
- Community meetings
- Webinars

## Extraction Pipeline

### Phase 1: Rule-based Extraction

1. **Wiki categories** - Extract entities from category assignments
2. **Infoboxes** - Parse structured wiki templates
3. **Links** - Internal wiki links often indicate entities
4. **Lists** - Member lists, project lists, etc.

### Phase 2: NLP Extraction (Planned)

1. **Named Entity Recognition** - Identify person/org/location names
2. **Coreference Resolution** - Link mentions to same entity
3. **Relation Extraction** - Identify relationships between entities

## Knowledge Graph

### Relationship Types

| Predicate | Description | Example |
|-----------|-------------|---------|
| `member_of` | Person is member of org | Frank -> OSGeo |
| `contributes_to` | Person contributes to project | User -> QGIS |
| `part_of` | Project is part of org | GDAL -> OSGeo |
| `located_in` | Event located in place | FOSS4G 2023 -> Kosovo |
| `founded` | Person founded project | X -> Project |
| `related_to` | General relationship | Project A -> Project B |

### Graph Queries

Example queries the graph should support:

- "Who contributes to GDAL?"
- "What projects is Frank involved with?"
- "What events happened in 2023?"
- "How are QGIS and PostGIS related?"

## Database Population

**Scripts**:
- `db/populate_entities.py` - Extract and store entities
- `db/populate_user_entities.py` - Extract user/people entities

## Quality Assurance

### Deduplication

- Normalize entity names
- Match aliases
- Merge duplicate entries

### Validation

- Check relationship consistency
- Verify entity types
- Flag uncertain extractions for review

## Future Improvements

- ML-based entity extraction
- Confidence scoring
- User feedback loop for corrections
- Cross-source entity linking
