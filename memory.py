"""Short-term (per session) and long-term (per user) memory, stored in SQLite."""
import json

import database
import tools


def normalize_user_id(name: str) -> str:
    return " ".join(name.strip().lower().split())


# ---------------------------------------------------------------------------
# Short-term memory: one conversation
# ---------------------------------------------------------------------------
def load_session(session_id: str) -> dict:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY message_id",
            (session_id,),
        ).fetchall()
        session = conn.execute(
            "SELECT shown_cars FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return {
        "history": [dict(r) for r in rows],
        "shown_cars": json.loads(session["shown_cars"]) if session else [],
    }


def save_turn(session_id: str, user_id: str, user_message: str,
              reply: str, shown_cars: list[dict]) -> None:
    now = tools.now_uae().isoformat(timespec="seconds")
    with database.get_connection() as conn:
        conn.execute(
            """INSERT INTO users (user_id, created_at, last_seen) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen""",
            (user_id, now, now),
        )
        conn.execute(
            """INSERT INTO sessions (session_id, user_id, shown_cars, started_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE
               SET shown_cars = excluded.shown_cars, updated_at = excluded.updated_at""",
            (session_id, user_id, json.dumps(shown_cars), now, now),
        )
        conn.executemany(
            """INSERT INTO messages (session_id, user_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            [(session_id, user_id, "user", user_message, now),
             (session_id, user_id, "assistant", reply, now)],
        )


def get_messages(session_id: str) -> list[dict]:
    return load_session(session_id)["history"]


# ---------------------------------------------------------------------------
# Long-term memory: everything we know about a returning user
# ---------------------------------------------------------------------------
def get_user_profile(user_id: str, current_session_id: str | None = None) -> dict | None:
    with database.get_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None:
            return None

        lead = conn.execute("SELECT * FROM leads WHERE user_id = ?", (user_id,)).fetchone()
        lead = dict(lead) if lead else {}

        interested = []
        ids = [int(x) for x in (lead.get("interested_listings") or "").split(",") if x]
        for listing_id in ids:
            row = conn.execute(
                "SELECT listing_id, year, make, model, price_aed FROM listings WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
            if row:
                interested.append(dict(row))

        viewings = [
            dict(r) for r in conn.execute(
                """SELECT b.slot_start, l.listing_id, l.year, l.make, l.model
                   FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
                   WHERE b.user_id = ? AND b.slot_start >= ?
                   ORDER BY b.slot_start""",
                (user_id, tools.now_uae().strftime("%Y-%m-%d %H:%M")),
            )
        ]

        past_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND session_id != ?",
            (user_id, current_session_id or ""),
        ).fetchone()[0]

        recent_requests = [
            r["content"][:150] for r in conn.execute(
                """SELECT content FROM messages
                   WHERE user_id = ? AND role = 'user' AND session_id != ?
                   ORDER BY message_id DESC LIMIT 6""",
                (user_id, current_session_id or ""),
            )
        ][::-1]

    return {
        "user_id": user_id,
        "name": lead.get("name"),
        "last_seen": user["last_seen"],
        "past_sessions": past_sessions,
        "budget_min": lead.get("budget_min"),
        "budget_max": lead.get("budget_max"),
        "preferences": lead.get("preferences"),
        "lead_status": lead.get("status"),
        "interested_cars": interested,
        "upcoming_viewings": viewings,
        "recent_requests": recent_requests,
    }


def profile_prompt(profile: dict | None) -> str:
    """Turn a profile into a compact block for the system prompt."""
    if not profile or not profile["past_sessions"]:
        return ""
    lines = [f"RETURNING USER (from {profile['past_sessions']} previous session(s)):"]
    if profile["name"]:
        lines.append(f"- Name: {profile['name']}")
    if profile["budget_max"] or profile["budget_min"]:
        lines.append(f"- Budget (AED): {profile['budget_min'] or '?'} to {profile['budget_max'] or '?'}")
    if profile["preferences"]:
        lines.append(f"- Preferences: {profile['preferences']}")
    for car in profile["interested_cars"]:
        lines.append(f"- Liked: listing ID {car['listing_id']}, "
                     f"{car['year']} {car['make']} {car['model']}")
    for v in profile["upcoming_viewings"]:
        lines.append(f"- Upcoming viewing: {v['slot_start']} for listing ID "
                     f"{v['listing_id']}, {v['year']} {v['make']} {v['model']}")
    if profile["recent_requests"]:
        lines.append("- Things they asked last time: "
                     + " | ".join(profile["recent_requests"]))
    return "\n".join(lines)
