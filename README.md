# Dubizzle Cars AI Assistant

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

**A note on the Gemini free tier:** model availability and limits change often, and limits can be low (during development I saw 20 requests/day on some models and 5 requests/minute on others). If you get an error regarding the models, run `uv run python list_models.py` to see the models your key can use, and switch `GEMINI_MODEL` in `.env`.

---

## Architecture Choices

**Client: Streamlit**, because a chat UI is closer to the real user experience than a notebook and makes the returning-user flow easy to demonstrate; it holds no AI logic, so it could be replaced without touching the backend. **Agent framework: LiteLLM with a hand-written tool loop** instead of a heavier framework like LangChain, since a few tools and a simple loop are easier to control and debug. **Retrieval: function calling over SQL**, For exact filters like price and year, SQL is precise where vector similarity is not, and at 100 listings, a vector database adds setup and API cost without a real benefit as we are retrieving information from an inventory, and fixed tool functions are safer than model-written SQL. **Memory: SQLite**, a single zero-setup file holding listings, sessions, bookings, leads, and user profiles.

## Implementation

The core idea is that the LLM never sees the whole inventory and never has to remember anything on its own. Each turn, the backend sends the system prompt, the last 20 messages, and a compact "cars shown so far" register (e.g. `#1 = listing ID 23: 2019 mercedes-benz c-class`), so references like "the first one" resolve to real listing IDs without resending long descriptions. Search results return short summaries; full descriptions are fetched only when the user asks about a specific car. Because the dataset stores price, mileage, and color only inside free text, a one-time enrichment pass (`enrich.py`) had Gemini extract them into nullable columns, with strict rules: values are extracted only if explicitly written, monthly installments are not treated as prices, and implausible values are rejected in code. Results are cached in `enrichment.json`, so no need to rerun that file. For long-term memory, a returning user's profile (name, budget, preferences, liked cars, upcoming viewings, and recent requests) is assembled from the leads, bookings, and messages tables and injected into the prompt, costing zero extra LLM calls. Booking rules are enforced in code, not just in the prompt: Sundays, past times, out-of-hours slots, and double bookings are rejected, and the backend supplies `user_id` to booking and lead tools itself, so the model cannot act on another user's behalf.

With more time, I would add: hybrid search with embeddings for some descriptive queries like ("something sporty but practical") match listings by meaning rather than exact keywords; LLM-generated session summaries for richer long-term memory; streaming responses; proper authentication instead of name-based identification; real calendar integration with confirmations by SMS or email; showing listing photos in the chat; an evaluation suite of test conversations to measure grounding and guardrail adherence automatically; and Docker packaging. I would also write down functional requirements as well as create UML diagrams so that engineers can better understand the system requirements and so that I make sure I covered all the functional requirements as per the request from client for example. I would also spend time testing the code to make sure that I have caught all the errors using unit testing. One more thing I would improve is the wait time for the LLM by incorporating techniques such as summarization to reduce token size, and choosing a smaller or faster model and choosing the appropriate model accordingly.

---

## Data assumptions and how they were handled

The provided dataset differed from the PDF in a few ways. I made reasonable assumptions and documented them here.

- **No price or mileage columns.** The PDF mentions a Price field, but the dataset only includes year, make, model, trim, title, description, and photo URL. Prices appear inside the text of only some listings. The enrichment pass extracted them where written; after enrichment, 14/100 listings have a price, 42/100 a mileage, 25/100 a color, and 25/100 a warranty. The agent says "price not listed" rather than guessing if price is not available, and when a user filters by budget, it tells them how many otherwise-matching cars were excluded for having no listed price.
- **Two sheets with different listings.** "raw dataset" and "cleaned dataset" contain different cars (only one title overlaps). I used the cleaned sheet, since it has listing IDs and HTML already stripped.
- **Inconsistent text.** Some descriptions are in Arabic, some are nearly empty, a quarter of trims are "other", and one model name is stored as a number. Text is normalized on load, and the agent replies in the user's language.
- **Seller contact details in descriptions.** Many listings include phone numbers and external websites. The agent never shares these and offers to book a viewing through dubizzle instead.
- **Viewing slots** are assumed to be 1 hour, starting on the hour from 08:00 to 19:00, in UAE time (UTC+4).

## Guardrails

The system prompt restricts the agent to cars and dubizzle services, avoids mentioning competitors or inventing services and policies, and requires every car mentioned to come from a tool result. Tool results are the only source of listing facts, and if a detail is missing, the agent says the listing doesn't mention it.

---

## Screenshots

### 1. Multi-turn inventory conversation

<img width="1599" height="852" alt="Screenshot 2026-09-11 185723" src="https://github.com/user-attachments/assets/09256fd8-64ff-4637-b4ca-07e8e91bf866" />

<img width="1453" height="734" alt="Screenshot 2026-09-11 190855" src="https://github.com/user-attachments/assets/e52d79f3-3913-4b31-81e4-8074a0d9331a" />

<img width="1242" height="642" alt="Screenshot 2026-09-11 190948" src="https://github.com/user-attachments/assets/4b408ee3-3be4-409f-b553-e40ebc790ab9" />

<img width="1214" height="737" alt="Screenshot 2026-09-11 190937" src="https://github.com/user-attachments/assets/a4826a2f-521c-4b07-aa92-739a06d8bed0" />

<img width="1248" height="699" alt="Screenshot 2026-09-11 191044" src="https://github.com/user-attachments/assets/b2c3a873-d8f8-48c3-9007-836e4d36bc45" />

<img width="1365" height="608" alt="Screenshot 2026-09-11 191221" src="https://github.com/user-attachments/assets/fa71febb-7e86-4408-903d-162fcfb753de" />

<img width="1330" height="680" alt="Screenshot 2026-09-11 191417" src="https://github.com/user-attachments/assets/0801af99-a3a1-4f67-aa2b-c79ec5d2343b" />

<img width="1575" height="83" alt="Screenshot 2026-09-11 191607" src="https://github.com/user-attachments/assets/24113dba-c7d0-4d0e-8164-8351f6d9c02e" />


### 2. Returning user recalled in a new session

