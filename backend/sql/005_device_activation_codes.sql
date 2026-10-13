BEGIN;

CREATE TABLE IF NOT EXISTS shrimp.device_activation_codes (
    device_id uuid PRIMARY KEY REFERENCES shrimp.devices(id) ON DELETE CASCADE,
    code_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE shrimp.device_activation_codes IS
    'Hashed, short-lived, single-use device activation codes. Issuing a new code replaces the previous one.';

COMMIT;
