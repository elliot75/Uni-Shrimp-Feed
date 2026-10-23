"""Shared, read-only probe selection for lab samples.

Each field uses its newest non-null reading in [sample - 60 min, sample],
within the same pond and stored cycle (including NULL). Ties use the larger
reading id. Do not substitute pH/conductivity temperature for DO temperature.
The SQL is shared by alert evaluation and the batched lab-list query.
"""

_FIELDS = (("ph", "sample_ph"), ("do_temp_c", "sample_temp_c"),
           ("salinity_ppt", "sample_salinity_ppt"))

# All identifiers are fixed application constants, never request data.
SAMPLE_CONDITIONS_JOIN = "\n".join(
    f"""
    LEFT JOIN LATERAL (
        SELECT pr.{field} AS {alias}, pr.recorded_at AS {alias}_recorded_at
        FROM shrimp.probe_readings pr
        WHERE pr.pond_id = lt.pond_id
          AND pr.cycle_id IS NOT DISTINCT FROM lt.cycle_id
          AND pr.recorded_at >= lt.sampled_at - interval '60 minutes'
          AND pr.recorded_at <= lt.sampled_at
          AND pr.recorded_at <= now() + interval '5 minutes'
          AND pr.{field} IS NOT NULL
        ORDER BY pr.recorded_at DESC, pr.id DESC
        LIMIT 1
    ) {alias}_source ON true
    """
    for field, alias in _FIELDS
)
SAMPLE_CONDITIONS_COLUMNS = ", ".join(
    f"{alias}_source.{column}"
    for _, alias in _FIELDS
    for column in (alias, f"{alias}_recorded_at")
)


def load_sample_conditions(conn, pond_id, sampled_at, cycle_id) -> dict:
    """Resolve all three fields in one statement/snapshot; no sample means no match."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SAMPLE_CONDITIONS_COLUMNS}
            FROM (SELECT %s::uuid AS pond_id, %s::timestamptz AS sampled_at,
                         %s::uuid AS cycle_id) lt
            {SAMPLE_CONDITIONS_JOIN}
            """,
            (pond_id, sampled_at, cycle_id),
        )
        return dict(cur.fetchone())
