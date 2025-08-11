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
