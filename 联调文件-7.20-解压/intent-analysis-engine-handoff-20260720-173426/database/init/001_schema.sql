CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS function_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    function_code VARCHAR(64) NOT NULL UNIQUE,
    function_name VARCHAR(200) NOT NULL,
    intent_category VARCHAR(80) NOT NULL,
    target_engine VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    required_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    example_sentences JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_function_registry_function_code
    ON function_registry (function_code);

CREATE INDEX IF NOT EXISTS idx_function_registry_intent_category
    ON function_registry (intent_category);

CREATE INDEX IF NOT EXISTS idx_function_registry_target_engine
    ON function_registry (target_engine);

CREATE INDEX IF NOT EXISTS idx_function_registry_status
    ON function_registry (status);

CREATE TABLE IF NOT EXISTS rule_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword VARCHAR(120) NOT NULL,
    pattern TEXT,
    function_code VARCHAR(64) NOT NULL REFERENCES function_registry(function_code),
    priority INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rule_mapping_keyword
    ON rule_mapping (keyword);

CREATE INDEX IF NOT EXISTS idx_rule_mapping_function_code
    ON rule_mapping (function_code);

CREATE INDEX IF NOT EXISTS idx_rule_mapping_status
    ON rule_mapping (status);

CREATE TABLE IF NOT EXISTS intent_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_text TEXT NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    conversation_id VARCHAR(120) NOT NULL,
    analysis_level VARCHAR(64) NOT NULL,
    matched_function VARCHAR(64) REFERENCES function_registry(function_code),
    confidence NUMERIC(5, 4),
    result VARCHAR(64) NOT NULL,
    cost_time INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_record_user_id
    ON intent_record (user_id);

CREATE INDEX IF NOT EXISTS idx_intent_record_conversation_id
    ON intent_record (conversation_id);

CREATE INDEX IF NOT EXISTS idx_intent_record_analysis_level
    ON intent_record (analysis_level);

CREATE INDEX IF NOT EXISTS idx_intent_record_matched_function
    ON intent_record (matched_function);

CREATE INDEX IF NOT EXISTS idx_intent_record_result
    ON intent_record (result);

CREATE TABLE IF NOT EXISTS conversation_message (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id VARCHAR(120) NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    content TEXT NOT NULL,
    analysis_result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversation_message_conversation_id
    ON conversation_message (conversation_id);

CREATE INDEX IF NOT EXISTS idx_conversation_message_user_id
    ON conversation_message (user_id);

CREATE INDEX IF NOT EXISTS idx_conversation_message_role
    ON conversation_message (role);

CREATE INDEX IF NOT EXISTS idx_conversation_message_lookup
    ON conversation_message (user_id, conversation_id, created_at);
