import csv
from datetime import date as Date, datetime, timedelta, timezone

import database

SUMMARY_COLUMNS = ("listing_id, year, make, model, trim, title, "
                   "price_aed, mileage_km, body_type, color")


def search_cars(
    make: str | None = None,
    model: str | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    body_type: str | None = None,
    color: str | None = None,
    keyword: str | None = None,
    limit: int = 5,
) -> dict:
    conditions, params = [], []

    if make:
        conditions.append("make LIKE ?")
        params.append(f"%{make.strip().lower()}%")
    if model:
        # "rav4" should match "rav 4", "c class" should match "c-class"
        conditions.append("REPLACE(REPLACE(LOWER(model), ' ', ''), '-', '') LIKE ?")
        params.append(f"%{model.lower().replace(' ', '').replace('-', '')}%")
    if min_year:
        conditions.append("year >= ?")
        params.append(int(min_year))
    if max_year:
        conditions.append("year <= ?")
        params.append(int(max_year))
    if body_type:
        conditions.append("LOWER(body_type) = ?")
        params.append(body_type.strip().lower())
    if color:
        conditions.append("LOWER(color) LIKE ?")
        params.append(f"%{color.strip().lower()}%")
    if keyword:
        conditions.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
        params += [f"%{keyword.lower()}%"] * 2

    # Price filters are kept separate so we can report cars with no listed price
    price_conditions, price_params = [], []
    if min_price:
        price_conditions.append("price_aed >= ?")
        price_params.append(int(min_price))
    if max_price:
        price_conditions.append("price_aed <= ?")
        price_params.append(int(max_price))

    base_where = " AND ".join(conditions) if conditions else "1=1"
    where = " AND ".join([base_where] + price_conditions)
    all_params = params + price_params
    limit = max(1, min(int(limit), 10))

    with database.get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM listings WHERE {where}", all_params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT {SUMMARY_COLUMNS} FROM listings WHERE {where} "
            "ORDER BY year DESC LIMIT ?",
            all_params + [limit],
        ).fetchall()
        result = {"total_matches": total, "cars": [dict(r) for r in rows]}

        if price_conditions:
            unpriced = conn.execute(
                f"SELECT COUNT(*) FROM listings WHERE {base_where} AND price_aed IS NULL",
                params,
            ).fetchone()[0]
            if unpriced:
                result["note"] = (
                    f"{unpriced} other cars match the non-price filters but have "
                    "no listed price, so they were excluded."
                )
    return result


def get_car_details(listing_id: int) -> dict:
    listing_id = int(listing_id)
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM listings WHERE listing_id = ?", (listing_id,)
        ).fetchone()
    if row is None:
        return {"error": f"No listing with ID {listing_id}"}
    car = dict(row)
    car.pop("photo_url", None)
    return car


# ---------------------------------------------------------------------------
# Viewing bookings
# ---------------------------------------------------------------------------
UAE_TZ = timezone(timedelta(hours=4))  # UAE has no daylight saving
FIRST_SLOT_HOUR, LAST_SLOT_HOUR = 8, 19  # 1-hour slots: 08:00 ... 19:00 (ends 20:00)
LEADS_CSV = database.DATA_DIR / "leads.csv"


def now_uae() -> datetime:
    return datetime.now(UAE_TZ)


def _listing_title(conn, listing_id: int) -> str | None:
    row = conn.execute(
        "SELECT year, make, model FROM listings WHERE listing_id = ?", (listing_id,)
    ).fetchone()
    return f"{row['year']} {row['make']} {row['model']}" if row else None


def _check_day(day: Date) -> str | None:
    """Return a reason the day can't be booked, or None if it's fine."""
    if day.weekday() == 6:
        return "Viewings are only available Monday to Saturday."
    if day < now_uae().date():
        return "That date is in the past."
    return None


