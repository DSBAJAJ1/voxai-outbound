"""
query_rotator.py
----------------
Selects today's scraping queries from the rotation list in queries.json.
Uses (day_of_year % list_length) so every calendar day picks a deterministic,
different slice from the rotation — no random seed needed, fully reproducible.
"""

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

QUERIES_FILE = Path(__file__).parent / "queries.json"


def _load_queries() -> dict:
    """Load the queries.json rotation list."""
    with open(QUERIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_today_queries(region: str, count: int) -> list[dict]:
    """
    Return today's slice of queries for the given region.

    Args:
        region: "india" or "international"
        count:  How many queries to return (e.g. 30 for India, 20 for international)

    Returns:
        List of { "niche": str, "city": str, "country": str } dicts.

    Strategy:
        - day_of_year determines the starting offset into the list.
        - The list wraps around if (offset + count) exceeds list length.
        - This means every day is different and consecutive days never repeat
          the same leading query (as long as count < list_length).
    """
    data = _load_queries()

    key = "india_queries" if region == "india" else "international_queries"
    full_list = data.get(key, [])

    if not full_list:
        logger.warning("No queries found for region: %s", region)
        return []

    day_offset = date.today().timetuple().tm_yday  # 1-366
    start_idx = day_offset % len(full_list)

    # Wrap-around slice
    if start_idx + count <= len(full_list):
        selected = full_list[start_idx : start_idx + count]
    else:
        # Wrap around the list
        tail = full_list[start_idx:]
        head = full_list[: count - len(tail)]
        selected = tail + head

    logger.info(
        "Region=%s | day_offset=%d | start_idx=%d | queries=%d",
        region,
        day_offset,
        start_idx,
        len(selected),
    )
    return selected


def get_today_india_queries(count: int = 30) -> list[dict]:
    return get_today_queries("india", count)


def get_today_international_queries(count: int = 20) -> list[dict]:
    return get_today_queries("international", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n--- Today's India Queries (30) ---")
    for q in get_today_india_queries(30):
        print(f"  {q['niche']} in {q['city']} ({q['country']})")

    print("\n--- Today's International Queries (20) ---")
    for q in get_today_international_queries(20):
        print(f"  {q['niche']} in {q['city']} ({q['country']})")
