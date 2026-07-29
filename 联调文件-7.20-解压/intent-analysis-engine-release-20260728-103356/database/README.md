# Database

This folder contains database bootstrap assets.

- `init/001_schema.sql` creates the PostgreSQL tables required by the current scaffold.
- `init/002_seed_data.sql` inserts database-layer test data for initial intent categories and rule mappings.
- `migrations/` is reserved for future migration tooling.
- Milvus stores example sentence vectors and is provisioned through Docker Compose.

The initial schema mirrors the SQLAlchemy models in `backend/app/models`.

Core PostgreSQL tables:

- `function_registry`
- `rule_mapping`
- `intent_record`