def check_availability(listing_id: int, date: str) -> dict:
    listing_id = int(listing_id)
    try:
        day = Date.fromisoformat(date)
    except ValueError:
        return {"error": "Date must be in YYYY-MM-DD format."}

    with database.get_connection() as conn:
        title = _listing_title(conn, listing_id)
        if title is None:
            return {"error": f"No listing with ID {listing_id}"}
        if reason := _check_day(day):
            return {"listing_id": listing_id, "date": date, "available_slots": [], "reason": reason}
        booked = {
            r["slot_start"][11:16]
            for r in conn.execute(
                "SELECT slot_start FROM bookings WHERE listing_id = ? AND slot_start LIKE ?",
                (listing_id, f"{date}%"),
            )
        }

    now = now_uae()
    slots = [
        f"{h:02d}:00"
        for h in range(FIRST_SLOT_HOUR, LAST_SLOT_HOUR + 1)
        if f"{h:02d}:00" not in booked and (day > now.date() or h > now.hour)
    ]
    return {"listing_id": listing_id, "car": title, "date": date,
            "day": day.strftime("%A"), "available_slots": slots}


def book_viewing(user_id: str, listing_id: int, date: str, time: str,
                 customer_name: str, phone: str) -> dict:
    listing_id = int(listing_id)
    try:
        day = Date.fromisoformat(date)
        hour, minute = (int(x) for x in time.split(":"))
    except ValueError:
        return {"error": "Use date YYYY-MM-DD and time HH:MM."}

    if reason := _check_day(day):
        return {"booked": False, "reason": reason}
    if minute != 0 or not FIRST_SLOT_HOUR <= hour <= LAST_SLOT_HOUR:
        return {"booked": False,
                "reason": "Slots start on the hour between 08:00 and 19:00."}
    if day == now_uae().date() and hour <= now_uae().hour:
        return {"booked": False, "reason": "That time has already passed today."}

    slot = f"{date} {hour:02d}:00"
    with database.get_connection() as conn:
        title = _listing_title(conn, listing_id)
        if title is None:
            return {"error": f"No listing with ID {listing_id}"}
        try:
            cursor = conn.execute(
                """INSERT INTO bookings
                   (user_id, listing_id, slot_start, customer_name, phone, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, listing_id, slot, customer_name, phone, now_uae().isoformat()),
            )
        except database.sqlite3.IntegrityError:
            return {"booked": False, "reason": "That slot was just taken. Please pick another."}
        booking_id = cursor.lastrowid

    save_lead(user_id, name=customer_name, phone=phone,
              interested_listing_ids=[listing_id])
    return {"booked": True, "booking_id": booking_id, "car": title,
            "slot": f"{day.strftime('%A %d %B %Y')}, {hour:02d}:00"}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
LEAD_FIELDS = ["user_id", "name", "phone", "budget_min", "budget_max",
               "preferences", "interested_listings", "status", "updated_at"]


def _lead_status(lead: dict, has_booking: bool) -> str:
    if has_booking:
        return "hot"            # booked a viewing
    if lead.get("budget_max") and lead.get("phone"):
        return "qualified"      # budget + contact details known
    return "new"


def save_lead(user_id: str, name: str | None = None, phone: str | None = None,
              budget_min: int | None = None, budget_max: int | None = None,
              preferences: str | None = None,
              interested_listing_ids: list[int] | None = None) -> dict:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE user_id = ?", (user_id,)).fetchone()
        lead = dict(row) if row else {"user_id": user_id}

        # Only overwrite fields we actually learned something new about
        updates = {"name": name, "phone": phone, "budget_min": budget_min,
                   "budget_max": budget_max, "preferences": preferences}
        for key, value in updates.items():
            if value not in (None, ""):
                lead[key] = int(value) if key.startswith("budget") else value

        interested = {int(x) for x in (lead.get("interested_listings") or "").split(",") if x}
        interested |= {int(x) for x in (interested_listing_ids or [])}
        lead["interested_listings"] = ",".join(str(x) for x in sorted(interested))

        has_booking = conn.execute(
            "SELECT 1 FROM bookings WHERE user_id = ? LIMIT 1", (user_id,)
        ).fetchone() is not None
        lead["status"] = _lead_status(lead, has_booking)
        lead["updated_at"] = now_uae().isoformat(timespec="seconds")

        conn.execute(
            f"INSERT OR REPLACE INTO leads ({', '.join(LEAD_FIELDS)}) "
            f"VALUES ({', '.join(':' + f for f in LEAD_FIELDS)})",
            {f: lead.get(f) for f in LEAD_FIELDS},
        )
        all_leads = [dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY updated_at")]

    # Mirror the leads table to a CSV, as the brief requires
    with open(LEADS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
        writer.writeheader()
        writer.writerows(all_leads)

    return {"saved": True, "status": lead["status"]}
