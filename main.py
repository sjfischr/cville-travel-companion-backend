import os
import json
import openai
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── OpenAI Client ──────────────────────────────────────────────────────────────
# Use the OPENAI_API_KEY environment variable
client = openai.OpenAI()

# ─── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI()
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://cycling-trip-companion-frontend.onrender.com"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Business Logic (Function Calling) ──────────────────────────────────────────
def get_breweries(name: str = None):
    """List local Charlottesville breweries"""
    breweries = [
        {"name": "Starr Hill", "rating": 4.5, "url": "https://starrhill.com/"},
        {"name": "Three Notch'd", "rating": 4.0, "url": "https://threenotchdbrewing.com/"},
        {"name": "Champion", "rating": 4.2, "url": "https://championbrewingcompany.com/"}
    ]
    if name:
        return [b for b in breweries if name.lower() in b["name"].lower()]
    return breweries

def get_restaurants(meal: str = None):
    """List local restaurants or bars"""
    restaurants = [
        {"name": "The Local", "meal": "dinner", "rating": 4.8, "url": "https://thelocal-cville.com/"},
        {"name": "Mas Tapas", "meal": "dinner", "rating": 4.7, "url": "https://mastapas.com/"},
        {"name": "Bodo's Bagels", "meal": "lunch", "rating": 4.9, "url": "https://bodosbagels.com/"}
    ]
    if meal:
        return [r for r in restaurants if r["meal"] == meal]
    return restaurants

# Map function names to actual functions
available_functions = {
    "get_breweries": get_breweries,
    "get_restaurants": get_restaurants,
}

# Describe the functions for the model
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_breweries",
            "description": "List local Charlottesville breweries",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Filter by brewery name"},
                },
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_restaurants",
            "description": "List local restaurants or bars",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal": {"type": "string", "enum": ["lunch", "dinner", "beer"]},
                },
                "required": [],
            }
        }
    }
]

# ─── Chat endpoint (with tool-calling) ────────────────────────────────────
@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_msg = body.get("message")
    if not user_msg:
        raise HTTPException(status_code=400, detail="Missing 'message' field")

    # 1) Send user + system prompt + tool definitions
    messages = [
        {"role": "system", "content": "You're Sam Calagione, a beer-savvy travel assistant with a swagger and sense of humor."},
        {"role": "user", "content": user_msg}
    ]
    
    response = client.chat.completions.create(
        model="gpt-4-1106-preview", # Or another model that supports tool calling
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # 2) If the LLM called a tool, execute it server-side
    if tool_calls:
        messages.append(response_message)  # Extend conversation with assistant's reply
        # Execute all tool calls
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_to_call = available_functions[function_name]
            function_args = json.loads(tool_call.function.arguments)
            function_response = function_to_call(**function_args)
            
            messages.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_response),
                }
            )
        
        # 3) Feed the tool result back into the model for a natural-language reply
        final_response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
        )
        reply = final_response.choices[0].message.content
    else:
        reply = response_message.content

    return {"reply": reply}
