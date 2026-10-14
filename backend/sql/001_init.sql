-- Uni-Shrimp schema. Apply against database UPVN_SHRIMP.

CREATE SCHEMA IF NOT EXISTS shrimp;

DO $$ BEGIN
    CREATE TYPE shrimp.user_role AS ENUM ('admin', 'salesperson', 'farmer');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE shrimp.locale_code AS ENUM ('vi', 'zh-TW');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE shrimp.pond_type AS ENUM ('nursery', 'growout', 'treatment', 'settling', 'other');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE shrimp.cycle_status AS ENUM ('planned', 'active', 'harvested', 'aborted');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE shrimp.cycle_stage AS ENUM ('nursery', 'growout');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE shrimp.severity AS ENUM ('info', 'warn', 'critical');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS shrimp.users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username        text NOT NULL,
    email           text NOT NULL,
    password_hash   text NOT NULL,
    role            shrimp.user_role NOT NULL,
    display_name    text NOT NULL,
    locale          shrimp.locale_code NOT NULL DEFAULT 'vi',
    phone           text,
    telegram_chat_id text,
    telegram_bind_code text,
    telegram_bind_expires_at timestamptz,
    is_active       boolean NOT NULL DEFAULT true,
    token_version   integer NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      uuid REFERENCES shrimp.users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower ON shrimp.users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower ON shrimp.users (lower(email));

