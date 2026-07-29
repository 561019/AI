# Project Structure

The scaffold follows the confirmed platform architecture:

- `backend/`: FastAPI service for L2 intent analysis entry points and data contracts.
- `frontend/`: React and TypeScript console for basic L4-style request testing.
- `database/`: PostgreSQL bootstrap SQL and Milvus collection notes.
- `tests/`: Automated tests for the scaffold.
- `docs/`: Original architecture and requirement documents plus development notes.

Current implementation scope:

- API contracts and health endpoint are available.
- SQLAlchemy models mirror the planned PostgreSQL tables.
- Docker Compose provisions backend, frontend, PostgreSQL, Milvus, etcd, and MinIO.
- AI logic, rule matching, semantic matching, model calls, parameter extraction, clarification rounds, task-list generation, and judgment-record persistence are intentionally left for later phases.
