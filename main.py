import os
import json
import openai
import requests
import math
import logging
import inspect
import base64
import html2text
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from playwright.async_api import async_playwright

# ─── Logging Configuration ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ─── OpenAI Client ──────────────────────────────────────────────────────────────
client = openai.AsyncOpenAI()

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

# ─── Request Models ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    location: Optional[dict] = None  # {"lat": float, "lng": float}

# ─── Load Local Breweries Data ──────────────────────────────────────────────────
def load_cville_breweries():
    try:
        with open('cville_breweries.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# ─── Distance Calculation ───────────────────────────────────────────────────────
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    R = 3959  # Earth's radius in miles
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ─── Google Places Integration ──────────────────────────────────────────────────
def get_google_places_breweries(lat, lng, radius=10000):
    """Get breweries from Google Places API"""
    api_key = os.getenv("GOOGLE_API_KEY")  # Changed from GOOGLE_PLACES_API_KEY
    if not api_key:
        print("Warning: No Google API key found")
        return []
    
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": "establishment",
        "keyword": "brewery",
        "key": api_key
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if data.get("status") != "OK":
            print(f"Google Places API error: {data.get('status')} - {data.get('error_message', 'Unknown error')}")
            return []
        
        places = []
        for place in data.get("results", []):
            places.append({
                "name": place.get("name"),
                "address": place.get("vicinity"),
                "rating": place.get("rating"),
                "place_id": place.get("place_id"),
                "source": "google_places"
            })
        return places
    except Exception as e:
        print(f"Google Places API error: {e}")
        return []

def get_google_places_restaurants(lat, lng, meal=None, radius=10000):
    """Get restaurants from Google Places API"""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Warning: No Google API key found")
        return []
    
    # Map meal types to Google Places types/keywords
    place_type = "restaurant"
    keyword = ""
    
    if meal == "lunch":
        keyword = "lunch restaurant cafe"
    elif meal == "dinner":
        keyword = "dinner restaurant"
    elif meal == "beer":
        keyword = "bar pub brewery"
        place_type = "bar"
    
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": place_type,
        "key": api_key
    }
    
    if keyword:
        params["keyword"] = keyword
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if data.get("status") != "OK":
            print(f"Google Places API error: {data.get('status')} - {data.get('error_message', 'Unknown error')}")
            return []
        
        places = []
        for place in data.get("results", []):
            places.append({
                "name": place.get("name"),
                "address": place.get("vicinity"),
                "rating": place.get("rating"),
                "price_level": place.get("price_level"),
                "place_id": place.get("place_id"),
                "meal": meal if meal else "general",
                "source": "google_places"
            })
        return places
    except Exception as e:
        print(f"Google Places API error: {e}")
        return []

# ─── Web Scraping for Brewery Details ──────────────────────────────────────────
async def get_taplist_summary(brewery: str, url: str):
    """Fetch and summarize the current beers on tap from a brewery's website using Playwright"""
    logging.info(f"Fetching taplist for {brewery} from {url} using Playwright")
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Navigate to the page and wait for it to be mostly loaded
            await page.goto(url, timeout=20000, wait_until='domcontentloaded')
            
            # Wait for a reasonable time to let dynamic content load
            await page.wait_for_timeout(5000) 
            
            content = await page.content()
            await browser.close()

            # Use BeautifulSoup to parse the dynamically loaded HTML
            soup = BeautifulSoup(content, 'html.parser')
            
            if soup.body:
                text = soup.body.get_text(separator='\n', strip=True)
            else:
                logging.warning("Could not find body in Playwright-rendered page. Falling back to raw text.")
                h = html2text.HTML2Text()
                h.ignore_links = True
                h.ignore_images = True
                text = h.handle(content)

            snippet = "\n".join(text.splitlines()[:400]) # Increased line limit further
            logging.info(f"Extracted text snippet for summarization:\n{snippet[:500]}...")

            # Ask GPT to extract & summarize
            logging.info("Sending snippet to OpenAI for summarization...")
            summary_resp = await client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a beer-savvy assistant. Given the brewery name and page text, extract the beers currently on tap with their style and a brief description. Format as a clear list. If no beer info is found, say so."
                    },
                    {
                        "role": "user", 
                        "content": f"Brewery: {brewery}\n\nPage text:\n{snippet}"
                    }
                ],
                max_tokens=1000 # Increased tokens for potentially longer lists
            )
            summary = summary_resp.choices[0].message.content
            logging.info(f"Received summary from OpenAI: {summary}")
            
            return {
                "brewery": brewery,
                "summary": summary,
                "url": url,
                "status": "success"
            }
            
        except Exception as e:
            logging.error(f"Error fetching taplist for {brewery} with Playwright: {e}", exc_info=True)
            return {
                "brewery": brewery,
                "summary": f"Unable to fetch current tap list for {brewery}. You might want to check their website directly at {url}",
                "url": url,
                "status": "error",
                "error": str(e)
            }

