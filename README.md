# dubizzle Cars AI Assistant

A conversational assistant that helps users explore a car inventory, book viewings, and get recognized when they come back. Built with **FastAPI**, **Streamlit**, **LiteLLM + Gemini**, **SQLite**, **uv**.

---

## Quick start

**Prerequisites:**

1. uv is an all-in-one Python package and project manager. Follow the instructions on the website to install uv based on your machine from here: [uv](https://docs.astral.sh/uv/getting-started/installation/). 

2. Free Gemini API key from here: [Google AI Studio](https://aistudio.google.com/apikey).

3. Clone and install dependencies (uv creates the virtual environment and installs all necessary packages. the packages we used were: fastapi, uvicorn, streamlit, httpx, litellm, tenacity, pandas, openpyxl, python-dotenv)

```bash
git clone <REPO_URL>
cd dubizzle-car-assistant
uv sync
```

4. Create the .env file (in PowerShell, from the project folder)

Replace your_key_here with your Gemini API key, and the model with any Gemini model available to your key (I used gemini-3.6-flash for testing):

```bash
Set-Content .env "GEMINI_API_KEY=your_key_here"
Add-Content .env "GEMINI_MODEL=gemini/gemini-3.6-flash"
```

Run the backend and the client in **two separate terminals**:

```bash
# Terminal 1 - FastAPI backend (http://localhost:8000, docs at /docs)
uv run uvicorn main:app --reload

# Terminal 2 - Streamlit client (http://localhost:8501)
uv run streamlit run app.py
```

Open http://localhost:8501, enter a name in the sidebar (this can be updated later to a proper sign up system, for now it functions as a username which will be used in another session to retrieve data about the client), and start chatting. To see long-term memory, chat for a bit, click **New session**, or reopen http://localhost:8501 and enter the same username and say "Hi".

On first start, the backend builds `data/dubizzle.db` from `data/cars.xlsx` and applies the pre-computed enrichment in `data/enrichment.json`, so **no API calls are spent on setup**.

**A note on the Gemini free tier:** model availability and limits change often, and limits can be low (during development I saw 20 requests/day on some models and 5 requests/minute on others). If you get an error regarding the models, run `uv run python list_models.py` to see the models your key can use, and switch `GEMINI_MODEL` in `.env`. Each chat turn uses 1-3 requests depending on how many tools the agent calls.

---

## Architecture choices

**Client: Streamlit**, because a chat UI is closer to the real user experience than a notebook and makes the returning-user flow easy to demonstrate; it holds no AI logic, so it could be replaced without touching the backend. **Agent framework: LiteLLM with a hand-written tool loop** instead of a heavier framework like LangChain, since a few tools and a simple loop are easier to control and debug, and LiteLLM keeps the model provider swappable. **Retrieval: function calling over SQL**, because users mostly filter on structured fields like make, year, and price, which SQL matches exactly, while a keyword filter covers descriptive features; a vector database adds little for 100 listings, and fixed tool functions are safer than model-written SQL. **Memory: SQLite**, a single zero-setup file holding listings, sessions, bookings, leads, and user profiles.

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

Leads are updated as the conversation reveals information and mirrored to `data/leads.csv`, one row per user, including any booked viewings (full booking records are kept in the SQLite `bookings` table):

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
