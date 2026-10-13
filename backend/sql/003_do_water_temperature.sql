-- The DO probe is the sole source of the pond water temperature.
-- Generated values also cover historical readings without changing raw data.
BEGIN;

ALTER TABLE shrimp.probe_readings
    ADD COLUMN IF NOT EXISTS temp_c numeric(6,2)
    GENERATED ALWAYS AS (do_temp_c) STORED;

COMMENT ON COLUMN shrimp.probe_readings.temp_c IS
    'Pond water temperature in Celsius, sourced exclusively from do_temp_c; NULL when DO temperature is unavailable.';

COMMIT;
