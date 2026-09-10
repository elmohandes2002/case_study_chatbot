import json
import os

from dotenv import load_dotenv
from litellm import completion

import memory
import tools

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini/gemini-3.6-flash")
HISTORY_WINDOW = 20
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are the dubizzle Cars assistant, helping users in the UAE
explore car listings from the dubizzle inventory.

INVENTORY RULES (most important):
- You can only know about cars through your tools. Always call search_cars
  before recommending or listing cars. Never mention a specific car that did
  not come from a tool result in this conversation.
- When the user asks about a specific car (mileage, warranty, features,
  condition, specs), call get_car_details and answer ONLY from what it returns.
  If a detail is not in the listing, say the listing doesn't mention it.
- Price and mileage are only available for some listings. If a value is null,
  say it isn't listed. Never estimate or guess prices.
- If a search returns nothing, say so honestly and suggest relaxing one filter.
- Present results as a short numbered list: year, make, model, and price if
  listed. Show at most 5 cars at a time.
- If the user refers to a car mentioned earlier ("the first one", "that
  Toyota"), use the "Cars shown so far" list below to find its listing ID.
- If a search result includes a "note" about cars with no listed price,
  mention it briefly so the user knows more options may exist.
- Never share seller phone numbers, WhatsApp numbers, emails, or external
  websites from listings. If the user wants to see or ask about a car,
  offer to book a viewing through dubizzle instead.

VIEWINGS AND LEADS:
- Viewings and test drives must be booked in advance. Slots are 1 hour,
  Monday to Saturday, starting on the hour from 08:00 to 19:00 (UAE time).
- Before booking, call check_availability for the car and date, and offer
  only the slots it returns. Resolve words like "tomorrow" or "next Monday"
  using the current date below, and pass dates as YYYY-MM-DD.
- To book you need the user's name and phone number. Ask for whatever is
  missing, then call book_viewing. Never claim a booking succeeded unless
  book_viewing returned booked: true.
- Naturally learn the user's budget and needs (body type, use, seats,
  brands) during the conversation, without interrogating them. Whenever you
  learn something new (budget, preferences, name, phone, a car they like),
  call save_lead with just the new information.

RETURNING USERS:
- If a RETURNING USER block appears below, greet them by name at the start
  of the conversation and briefly mention what they were looking for or
  their upcoming viewing. Use it to personalise suggestions, but let them
  change their mind. Never invent history that isn't in that block.

SCOPE:
- Only discuss cars, car buying, and dubizzle services. Politely decline
  anything else (coding, history, general trivia) and steer back to cars.
