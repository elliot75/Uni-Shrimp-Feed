from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

RANGE_HOURS = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24}


def reading_range(mode: str, start_date: date | None, end_date: date | None) -> tuple[str, tuple]:
    if mode == "all":
        return "", ()
    if mode == "custom":
        if start_date is None or end_date is None or start_date > end_date:
            raise HTTPException(status_code=422, detail="Select a valid start and end date")
        # Include the entire end date in Vietnam, without rounding reading timestamps.
        return (
            """AND recorded_at >= (%s::timestamp AT TIME ZONE 'Asia/Ho_Chi_Minh')
               AND recorded_at < ((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Ho_Chi_Minh')""",
            (start_date, end_date),
        )
    since = datetime.now(timezone.utc) - timedelta(hours=RANGE_HOURS.get(mode, 24))
    return "AND recorded_at >= %s", (since,)
