BEGIN;

-- Closed cycles must have an end date. Prefer the day before the next stocking date.
UPDATE shrimp.cycles c
SET harvested_at = sub.next_start - 1
FROM (
    SELECT c2.id,
           (
               SELECT min(n.stocked_at)
               FROM shrimp.cycles n
               WHERE n.pond_id = c2.pond_id
                 AND n.id <> c2.id
                 AND n.stocked_at IS NOT NULL
                 AND (c2.stocked_at IS NULL OR n.stocked_at > c2.stocked_at)
           ) AS next_start
    FROM shrimp.cycles c2
    WHERE c2.status IN ('harvested', 'aborted')
      AND c2.harvested_at IS NULL
) sub
WHERE c.id = sub.id
  AND sub.next_start IS NOT NULL
  AND (c.stocked_at IS NULL OR sub.next_start - 1 >= c.stocked_at);

UPDATE shrimp.cycles
SET harvested_at = GREATEST(
        COALESCE(stocked_at, (updated_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date),
        (updated_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
    )
WHERE status IN ('harvested', 'aborted')
  AND harvested_at IS NULL;

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

-- Reassign only readings whose cycle is now unambiguous.
WITH assignments AS (
    SELECT id, shrimp.cycle_for_sample(pond_id, recorded_at) AS expected_cycle
    FROM shrimp.probe_readings
)
UPDATE shrimp.probe_readings pr
SET cycle_id = a.expected_cycle,
    alerts_evaluated_at = NULL
FROM assignments a
WHERE pr.id = a.id
  AND a.expected_cycle IS NOT NULL
  AND pr.cycle_id IS DISTINCT FROM a.expected_cycle;

ALTER TABLE shrimp.users
    ADD COLUMN IF NOT EXISTS token_version integer NOT NULL DEFAULT 1;

UPDATE shrimp.users
SET telegram_bind_code = NULL, telegram_bind_expires_at = NULL
WHERE telegram_bind_code IS NOT NULL
  AND id NOT IN (
      SELECT DISTINCT ON (telegram_bind_code) id
      FROM shrimp.users
      WHERE telegram_bind_code IS NOT NULL
      ORDER BY telegram_bind_code, telegram_bind_expires_at DESC NULLS LAST, id
  );

CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_bind_code
    ON shrimp.users (telegram_bind_code)
    WHERE telegram_bind_code IS NOT NULL;

-- Keep device last_seen aligned with sample time, not the moment an old packet is retried.
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

UPDATE shrimp.devices d
SET last_seen_at = sub.latest
FROM (
    SELECT device_id, max(recorded_at) AS latest
    FROM shrimp.probe_readings
    WHERE device_id IS NOT NULL
      AND recorded_at <= now() + interval '5 minutes'
    GROUP BY device_id
) sub
WHERE d.id = sub.device_id
  AND (d.last_seen_at IS NULL OR d.last_seen_at > sub.latest);

COMMIT;
