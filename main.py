import os
import json
import io
from typing import Optional
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import openai

# ─── Load environment variables ────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY   = os.getenv("GOOGLE_API_KEY")
ELEVEN_API_KEY   = os.getenv("ELEVEN_API_KEY")
VOICE_ID         = os.getenv("VOICE_ID")

openai.api_key = OPENAI_API_KEY

# ─── App initialization ───────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Load static brewery list ─────────────────────────────────────────────────
with open("cville_breweries.json") as f:
    breweries = json.load(f)

# ─── Brewery endpoint ─────────────────────────────────────────────────────────
@app.get("/breweries")
def get_breweries(name: Optional[str] = None):
    if name:
        return [b for b in breweries if name.lower() in b["name"].lower()]
    return breweries

# ─── Restaurant endpoint ──────────────────────────────────────────────────────
@app.get("/restaurants")
def get_restaurants(meal: Optional[str] = "lunch"):
    # keyword "bar" for beer, else generic "restaurant"
    keyword = "bar" if meal == "beer" else "restaurant"
    # Locust Grove VRBO coords
    lat, lon = "38.0305", "-78.4784"
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius":   1200,
        "keyword":  keyword,
        "key":      GOOGLE_API_KEY
    }
    r = requests.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail="Google Places error")
    return r.json().get("results", [])

# ─── Text-to-Speech endpoint ───────────────────────────────────────────────────
@app.post("/speak")
async def speak(request: Request):
    data = await request.json()
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' field")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept":        "audio/mpeg",
        "Content-Type":  "application/json",
        "xi-api-key":    ELEVEN_API_KEY
    }
    payload = {
        "text":           text,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="TTS error from ElevenLabs")
    return StreamingResponse(io.BytesIO(resp.content), media_type="audio/mpeg")

# ─── Function definitions for LLM ─────────────────────────────────────────────
functions = [
    {
        "name": "get_breweries",
        "description": "List local Charlottesville breweries",
        "parameters": {
            "type":       "object",
            "properties": {
                "name": {"type": "string", "description": "Filter by brewery name"},
            }
        }
    },
    {
        "name": "get_restaurants",
        "description": "List local restaurants or bars",
        "parameters": {
            "type":       "object",
            "properties": {
                "meal": {"type": "string", "enum": ["lunch", "dinner", "beer"]},
            }
        }
    }
]

# ─── Chat endpoint (with function-calling) ────────────────────────────────────
@app.post("/chat")
async def chat(request: Request):
    body    = await request.json()
    user_msg = body.get("message")
    if not user_msg:
        raise HTTPException(status_code=400, detail="Missing 'message' field")

    # 1) Send user + system prompt + function definitions
    messages = [
        {"role": "system", "content": "You're Sam Calgione, a beer-savvy travel assistant with a swagger and sense of humor."},
        {"role": "user",   "content": user_msg}
    ]
    resp = openai.ChatCompletion.create(
        model="gpt-4-0613",
        messages=messages,
        functions=functions,
        function_call="auto"
    )
    msg = resp.choices[0].message

    # 2) If the LLM called a function, execute it server-side
    if msg.get("function_call"):
        fn_name = msg["function_call"]["name"]
        args    = json.loads(msg["function_call"].get("arguments", "{}"))
        if fn_name == "get_breweries":
            result = get_breweries(**args)
        elif fn_name == "get_restaurants":
            result = get_restaurants(**args)
        else:
            result = {}
        # 3) Feed the function result back into the model for a natural-language reply
        messages.append(msg)
        messages.append({"role": "function", "name": fn_name, "content": json.dumps(result)})
        final_resp = openai.ChatCompletion.create(
            model="gpt-4-0613",
            messages=messages
        )
        reply = final_resp.choices[0].message.get("content", "")
    else:
        reply = msg.get("content", "")

    return {"reply": reply}