# ─── Business Logic Functions ───────────────────────────────────────────────────
def get_breweries(name: str = None, location: dict = None):
    """List breweries using local JSON + Google Places"""
    local_breweries = load_cville_breweries()
    
    # If location provided, get Google Places results and filter local breweries
    if location:
        lat, lng = location.get("lat"), location.get("lng")
        
        # Get Google Places breweries
        google_breweries = get_google_places_breweries(lat, lng)
        
        # Add distance to local breweries using actual user location
        for brewery in local_breweries:
            # For now, calculate distance from user's location to Charlottesville center
            # TODO: Add actual coordinates to each brewery in JSON for precise distances
            cville_center = (38.0293, -78.4767)  # Approximate center of Charlottesville
            brewery["distance"] = haversine_distance(lat, lng, cville_center[0], cville_center[1])
        
        # Sort local breweries by distance
        local_breweries.sort(key=lambda x: x.get("distance", 999))
        
        # Combine and deduplicate
        all_breweries = local_breweries + google_breweries
    else:
        all_breweries = local_breweries
    
    # Filter by name if provided
    if name:
        all_breweries = [b for b in all_breweries if name.lower() in b["name"].lower()]
    
    return all_breweries[:15]  # Limit results

def get_restaurants(meal: str = None, location: dict = None):
    """List local restaurants or bars near the user's location"""
    if location:
        lat, lng = location.get("lat"), location.get("lng")
        restaurants = get_google_places_restaurants(lat, lng, meal)
        
        # Add distance to each restaurant
        for restaurant in restaurants:
            # For Google Places results, we don't have exact coordinates
            # but we can use the general location for sorting
            restaurant["distance"] = 0.5  # Placeholder - actual distance would need geocoding
        
        return restaurants[:15]  # Limit results
    else:
        # Fallback for when no location is provided
        return [{
            "name": "No location provided",
            "address": "Please enable location services to find nearby restaurants",
            "rating": 0,
            "meal": meal if meal else "general",
            "source": "error"
        }]

# Remove the old get_brewery_details function and replace available_functions
available_functions = {
    "get_breweries": get_breweries,
    "get_taplist_summary": get_taplist_summary,
    "get_restaurants": get_restaurants,
}

# Updated tools definition
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_breweries",
            "description": "List breweries near the user's location using local data and Google Places",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Filter by brewery name"},
                    "location": {"type": "object", "description": "User's current location with lat/lng"}
                },
                "required": [],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_taplist_summary",
            "description": "Fetch and summarize the current beers on tap from a brewery's website",
            "parameters": {
                "type": "object",
                "properties": {
                    "brewery": {"type": "string", "description": "Brewery name"},
                    "url": {"type": "string", "description": "Tap list page URL"}
                },
                "required": ["brewery", "url"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_restaurants",
            "description": "List local restaurants or bars near the user's location",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal": {"type": "string", "enum": ["lunch", "dinner", "beer"]},
                    "location": {"type": "object", "description": "User's current location with lat/lng"}
                },
                "required": [],
            }
        }
    }
]

# ─── Session Storage (for demo purposes) ───────────────────────────────────────
# In a real application, use a more robust session management solution.
session_storage = {}

# ─── Chat endpoint (with tool-calling and location) ────────────────────────────
@app.post("/chat")
async def chat(request: ChatRequest):
    logging.info(f"Received chat request: {request.message}")
    user_msg = request.message
    user_location = request.location
    
    # Use a fixed session ID for this demo
    session_id = "default_user" 
    if session_id not in session_storage:
        session_storage[session_id] = {}
    session = session_storage[session_id]

    if not user_msg:
        logging.error("Missing 'message' field in request")
        raise HTTPException(status_code=400, detail="Missing 'message' field")

    # Create system prompt that includes location and session context
    location_context = ""
    if user_location:
        location_context = f" The user is currently at coordinates {user_location['lat']}, {user_location['lng']}."
        logging.info(f"User location provided: {user_location}")
    
    session_context = ""
    if "last_brewery" in session:
        last_brewery_name = session['last_brewery']['name']
        session_context = f" The user was just asking about {last_brewery_name}. When they say 'there', 'that place', or ask about the taplist, they are likely referring to {last_brewery_name}."

    messages = [
        {"role": "system", "content": f"You're Sam Calagione, a beer-savvy travel assistant with a swagger and sense of humor.{location_context}{session_context} When suggesting places, prioritize those near the user's location. When users ask about what's on tap at a specific brewery, use the get_taplist_summary function with the brewery's taplist_url from your knowledge."},
        {"role": "user", "content": user_msg}
    ]
    
    logging.info("Sending initial request to OpenAI...")
    response = await client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    response_message = response.choices[0].message
    
    # Loop to handle chained tool calls
    while response_message.tool_calls:
        logging.info("OpenAI response contains tool calls. Executing them...")
        messages.append(response_message)
        tool_calls = response_message.tool_calls
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            logging.info(f"Executing tool: {function_name} with args: {function_args}")
            
            function_to_call = available_functions[function_name]
            
            if user_location and function_name in ["get_breweries", "get_restaurants"]:
                function_args["location"] = user_location
            
            # Check if the function is async and await it if so
            if inspect.iscoroutinefunction(function_to_call):
                function_response = await function_to_call(**function_args)
            else:
                function_response = function_to_call(**function_args)

            logging.info(f"Received response from tool {function_name}")

            # Requirement 1: Store the last mentioned brewery
            if function_name == "get_breweries" and function_response:
                # The first result is the most relevant one
                relevant_brewery = function_response[0]
                if "taplist_url" in relevant_brewery and relevant_brewery["taplist_url"]:
                    session["last_brewery"] = {
                        "name": relevant_brewery["name"],
                        "url": relevant_brewery["taplist_url"]
                    }
                    logging.info(f"Stored last brewery in session: {session['last_brewery']['name']}")
            
            messages.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_response),
                }
            )
        
        logging.info("Sending follow-up request to OpenAI with tool responses...")
        response = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message

    reply = response_message.content
    logging.info(f"Final reply: {reply}")

    return {"reply": reply}
