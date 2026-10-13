BEGIN;

CREATE TABLE IF NOT EXISTS shrimp.device_api_keys (
    device_id uuid PRIMARY KEY REFERENCES shrimp.devices(id) ON DELETE CASCADE,
    key_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE shrimp.device_api_keys IS
    'SHA-256 hashes of random per-device HTTP ingestion keys; plaintext keys are never stored.';

COMMIT;
