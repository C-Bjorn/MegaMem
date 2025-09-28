---
title: Database Setup Guide
description: Simple setup for Neo4j and FalkorDB databases for MegaMem
type: guide
category: setup
difficulty: beginner
tags:
  - database
  - neo4j
  - falkordb
  - installation
last_updated: 2025-01-23
date_created: 2025-09-23T11:36
date_updated: 2025-09-28T11:36
---

# Database Setup Guide

MegaMem requires a graph database to store your knowledge graph. Choose one of the supported options below.

## Neo4j (Recommended)

### Docker Setup
```bash
# Run Neo4j with Docker
docker run -d \
  --name neo4j-megamem \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/megamem123 \
  neo4j:latest
```

### Verification
- Open http://localhost:7474 in your browser
- Login with username: `neo4j`, password: `megamem123`
- Run test query: `MATCH (n) RETURN count(n)`

### MegaMem Configuration
- Database Type: `neo4j`
- URI: `bolt://localhost:7687`
- Username: `neo4j`
- Password: `megamem123`
- Database Name: `neo4j`

## FalkorDB (Alternative)

### Docker Setup
```bash
# Run FalkorDB with Docker
docker run -d \
  --name falkordb-megamem \
  -p 6379:6379 \
  falkordb/falkordb:latest
```

### Verification
```bash
# Test connection
redis-cli -h localhost -p 6379 ping
# Should return: PONG
```

### MegaMem Configuration
- Database Type: `falkordb`
- Host: `localhost`
- Port: `6379`
- Password: (leave empty)
- Database Name: `megamem`

## Next Steps

1. Return to [Quick Start Guide](../quick-start.md) to continue setup
2. Configure MegaMem database settings
3. Test connection and initialize schema