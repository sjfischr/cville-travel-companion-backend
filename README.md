# Cville Travel Companion — Backend

**One-liner:** MCP-enabled, beer-savvy travel companion for Charlottesville—nicknamed “Sam”—with chat, voice, and live tap-list summaries.

## What this service does
- **/chat** — LLM orchestration (MCP-style). The model can discover and call small “tools” (functions) for breweries, restaurants, and taplist summaries.
- **/breweries** — Curated brewery data for the area (`cville_breweries.json`).
- **/restaurants** — Google Places lookup for lunch/dinner/beer near downtown/VRBO.
- **/speak** — ElevenLabs TTS endpoint; returns MP3 of the assistant’s reply.

> **Why MCP-style?** Each capability is exposed as an independent, self-describing tool that the LLM can invoke. The flow is *discover → invoke → return context* via function-calling.

---

## Quick test

```bash
# All breweries
curl https://cville-travel-companion-backend.onrender.com/breweries

# Filter by name
curl "https://cville-travel-companion-backend.onrender.com/breweries?name=three"

# Lunch ideas
curl "https://cville-travel-companion-backend.onrender.com/restaurants?meal=lunch"

# Ask the assistant
curl -X POST https://cville-travel-companion-backend.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Best first stop for a flight?"}'

# Text-to-speech (saves an MP3)
curl -X POST https://cville-travel-companion-backend.onrender.com/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Welcome to C-ville!"}' --output hello.mp3
```

## Local setup
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
# http://127.0.0.1:8000
```
## Environment
Create .env (or set in your host):
```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-0613
GOOGLE_API_KEY=...
ELEVEN_API_KEY=...
VOICE_ID=...
```

## Deploy (Render)
Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
Env vars: as above.
CORS: currently open; lock down to your Vercel domain once deployed.

```bash
Frontend (Next.js) → /chat → OpenAI (function-calling)
        │                 ↘ calls tools ↙
        ├─ /breweries ──> brewery tool (curated JSON)
        ├─ /restaurants → Google Places tool
        └─ /speak ─────> ElevenLabs TTS (MP3)
```

## Known issues
Tap-list delay (first request): We fetch a brewery’s taplist page and have the LLM extract beers/styles. Reliable, but can be slow on some sites. We’re working on:
- caching summaries for 30–60 minutes,
- headless fetch (Playwright) for dynamic pages,
- detecting embedded JSON feeds (TapHunter/Wix/Squarespace) when present.
- “What’s on tap there?” resolving to many breweries: We now store the last selected brewery in session and call the taplist tool only for that brewery on follow-ups.
- Render “No open ports detected”: Ensure --host 0.0.0.0 --port $PORT.

## Roadmap
- Cache + ETag for taplists
- Playwright fallback
- Optional STT endpoint
- Narrow CORS

# License
MIT
