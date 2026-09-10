"""One-time enrichment: extract structured fields from listing descriptions.

Run with:  uv run python enrich.py
Results are saved to data/enrichment.json so this never needs to run again,
and database.py applies that file automatically when building the database.
"""
import json
import os
import time

from dotenv import load_dotenv
import litellm
from litellm import completion

import database

load_dotenv()

MODEL = os.getenv("ENRICH_MODEL") or os.getenv("GEMINI_MODEL", "gemini/gemini-3.6-flash")
BATCH_SIZE = 20
ENRICHMENT_PATH = database.ENRICHMENT_PATH
BODY_TYPES = {"suv", "sedan", "coupe", "hatchback", "convertible",
              "pickup", "van", "wagon", "other"}

PROMPT = """You extract structured data from UAE used-car listings.
For each listing, return these fields:

- price_aed: the full selling price in AED as an integer, ONLY if it is
  explicitly written in the title or description. Monthly installments or
  down payments are NOT the price. If only installments are given, use null.
  Never guess.
- mileage_km: integer kilometers ONLY if explicitly written, else null.
  "0KM" or "brand new" means 0.
- body_type: one of suv, sedan, coupe, hatchback, convertible, pickup, van,
  wagon, other. You may use your knowledge of the make and model here.
- color: exterior color ONLY if written, as a simple lowercase word
  (e.g. "white", "black"), else null.
- warranty: short text summary of any warranty mentioned
  (e.g. "Agency warranty until 2028"), else null.

Listings may be in Arabic. Respond with ONLY a JSON object of the form:
{"listings": [{"listing_id": 1, "price_aed": null, "mileage_km": 35711,
"body_type": "coupe", "color": "silver", "warranty": null}, ...]}

Listings:
"""


def _to_int(value, low, high):
    try:
        number = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _clean(item: dict) -> dict:
    body = str(item.get("body_type") or "other").strip().lower()
    color = item.get("color")
    return {
        "listing_id": int(item["listing_id"]),
        "price_aed": _to_int(item.get("price_aed"), 5_000, 100_000_000),
        "mileage_km": _to_int(item.get("mileage_km"), 0, 1_000_000),
        "body_type": body if body in BODY_TYPES else "other",
        "color": str(color).strip().lower() if color else None,
        "warranty": item.get("warranty") or None,
    }


def _extract_batch(rows) -> list[dict]:
    payload = [
        {
            "listing_id": r["listing_id"],
            "year": r["year"], "make": r["make"], "model": r["model"],
            "title": r["title"],
            "description": r["description"][:1500],
        }
        for r in rows
    ]
    response = completion(
        model=MODEL,
        messages=[{"role": "user",
                   "content": PROMPT + json.dumps(payload, ensure_ascii=False)}],
        response_format={"type": "json_object"},
        num_retries=3,
    )
    text = response.choices[0].message.content
    text = text.replace("```json", "").replace("```", "").strip()
    return [_clean(item) for item in json.loads(text)["listings"]]


def enrich_listings() -> None:
    results = {}
    if ENRICHMENT_PATH.exists():
        results = {r["listing_id"]: r for r in json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))}

    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT listing_id, year, make, model, title, description FROM listings"
        ).fetchall()
    todo = [r for r in rows if r["listing_id"] not in results]
    print(f"{len(todo)} listings to enrich.")

    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        try:
            for item in _extract_batch(batch):
                results[item["listing_id"]] = item
        except litellm.RateLimitError:
            print("Quota exhausted. Progress saved; rerun later or switch ENRICH_MODEL.")
            break
        except Exception as e:
            print(f"Batch starting at {start} failed: {e}. Rerun to retry.")
            continue
        # Save after every batch so progress survives a crash or rate limit
        ENRICHMENT_PATH.write_text(
            json.dumps(list(results.values()), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Enriched {len(results)}/{len(rows)}")
        time.sleep(5)  # stay under free-tier rate limits

    database.apply_enrichment()
    print("Done.")


if __name__ == "__main__":
    database.init_db()
    enrich_listings()