# OSGeo Wiki Bot Testing Guide

## Basic Commands

```bash
# Test with a single query
./mcp_client/cli/run.sh "What is OSGeo?"

# Run in interactive mode
./mcp_client/cli/run.sh
```

## Test Query Categories

### Organization & Mission

```bash
# Basic organization queries
./mcp_client/cli/run.sh "What is OSGeo?"
./mcp_client/cli/run.sh "When was OSGeo founded?"
./mcp_client/cli/run.sh "What is OSGeo's mission?"
./mcp_client/cli/run.sh "How is OSGeo governed?"
./mcp_client/cli/run.sh "Who is on the OSGeo board?"
```

### Projects & Software

```bash
# Project-related queries
./mcp_client/cli/run.sh "What projects are part of OSGeo?"
./mcp_client/cli/run.sh "Tell me about QGIS"
./mcp_client/cli/run.sh "What is GDAL used for?"
./mcp_client/cli/run.sh "Explain PostGIS capabilities"
./mcp_client/cli/run.sh "How do I contribute to OSGeo projects?"
```

### Events & Community

```bash
# Event queries
./mcp_client/cli/run.sh "What is FOSS4G?"
./mcp_client/cli/run.sh "When is the next FOSS4G conference?"
./mcp_client/cli/run.sh "What happens at code sprints?"
./mcp_client/cli/run.sh "Are there local OSGeo chapters?"
./mcp_client/cli/run.sh "How can I organize a local OSGeo event?"
```

### Technical Concepts

```bash
# Technical/educational queries
./mcp_client/cli/run.sh "What is open source GIS?"
./mcp_client/cli/run.sh "How does PostgreSQL full-text search work?"
./mcp_client/cli/run.sh "What is a spatial database?"
./mcp_client/cli/run.sh "Explain vector vs raster data"
./mcp_client/cli/run.sh "What resources are available for learning GIS?"
```

### Governance & Membership

```bash
# Governance queries
./mcp_client/cli/run.sh "What are the OSGeo committees?"
./mcp_client/cli/run.sh "How do I become an OSGeo member?"
./mcp_client/cli/run.sh "What is the OSGeo incubation process?"
./mcp_client/cli/run.sh "Who funds OSGeo?"
./mcp_client/cli/run.sh "How are decisions made in OSGeo?"
```

### Follow-up Questions
Use these after asking one of the above questions to test context preservation:

```bash
./mcp_client/cli/run.sh "Tell me more about that"
./mcp_client/cli/run.sh "What else do they do?"
./mcp_client/cli/run.sh "When was it established?"
./mcp_client/cli/run.sh "Who is involved in this?"
./mcp_client/cli/run.sh "Why is this important?"
```