import json
import sqlite3
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "dubizzle.db"
EXCEL_PATH = DATA_DIR / "cars.xlsx"
ENRICHMENT_PATH = DATA_DIR / "enrichment.json"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                listing_id  INTEGER PRIMARY KEY,
                make        TEXT,
                model       TEXT,
                trim        TEXT,
                year        INTEGER,
                title       TEXT,
                description TEXT,
                photo_url   TEXT,
                price_aed   INTEGER,
                mileage_km  INTEGER,
                body_type   TEXT,
                color       TEXT,
                warranty    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT,
                listing_id    INTEGER,
                slot_start    TEXT,
                customer_name TEXT,
                phone         TEXT,
                created_at    TEXT,
                UNIQUE (listing_id, slot_start)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                user_id             TEXT PRIMARY KEY,
                name                TEXT,
                phone               TEXT,
                budget_min          INTEGER,
                budget_max          INTEGER,
                preferences         TEXT,
                interested_listings TEXT,
                status              TEXT,
                updated_at          TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    TEXT PRIMARY KEY,
                created_at TEXT,
                last_seen  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id    TEXT,
                shown_cars TEXT,
                started_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                user_id    TEXT,
                role       TEXT,
                content    TEXT,
                created_at TEXT
            )
        """)
        count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        if count == 0:
            load_listings(conn)
    apply_enrichment()


def load_listings(conn: sqlite3.Connection) -> None:
    df = pd.read_excel(EXCEL_PATH, sheet_name="cleaned dataset")
    df = df.rename(columns={"Listing_ID": "listing_id"})
    for col in ["make", "model", "trim", "title", "description", "photo_url"]:
        df[col] = df[col].astype(str).str.strip()
    df["year"] = df["year"].astype(int)

    rows = df[["listing_id", "make", "model", "trim", "year",
               "title", "description", "photo_url"]].to_dict("records")
    conn.executemany(
        """INSERT INTO listings
           (listing_id, make, model, trim, year, title, description, photo_url)
           VALUES (:listing_id, :make, :model, :trim, :year,
                   :title, :description, :photo_url)""",
        rows,
    )
    print(f"Loaded {len(rows)} listings into the database.")


def apply_enrichment() -> None:
    """Copy extracted fields from data/enrichment.json into the listings table."""
    if not ENRICHMENT_PATH.exists():
        return
    items = json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))
    with get_connection() as conn:
        conn.executemany(
            """UPDATE listings
               SET price_aed = :price_aed, mileage_km = :mileage_km,
                   body_type = :body_type, color = :color, warranty = :warranty
               WHERE listing_id = :listing_id""",
            items,
        )