CREATE TABLE IF NOT EXISTS shrimp.salesperson_farmers (
    salesperson_id  uuid NOT NULL REFERENCES shrimp.users(id) ON DELETE CASCADE,
    farmer_id       uuid NOT NULL REFERENCES shrimp.users(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (salesperson_id, farmer_id),
    CHECK (salesperson_id <> farmer_id)
);

CREATE TABLE IF NOT EXISTS shrimp.ponds (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    farmer_id       uuid NOT NULL REFERENCES shrimp.users(id),
    code            text NOT NULL,
    name            text NOT NULL,
    pond_type       shrimp.pond_type NOT NULL DEFAULT 'growout',
    area_m2         numeric(12,2),
    depth_m         numeric(8,2),
    volume_m3       numeric(12,2),
    location_text   text,
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ponds_code_lower ON shrimp.ponds (lower(code));
CREATE INDEX IF NOT EXISTS ponds_farmer_id ON shrimp.ponds (farmer_id);

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

CREATE TABLE IF NOT EXISTS shrimp.devices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    serial          text NOT NULL,
    mac_address     text GENERATED ALWAYS AS (shrimp.normalize_device_mac(serial)) STORED,
    pond_id         uuid REFERENCES shrimp.ponds(id),
    name            text,
    is_active       boolean NOT NULL DEFAULT true,
    last_seen_at    timestamptz,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS devices_serial ON shrimp.devices (serial);
DROP TRIGGER IF EXISTS devices_mac_immutable ON shrimp.devices;
CREATE TRIGGER devices_mac_immutable
    BEFORE UPDATE OF serial ON shrimp.devices
    FOR EACH ROW EXECUTE FUNCTION shrimp.prevent_device_mac_change();

CREATE TABLE IF NOT EXISTS shrimp.cycles (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pond_id             uuid NOT NULL REFERENCES shrimp.ponds(id) ON DELETE CASCADE,
    status              shrimp.cycle_status NOT NULL DEFAULT 'active',
    stage               shrimp.cycle_stage NOT NULL DEFAULT 'nursery',
    stocked_at          date,
    stocked_count       integer,
    density_per_m2      numeric(10,2),
    sample_avg_weight_g numeric(10,3),
    species             text NOT NULL DEFAULT 'whiteleg',
    notes               text,
    harvested_at        date,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS cycles_one_active_per_pond
    ON shrimp.cycles (pond_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS cycles_pond_id ON shrimp.cycles (pond_id);

CREATE TABLE IF NOT EXISTS shrimp.probe_readings (
    id                  bigserial PRIMARY KEY,
    device_serial       text NOT NULL,
    device_id           uuid REFERENCES shrimp.devices(id),
    pond_id             uuid REFERENCES shrimp.ponds(id),
    cycle_id            uuid REFERENCES shrimp.cycles(id),
    recorded_at         timestamptz NOT NULL,
    ph                  numeric(8,3),
    ph_mv               numeric(10,3),
    ph_temp_c           numeric(6,2),
    conductivity_us_cm  numeric(14,3),
    salinity_ppt        numeric(8,3),
    cond_temp_c         numeric(6,2),
    tds_mg_l            numeric(14,3),
    do_mg_l             numeric(8,3),
    do_sat_pct          numeric(8,3),
    do_temp_c           numeric(6,2),
    temp_c              numeric(6,2) GENERATED ALWAYS AS (do_temp_c) STORED,
    raw                 jsonb,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    alerts_evaluated_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS probe_readings_device_recorded
    ON shrimp.probe_readings (device_serial, recorded_at);
CREATE INDEX IF NOT EXISTS probe_readings_pond_recorded
    ON shrimp.probe_readings (pond_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS probe_readings_unevaluated
    ON shrimp.probe_readings (ingested_at)
    WHERE alerts_evaluated_at IS NULL;

CREATE TABLE IF NOT EXISTS shrimp.lab_tests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pond_id             uuid NOT NULL REFERENCES shrimp.ponds(id) ON DELETE CASCADE,
    cycle_id            uuid REFERENCES shrimp.cycles(id),
    sampled_at          timestamptz NOT NULL,
    no2_ppm             numeric(10,3),
    nh3_ppm             numeric(10,3),
    alkalinity_ppm      numeric(10,3),
    ca_ppm              numeric(10,3),
    mg_ppm              numeric(10,3),
    k_ppm               numeric(10,3),
    nh3_unionized_ppm   numeric(10,4),
    notes               text,
    recorded_by         uuid REFERENCES shrimp.users(id),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lab_tests_pond_sampled
    ON shrimp.lab_tests (pond_id, sampled_at DESC);

CREATE TABLE IF NOT EXISTS shrimp.nh3_lookup (
    tan_ppm     numeric(10,3) NOT NULL,
    ph          numeric(4,1) NOT NULL,
    nh3_ppm     numeric(10,4) NOT NULL,
    PRIMARY KEY (tan_ppm, ph)
);

CREATE TABLE IF NOT EXISTS shrimp.alert_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,
    metric          text NOT NULL,
    min_value       numeric(12,4),
    max_value       numeric(12,4),
    severity        shrimp.severity NOT NULL DEFAULT 'warn',
    stage           shrimp.cycle_stage,
    is_active       boolean NOT NULL DEFAULT true,
    sort_order      integer NOT NULL DEFAULT 0,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shrimp.alert_events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pond_id             uuid NOT NULL REFERENCES shrimp.ponds(id) ON DELETE CASCADE,
    cycle_id            uuid REFERENCES shrimp.cycles(id),
    rule_code           text NOT NULL,
    severity            shrimp.severity NOT NULL,
    metric              text NOT NULL,
    value               numeric(14,4),
    message_vi          text NOT NULL,
    message_zh          text NOT NULL,
    opened_at           timestamptz NOT NULL DEFAULT now(),
    acknowledged_at     timestamptz,
    acknowledged_by     uuid REFERENCES shrimp.users(id),
    resolved_at         timestamptz,
    last_notified_at    timestamptz,
    notify_count        integer NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS alert_events_open_unique
    ON shrimp.alert_events (pond_id, rule_code) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS alert_events_pond_open
    ON shrimp.alert_events (pond_id, opened_at DESC);

CREATE TABLE IF NOT EXISTS shrimp.notification_log (
    id              bigserial PRIMARY KEY,
    alert_event_id  uuid REFERENCES shrimp.alert_events(id) ON DELETE CASCADE,
    user_id         uuid REFERENCES shrimp.users(id),
    channel         text NOT NULL,
    success         boolean NOT NULL,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Handbook NH3 table (unionized NH3 at given TAN and pH).
INSERT INTO shrimp.nh3_lookup (tan_ppm, ph, nh3_ppm) VALUES
    (0.25, 7.0, 0.00), (0.25, 7.4, 0.00), (0.25, 7.6, 0.01), (0.25, 7.8, 0.01),
    (0.25, 8.0, 0.01), (0.25, 8.2, 0.02), (0.25, 8.4, 0.03), (0.25, 8.6, 0.05), (0.25, 9.0, 0.09),
    (0.50, 7.0, 0.00), (0.50, 7.4, 0.01), (0.50, 7.6, 0.01), (0.50, 7.8, 0.02),
    (0.50, 8.0, 0.03), (0.50, 8.2, 0.04), (0.50, 8.4, 0.06), (0.50, 8.6, 0.09), (0.50, 9.0, 0.18),
    (1.00, 7.0, 0.01), (1.00, 7.4, 0.01), (1.00, 7.6, 0.02), (1.00, 7.8, 0.04),
    (1.00, 8.0, 0.05), (1.00, 8.2, 0.08), (1.00, 8.4, 0.12), (1.00, 8.6, 0.18), (1.00, 9.0, 0.36),
    (2.00, 7.0, 0.01), (2.00, 7.4, 0.03), (2.00, 7.6, 0.04), (2.00, 7.8, 0.07),
    (2.00, 8.0, 0.11), (2.00, 8.2, 0.16), (2.00, 8.4, 0.25), (2.00, 8.6, 0.37), (2.00, 9.0, 0.72),
    (3.00, 7.0, 0.02), (3.00, 7.4, 0.04), (3.00, 7.6, 0.07), (3.00, 7.8, 0.10),
    (3.00, 8.0, 0.16), (3.00, 8.2, 0.25), (3.00, 8.4, 0.37), (3.00, 8.6, 0.55), (3.00, 9.0, 1.08),
    (5.00, 7.0, 0.03), (5.00, 7.4, 0.07), (5.00, 7.6, 0.11), (5.00, 7.8, 0.17),
    (5.00, 8.0, 0.27), (5.00, 8.2, 0.41), (5.00, 8.4, 0.62), (5.00, 8.6, 0.92), (5.00, 9.0, 1.81),
    (10.00, 7.0, 0.06), (10.00, 7.4, 0.14), (10.00, 7.6, 0.22), (10.00, 7.8, 0.35),
    (10.00, 8.0, 0.54), (10.00, 8.2, 0.82), (10.00, 8.4, 1.24), (10.00, 8.6, 1.84), (10.00, 9.0, 3.61)
ON CONFLICT DO NOTHING;

INSERT INTO shrimp.alert_rules (code, metric, min_value, max_value, severity, stage, sort_order) VALUES
    ('PH_LOW', 'ph', 7.6, NULL, 'warn', NULL, 10),
    ('PH_HIGH', 'ph', NULL, 7.8, 'warn', NULL, 11),
    ('DO_LOW', 'do_mg_l', 4.0, NULL, 'warn', NULL, 20),
    ('DO_CRITICAL', 'do_mg_l', 3.0, NULL, 'critical', NULL, 21),
    ('ALK_LOW', 'alkalinity_ppm', 150, NULL, 'warn', NULL, 30),
    ('CA_LOW_NURSERY', 'ca_ppm', 240, NULL, 'warn', 'nursery', 40),
    ('CA_LOW_GROWOUT', 'ca_ppm', 160, NULL, 'warn', 'growout', 41),
    ('CA_LOW_10G', 'ca_ppm', 200, NULL, 'warn', 'growout', 42),
    ('MG_LOW_NURSERY', 'mg_ppm', 550, NULL, 'warn', 'nursery', 50),
    ('MG_LOW_GROWOUT', 'mg_ppm', 400, NULL, 'warn', 'growout', 51),
    ('MG_LOW_10G', 'mg_ppm', 450, NULL, 'warn', 'growout', 52),
    ('NO2_HIGH', 'no2_ppm', NULL, 7, 'warn', NULL, 60),
    ('NO2_HARVEST_EARLY', 'no2_ppm', NULL, 7, 'critical', NULL, 61),
    ('NH3_WARN', 'nh3_unionized_ppm', NULL, 0.05, 'warn', NULL, 70),
    ('NH3_DANGER', 'nh3_unionized_ppm', NULL, 0.10, 'critical', NULL, 71),
    ('DEVICE_STALE', 'heartbeat', NULL, 60, 'warn', NULL, 80)
ON CONFLICT (code) DO NOTHING;

-- A closed cycle without a harvest date is not open-ended.
-- Overlapping ranges belong to the later stocking date, so a shared boundary day is not assigned twice.
CREATE OR REPLACE FUNCTION shrimp.cycle_for_sample(p_pond_id uuid, p_sampled_at timestamptz)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = shrimp, pg_temp
AS $$
DECLARE
    v_day date := (p_sampled_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date;
    v_winner uuid;
    v_stocked date;
    v_ties int;
    v_undated uuid[];
    v_active_undated uuid;
BEGIN
    SELECT id, stocked_at INTO v_winner, v_stocked
    FROM shrimp.cycles
    WHERE pond_id = p_pond_id
      AND status <> 'planned'
      AND stocked_at IS NOT NULL
      AND stocked_at <= v_day
      AND (
            (status = 'active' AND (harvested_at IS NULL OR v_day <= harvested_at))
         OR (status <> 'active' AND harvested_at IS NOT NULL AND v_day <= harvested_at)
      )
    ORDER BY stocked_at DESC, created_at DESC
    LIMIT 1;

    IF v_winner IS NOT NULL THEN
        SELECT count(*) INTO v_ties
        FROM shrimp.cycles
        WHERE pond_id = p_pond_id
          AND status <> 'planned'
          AND stocked_at = v_stocked
          AND stocked_at <= v_day
          AND (
                (status = 'active' AND (harvested_at IS NULL OR v_day <= harvested_at))
             OR (status <> 'active' AND harvested_at IS NOT NULL AND v_day <= harvested_at)
          );
        IF v_ties > 1 THEN
            v_winner := NULL;
        END IF;
    END IF;

    SELECT array_agg(id) INTO v_undated
    FROM shrimp.cycles
    WHERE pond_id = p_pond_id AND status <> 'planned' AND stocked_at IS NULL;

    IF v_winner IS NOT NULL AND v_undated IS NULL THEN
        RETURN v_winner;
    END IF;
    IF v_winner IS NULL AND cardinality(v_undated) = 1
       AND v_day = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date THEN
        SELECT id INTO v_active_undated FROM shrimp.cycles
        WHERE id = v_undated[1] AND status = 'active';
        RETURN v_active_undated;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION shrimp.ingest_probe_reading(
    p_device_serial      text,
    p_recorded_at        timestamptz,
    p_ph                 numeric DEFAULT NULL,
    p_ph_mv              numeric DEFAULT NULL,
    p_ph_temp_c          numeric DEFAULT NULL,
    p_conductivity_us_cm numeric DEFAULT NULL,
    p_salinity_ppt       numeric DEFAULT NULL,
    p_cond_temp_c        numeric DEFAULT NULL,
    p_tds_mg_l           numeric DEFAULT NULL,
    p_do_mg_l            numeric DEFAULT NULL,
    p_do_sat_pct         numeric DEFAULT NULL,
    p_do_temp_c          numeric DEFAULT NULL,
    p_raw                jsonb DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = shrimp, pg_temp
AS $$
DECLARE
    v_device shrimp.devices%ROWTYPE;
    v_cycle_id uuid;
    v_id bigint;
    v_mac text;
BEGIN
    v_mac := shrimp.normalize_device_mac(p_device_serial);
    IF v_mac IS NULL THEN
        RAISE EXCEPTION 'device ID must be a MAC address (12 hex digits)' USING ERRCODE = '22023';
    END IF;
    IF p_recorded_at IS NULL THEN
        RAISE EXCEPTION 'recorded_at is required' USING ERRCODE = '22023';
    END IF;
    IF p_recorded_at > now() + interval '5 minutes' THEN
        RAISE EXCEPTION 'recorded_at is too far in the future' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_device
    FROM shrimp.devices
    WHERE mac_address = v_mac AND is_active = true;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown or inactive device serial: %', p_device_serial USING ERRCODE = '22023';
    END IF;
    IF v_device.pond_id IS NULL THEN
        RAISE EXCEPTION 'device % is not bound to a pond', p_device_serial USING ERRCODE = '22023';
    END IF;

    v_cycle_id := shrimp.cycle_for_sample(v_device.pond_id, p_recorded_at);

    INSERT INTO shrimp.probe_readings (
        device_serial, device_id, pond_id, cycle_id, recorded_at,
        ph, ph_mv, ph_temp_c,
        conductivity_us_cm, salinity_ppt, cond_temp_c, tds_mg_l,
        do_mg_l, do_sat_pct, do_temp_c, raw
    ) VALUES (
        v_mac, v_device.id, v_device.pond_id, v_cycle_id, p_recorded_at,
        p_ph, p_ph_mv, p_ph_temp_c,
        p_conductivity_us_cm, p_salinity_ppt, p_cond_temp_c, p_tds_mg_l,
        p_do_mg_l, p_do_sat_pct, p_do_temp_c, p_raw
    )
    ON CONFLICT (device_id, recorded_at) WHERE device_id IS NOT NULL DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NULL THEN
        SELECT id INTO v_id
        FROM shrimp.probe_readings
        WHERE device_id = v_device.id AND recorded_at = p_recorded_at;
    END IF;

    UPDATE shrimp.devices
    SET last_seen_at = LEAST(p_recorded_at, now()),
        updated_at = now()
    WHERE id = v_device.id
      AND (last_seen_at IS NULL OR p_recorded_at > last_seen_at);

    RETURN v_id;
END;
$$;

ALTER FUNCTION shrimp.ingest_probe_reading(
    text, timestamptz, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, jsonb
) OWNER TO CURRENT_USER;

REVOKE ALL ON FUNCTION shrimp.ingest_probe_reading(
    text, timestamptz, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, jsonb
) FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shrimp_device') THEN
        CREATE ROLE shrimp_device LOGIN;
    END IF;
END $$;

DO $$ BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO shrimp_device', current_database());
END $$;
GRANT USAGE ON SCHEMA shrimp TO shrimp_device;
GRANT EXECUTE ON FUNCTION shrimp.ingest_probe_reading(
    text, timestamptz, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, jsonb
) TO shrimp_device;
