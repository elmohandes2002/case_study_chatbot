# dubizzle Cars AI Assistant

A conversational assistant that helps users explore a car inventory, book viewings, and get recognized when they come back. Built with **FastAPI**, **Streamlit**, **LiteLLM + Gemini**, **SQLite**, **uv**.

---

## Quick start

**Prerequisites:**

1. uv is an all-in-one Python package and project manager. Follow the instructions on the website to install uv based on your machine from here: [uv](https://docs.astral.sh/uv/getting-started/installation/) 

2. Free Gemini API key from here: [Google AI Studio](https://aistudio.google.com/apikey).

```bash
# 1. Clone and install dependencies (uv creates the virtual environment and installs exact locked versions)
git clone <REPO_URL>
cd dubizzle-car-assistant
uv sync

# 2. Add your API key
cp .env.example .env            # Windows PowerShell: Copy-Item .env.example .env
# then open .env and paste your Gemini key
```

Run the backend and the client in **two separate terminals**:

```bash
# Terminal 1 - FastAPI backend (http://localhost:8000, docs at /docs)
uv run uvicorn main:app --reload

# Terminal 2 - Streamlit client (http://localhost:8501)
uv run streamlit run app.py
```

Open http://localhost:8501, enter a name in the sidebar, and start chatting. To see long-term memory, chat for a bit, click **New session**, and say "Hi".

On first start, the backend builds `data/dubizzle.db` from `data/cars.xlsx` and applies the pre-computed enrichment in `data/enrichment.json`, so **no API calls are spent on setup**.

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Your Google AI Studio key (required) |
| `GEMINI_MODEL` | Model used for chat, e.g. `gemini/gemini-3.6-flash` |
| `ENRICH_MODEL` | Model used only by `enrich.py` (optional, defaults to `GEMINI_MODEL`) |

**A note on the Gemini free tier:** model availability and limits change often, and limits can be low (during development I saw 20 requests/day on some models and 5 requests/minute on others). If you get a `404` or `429` error, run `uv run python list_models.py` to see the models your key can use, and switch `GEMINI_MODEL` in `.env`. Each chat turn uses 1-3 requests depending on how many tools the agent calls.

---

## Architecture

```
+--------------+   HTTP (JSON)   +----------------------------------------------+
|  Streamlit   | --------------> |  FastAPI (main.py)                           |
|  (app.py)    | <-------------- |   +-- agent.py  -- LiteLLM --> Gemini        |
|  UI only     |                 |        |  tool-calling loop                  |
+--------------+                 |        +-- tools.py   search, booking, leads |
                                 |        +-- memory.py  sessions, profiles     |
                                 |                 |                            |
                                 |   SQLite (data/dubizzle.db) + leads.csv      |
                                 +----------------------------------------------+
```

| File | Responsibility |
|---|---|
| `main.py` | API layer only: request validation (Pydantic) and routing |
| `agent.py` | System prompt, tool definitions, and the LLM tool-calling loop |
| `tools.py` | Inventory search, car details, viewing availability and booking, lead recording |
| `memory.py` | Session persistence (short-term) and user profiles (long-term) |
| `database.py` | SQLite schema and loading the Excel dataset |
| `enrich.py` | One-time LLM extraction of price, mileage, body type, color, and warranty from descriptions |
| `app.py` | Streamlit chat client; contains no AI or business logic |
| `list_models.py` | Helper that lists Gemini models available to your key |

### API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Send a message (`user_id`, `session_id`, `message`), get the agent's reply |
| `GET` | `/cars` | List inventory |
| `GET` | `/cars/{listing_id}` | Full details of one listing |
| `GET` | `/users/{user_id}/profile` | What the system remembers about a user |
| `GET` | `/sessions/{session_id}/messages` | Full history of a conversation |
| `GET` | `/health` | Health check |

Interactive documentation is available at http://localhost:8000/docs.

---

## Why these choices

**Client: Streamlit.** The goal is a product demo, so a reactive chat UI is closer to what a dubizzle user would actually experience than a notebook, and it makes the returning-user flow easy to show (a name field, a "New session" button, and a sidebar panel displaying what the assistant remembers). Streamlit contains no AI logic; it only renders and forwards messages, so it could be swapped for a mobile app without touching the backend. **Agent framework: LiteLLM with a hand-written tool loop** rather than a heavier framework like LangChain. The agent needs only a few tools and a simple loop, and writing it directly keeps the behavior transparent and easy to control, while LiteLLM keeps the model provider swappable through one line in `.env`. **Retrieval: function calling over SQL** rather than vector RAG or text-to-SQL. Users mostly filter on structured attributes (make, year, price, body type), which SQL handles exactly; a keyword filter over titles and descriptions covers features like "sunroof". With 100 listings, a vector database would add complexity without improving accuracy. Parameterized tool functions are also safer and more predictable than letting the model write raw SQL, and the model can only describe cars that a tool actually returned. **Memory: SQLite**, a single file with no setup, which stores listings, sessions, messages, bookings, leads, and users together.

## Implementation

The core idea is that the LLM never sees the whole inventory and never has to remember anything on its own. Each turn, the backend sends the system prompt, the last 20 messages, and a compact "cars shown so far" register (e.g. `#1 = listing ID 23: 2019 mercedes-benz c-class`), so references like "the first one" resolve to real listing IDs without resending long descriptions. Search results return short summaries; full descriptions are fetched only when the user asks about a specific car. Because the dataset stores price, mileage, and color only inside free text, a one-time enrichment pass (`enrich.py`) had Gemini extract them into nullable columns, with strict rules: values are extracted only if explicitly written, monthly installments are not treated as prices, and implausible values are rejected in code. Results are cached in `enrichment.json` so evaluators never spend quota on it. For long-term memory, a returning user's profile (name, budget, preferences, liked cars, upcoming viewings, and recent requests) is assembled from the leads, bookings, and messages tables and injected into the prompt, costing zero extra LLM calls. Booking rules are enforced in code, not just in the prompt: Sundays, past times, out-of-hours slots, and double bookings are rejected, and the backend supplies `user_id` to booking and lead tools itself, so the model cannot act on another user's behalf.

With more time, I would add: hybrid search with embeddings for fuzzy descriptive queries ("something sporty but practical"); LLM-generated session summaries for richer long-term memory; streaming responses; proper authentication instead of name-based identification; real calendar integration with confirmations by SMS or email; showing listing photos in the chat; an evaluation suite of test conversations to measure grounding and guardrail adherence automatically; and Docker packaging.

---

## Data assumptions and how they were handled

The provided dataset differed from the brief in a few ways. Rather than block on these, I made reasonable assumptions and documented them here.

- **No price or mileage columns.** The brief mentions a Price field, but the dataset only includes year, make, model, trim, title, description, and photo URL. Prices appear inside the text of only some listings. The enrichment pass extracted them where written; after enrichment, [X]/100 listings have a price, [X]/100 a mileage, [X]/100 a color, and [X]/100 a warranty. The agent says "price not listed" rather than guessing, and when a user filters by budget, it tells them how many otherwise-matching cars were excluded for having no listed price.
- **Two sheets with different listings.** "raw dataset" and "cleaned dataset" contain different cars (only one title overlaps). I used the cleaned sheet, since it has listing IDs and HTML already stripped.
- **Inconsistent text.** Some descriptions are in Arabic, some are nearly empty, a quarter of trims are "other", and one model name is stored as a number. Text is normalized on load, and the agent replies in the user's language.
- **Seller contact details in descriptions.** Many listings include phone numbers and external websites. The agent never shares these and offers to book a viewing through dubizzle instead.
- **Viewing slots** are assumed to be 1 hour, starting on the hour from 08:00 to 19:00, in UAE time (UTC+4).

## Lead qualification

Leads are updated as the conversation reveals information and mirrored to `data/leads.csv`:

| Status | Meaning |
|---|---|
| `new` | Some information captured |
| `qualified` | Budget and phone number known |
| `hot` | Booked a viewing |

## Guardrails

The system prompt restricts the agent to cars and dubizzle services, forbids mentioning competitors or inventing services and policies, and requires every car mentioned to come from a tool result. Tool results are the only source of listing facts, and if a detail is missing, the agent says the listing doesn't mention it.

---

## Screenshots

### 1. Multi-turn inventory conversation
<!-- Add screenshot: search -> follow-up about "the first one" -> warranty question -> booking -->

### 2. Returning user recalled in a new session
<!-- Add screenshot: new session, "Hi" -> greeted by name with budget/preferences/viewing recalled, sidebar memory panel open -->
