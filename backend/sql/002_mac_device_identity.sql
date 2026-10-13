-- Give MAC addresses a single canonical form while preserving legacy serials
-- and their existing readings. This migration stops before modifying data if
-- equivalent MACs or duplicate readings already exist.
BEGIN;

CREATE OR REPLACE FUNCTION shrimp.normalize_device_mac(p_mac text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN btrim(p_mac) ~* '^([0-9a-f]{12}|([0-9a-f]{2}:){5}[0-9a-f]{2}|([0-9a-f]{2}-){5}[0-9a-f]{2})$'
        THEN upper(replace(replace(btrim(p_mac), ':', ''), '-', ''))
        ELSE NULL
    END
$$;

CREATE OR REPLACE FUNCTION shrimp.prevent_device_mac_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.mac_address IS NOT NULL AND NEW.mac_address IS DISTINCT FROM OLD.mac_address THEN
        RAISE EXCEPTION 'device MAC address is immutable' USING ERRCODE = '22023';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE shrimp.devices
    ADD COLUMN IF NOT EXISTS mac_address text
    GENERATED ALWAYS AS (shrimp.normalize_device_mac(serial)) STORED;

DO $$ BEGIN
    IF EXISTS (
        SELECT mac_address FROM shrimp.devices
        WHERE mac_address IS NOT NULL
        GROUP BY mac_address HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate normalized device MAC addresses; resolve duplicates before migration';
    END IF;
    IF EXISTS (
        SELECT device_id, recorded_at FROM shrimp.probe_readings
        WHERE device_id IS NOT NULL
        GROUP BY device_id, recorded_at HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate device readings; resolve duplicates before migration';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS devices_mac_address
    ON shrimp.devices (mac_address) WHERE mac_address IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS probe_readings_device_id_recorded
    ON shrimp.probe_readings (device_id, recorded_at) WHERE device_id IS NOT NULL;
DROP TRIGGER IF EXISTS devices_mac_immutable ON shrimp.devices;
CREATE TRIGGER devices_mac_immutable
    BEFORE UPDATE OF serial ON shrimp.devices
    FOR EACH ROW EXECUTE FUNCTION shrimp.prevent_device_mac_change();

COMMIT;
