BEGIN;

-- Preserve invalid input in notes before removing it from numeric columns.
DO $$
DECLARE
    field_name text;
    constraint_name text;
BEGIN
    FOREACH field_name IN ARRAY ARRAY[
        'no2_ppm', 'nh3_ppm', 'alkalinity_ppm', 'ca_ppm', 'mg_ppm', 'k_ppm', 'nh3_unionized_ppm'
    ] LOOP
        EXECUTE format(
            'UPDATE shrimp.lab_tests SET notes = concat_ws(E''\n'', notes, %L || %I::text), %I = NULL
             WHERE %I < 0 OR %I::text IN (''NaN'', ''Infinity'', ''-Infinity'')',
            '[Invalid value removed: ' || field_name || '] ', field_name, field_name,
            field_name, field_name
        );
        constraint_name := 'lab_tests_' || field_name || '_valid';
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conrelid = 'shrimp.lab_tests'::regclass AND conname = constraint_name) THEN
            EXECUTE format(
                'ALTER TABLE shrimp.lab_tests ADD CONSTRAINT %I
                 CHECK (%I >= 0 AND %I::text NOT IN (''NaN'', ''Infinity'', ''-Infinity''))',
                constraint_name, field_name, field_name
            );
        END IF;
    END LOOP;
END $$;

UPDATE shrimp.lab_tests SET nh3_unionized_ppm = NULL
WHERE nh3_ppm IS NULL AND nh3_unionized_ppm IS NOT NULL;

COMMIT;