- Never mention or recommend other car marketplaces or competitors.
- Do not invent dubizzle services, programs, or policies.
- Some listings are written in Arabic. Reply in the user's language.
- Be friendly and concise.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_cars",
            "description": (
                "Search the dubizzle car inventory. All filters are optional; "
                "combine them as needed. Use 'keyword' for things written in "
                "listing text, e.g. 'sunroof', 'warranty', 'gcc'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "make": {"type": "string", "description": "Brand, e.g. 'toyota', 'mercedes', 'land rover'"},
                    "model": {"type": "string", "description": "Model, e.g. 'camry', 'rav4', 'c-class'"},
                    "min_year": {"type": "integer"},
                    "max_year": {"type": "integer"},
                    "min_price": {"type": "integer", "description": "Minimum price in AED"},
                    "max_price": {"type": "integer", "description": "Maximum price in AED"},
                    "body_type": {
                        "type": "string",
                        "description": "One of: suv, sedan, coupe, hatchback, convertible, pickup, van, wagon",
                    },
                    "color": {"type": "string", "description": "Exterior color, e.g. 'white'"},
                    "keyword": {"type": "string", "description": "Single word or short phrase to find in title/description"},
                    "limit": {"type": "integer", "description": "Max results, default 5"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_car_details",
            "description": "Get the full details and description of one listing by its listing ID.",
            "parameters": {
                "type": "object",
                "properties": {"listing_id": {"type": "integer"}},
                "required": ["listing_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "List free 1-hour viewing slots for a car on a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "listing_id": {"type": "integer"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["listing_id", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_viewing",
            "description": "Book a viewing/test drive slot for a car.",
            "parameters": {
                "type": "object",
                "properties": {
                    "listing_id": {"type": "integer"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:00, e.g. '10:00'"},
                    "customer_name": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["listing_id", "date", "time", "customer_name", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_lead",
            "description": (
                "Record what you've learned about the user as a sales lead. "
                "Only include fields you learned; omitted fields are kept."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "budget_min": {"type": "integer", "description": "AED"},
                    "budget_max": {"type": "integer", "description": "AED"},
                    "preferences": {
                        "type": "string",
                        "description": "Short summary of needs, e.g. '7-seater SUV for family, prefers white'",
                    },
                    "interested_listing_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Listing IDs the user showed interest in",
                    },
                },
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "search_cars": tools.search_cars,
    "get_car_details": tools.get_car_details,
    "check_availability": tools.check_availability,
    "book_viewing": tools.book_viewing,
    "save_lead": tools.save_lead,
}

# Tools that act on behalf of the user. The backend supplies user_id itself,
# so the LLM can never book or save a lead for someone else.
USER_TOOLS = {"book_viewing", "save_lead"}

def _remember_shown(session: dict, result: dict) -> None:
    """Keep an ordered register of every car the user has seen."""
    cars = result.get("cars") or ([result] if "make" in result else [])
    known = {c["listing_id"] for c in session["shown_cars"]}
    for car in cars:
        if car["listing_id"] not in known:
            session["shown_cars"].append({
                "listing_id": car["listing_id"],
                "label": f"{car['year']} {car['make']} {car['model']}",
            })
            known.add(car["listing_id"])


def _build_system_prompt(session: dict, profile_block: str) -> str:
    now = tools.now_uae()
    prompt = SYSTEM_PROMPT + f"\nCurrent date and time (UAE): {now:%A %Y-%m-%d %H:%M}\n"
    if profile_block:
        prompt += "\n" + profile_block + "\n"
    if session["shown_cars"]:
        lines = [
            f"#{i} = listing ID {c['listing_id']}: {c['label']}"
            for i, c in enumerate(session["shown_cars"], start=1)
        ]
        prompt += "\nCars shown so far (in order):\n" + "\n".join(lines)
    return prompt


def _recent_history(history: list[dict]) -> list[dict]:
    window = history[-HISTORY_WINDOW:]
    while window and window[0]["role"] != "user":
        window = window[1:]
    return window


def _run_tool(name: str, args: dict, user_id: str) -> dict:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool {name}"}
    if name in USER_TOOLS:
        args["user_id"] = user_id
    try:
        return func(**args)
    except Exception as e:
        return {"error": str(e)}


def chat(session_id: str, user_id: str, message: str) -> str:
    session = memory.load_session(session_id)
    profile = memory.get_user_profile(user_id, current_session_id=session_id)
    history = session["history"] + [{"role": "user", "content": message}]

    messages = [{"role": "system",
                 "content": _build_system_prompt(session, memory.profile_prompt(profile))}]
    messages += _recent_history(history)

    reply = "Sorry, I had trouble with that. Could you rephrase?"
    for _ in range(MAX_TOOL_ROUNDS):
        response = completion(model=MODEL, messages=messages, tools=TOOLS, num_retries=2)
        msg = response.choices[0].message

        if not msg.tool_calls:
            reply = msg.content or reply
            break

        messages.append(msg)
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = _run_tool(call.function.name, args, user_id)
            _remember_shown(session, result)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": json.dumps(result, default=str),
            })

    memory.save_turn(session_id, user_id, message, reply, session["shown_cars"])
    return reply
