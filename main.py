from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import agent
import database
import memory


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="dubizzle Car Assistant", lifespan=lifespan)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------- Chat ----------------------------
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    user_id = memory.normalize_user_id(request.user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        reply = agent.chat(request.session_id, user_id, request.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    return ChatResponse(reply=reply)


# ---------------------------- Inventory ----------------------------
@app.get("/cars")
def list_cars(limit: int = 20):
    with database.get_connection() as conn:
        rows = conn.execute(
            """SELECT listing_id, year, make, model, trim, title,
                      price_aed, mileage_km, body_type, color
               FROM listings LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/cars/{listing_id}")
def get_car(listing_id: int):
    car = agent.tools.get_car_details(listing_id)
    if "error" in car:
        raise HTTPException(status_code=404, detail=car["error"])
    return car


# ---------------------------- State / memory ----------------------------
@app.get("/users/{user_id}/profile")
def user_profile(user_id: str):
    profile = memory.get_user_profile(memory.normalize_user_id(user_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown user")
    return profile


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    return memory.get_messages(session_id)
