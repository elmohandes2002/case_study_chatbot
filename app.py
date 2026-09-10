import uuid

import httpx
import streamlit as st

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="dubizzle Car Assistant", page_icon="🚗")
st.title("dubizzle Car Assistant")


def new_session():
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []


# ---------------- Sidebar: who is chatting ----------------
name = st.sidebar.text_input("Your name", placeholder="e.g. Mohamed")
user_id = " ".join(name.strip().lower().split())

if "session_id" not in st.session_state:
    new_session()

# A different user means a different conversation
if st.session_state.get("user_id") != user_id:
    st.session_state.user_id = user_id
    new_session()

if st.sidebar.button("New session"):
    new_session()

if not user_id:
    st.info("Enter your name in the sidebar to start chatting.")
    st.stop()

# Show what the backend remembers about this user (useful for the demo)
profile = httpx.get(f"{BACKEND_URL}/users/{user_id}/profile", timeout=10)
with st.sidebar.expander("What the assistant remembers"):
    if profile.status_code == 200:
        st.json(profile.json())
    else:
        st.write("Nothing yet — this is a new user.")

# ---------------- Chat ----------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("Ask about cars..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.spinner("Thinking..."):
        response = httpx.post(
            f"{BACKEND_URL}/chat",
            json={"user_id": user_id,
                  "session_id": st.session_state.session_id,
                  "message": prompt},
            timeout=120,
        )
    if response.status_code == 200:
        reply = response.json()["reply"]
    else:
        reply = f"Error: {response.json().get('detail', 'unknown error')}"

    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.write(reply)
    st.rerun()
