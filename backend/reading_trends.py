"""Bounded trend samples that retain each metric's extrema and missing-data gaps."""

TREND_FIELDS = ("ph", "ph_mv", "salinity_ppt", "do_mg_l", "temp_c")
TREND_BUCKETS = 100
# Each bucket selects first/last plus min/max for each metric: at most 1,200 rows.
TREND_MAX_POINTS = TREND_BUCKETS * (2 + 2 * len(TREND_FIELDS))


def trend_query(date_filter: str) -> str:
    columns = ", ".join(TREND_FIELDS)
    segments = ",\n".join(
        f"""count(*) FILTER (WHERE {field} IS NULL) OVER timeline
            + sum(CASE WHEN interval_seconds > max_gap THEN 1 ELSE 0 END) OVER timeline
            AS segment_{field}"""
        for field in TREND_FIELDS
    )
    rankings = [
        "row_number() OVER (PARTITION BY bucket ORDER BY recorded_at, id) AS first_point",
        "row_number() OVER (PARTITION BY bucket ORDER BY recorded_at DESC, id DESC) AS last_point",
    ]
    selected = ["first_point = 1", "last_point = 1"]
    for field in TREND_FIELDS:
        for direction, name in (("ASC", "min"), ("DESC", "max")):
            alias = f"{name}_{field}"
            rankings.append(
                f"row_number() OVER (PARTITION BY bucket ORDER BY {field} "
                f"{direction} NULLS LAST, recorded_at, id) AS {alias}"
            )
            selected.append(f"{alias} = 1")
    ranks = ",\n".join(rankings)
    predicate = " OR ".join(selected)
    segment_columns = ", ".join(f"segment_{field}" for field in TREND_FIELDS)
    return f"""
        WITH readings AS MATERIALIZED (
            SELECT id, recorded_at, {columns},
                   extract(epoch FROM recorded_at - lag(recorded_at) OVER (ORDER BY recorded_at, id))
                       AS interval_seconds
            FROM shrimp.probe_readings
            WHERE pond_id = %s {date_filter}
              AND recorded_at <= now() + interval '5 minutes'
        ), bounds AS (
            SELECT min(recorded_at) AS first_time,
                   extract(epoch FROM max(recorded_at) - min(recorded_at)) AS span,
                   1.5 * percentile_cont(0.5) WITHIN GROUP (ORDER BY interval_seconds)
                       FILTER (WHERE interval_seconds > 0) AS max_gap
            FROM readings
        ), bucketed AS (
            SELECT readings.*,
                   least({TREND_BUCKETS - 1}, coalesce(floor(
                       extract(epoch FROM recorded_at - first_time)
                       / nullif(span, 0) * {TREND_BUCKETS}
                   ), 0)) AS bucket,
                   {segments}
            FROM readings CROSS JOIN bounds
            WINDOW timeline AS (ORDER BY recorded_at, id ROWS UNBOUNDED PRECEDING)
        ), ranked AS (
            SELECT *, {ranks}
            FROM bucketed
        )
        SELECT recorded_at, {columns}, {segment_columns}
        FROM ranked
        WHERE {predicate}
        ORDER BY recorded_at, id
    """
