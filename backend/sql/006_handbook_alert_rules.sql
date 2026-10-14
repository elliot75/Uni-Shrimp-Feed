BEGIN;

INSERT INTO shrimp.alert_rules (code, metric, min_value, max_value, severity, stage, sort_order)
VALUES
    ('K_LOW', 'k_ppm', 150, NULL, 'warn', NULL, 55),
    ('NH3_OUT_OF_RANGE', 'nh3_unionized_ppm', NULL, NULL, 'warn', NULL, 72)
ON CONFLICT (code) DO NOTHING;

COMMIT;
