import os
import json
import openai
import requests
from bs4 import BeautifulSoup
import math
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict

# ─── OpenAI Client ──────────────────────────────────────────────────────────────
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
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
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

# ─── Web Scraping for Brewery Details ──────────────────────────────────────────
def scrape_brewery_website(brewery_url):
    """Scrape brewery website for current taps and food info"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(brewery_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for common brewery website patterns
        tap_keywords = ['tap', 'beer', 'on tap', 'current', 'now pouring', 'draft']
        food_keywords = ['food', 'menu', 'kitchen', 'food truck', 'eats']
        
        taps = []
        food_info = []
        
        # Search for tap information
        for keyword in tap_keywords:
            elements = soup.find_all(string=lambda text: text and keyword.lower() in text.lower())
            for element in elements[:5]:  # Limit results
                parent = element.parent if element.parent else element
                if parent and len(str(parent).strip()) > 10:
                    taps.append(str(parent).strip()[:200])
        
        # Search for food information
        for keyword in food_keywords:
            elements = soup.find_all(string=lambda text: text and keyword.lower() in text.lower())
            for element in elements[:3]:  # Limit results
                parent = element.parent if element.parent else element
                if parent and len(str(parent).strip()) > 10:
                    food_info.append(str(parent).strip()[:200])
        
        return {
            "taps": taps[:10],  # Limit to 10 items
            "food": food_info[:5],  # Limit to 5 items
            "scraped": True
        }
    except Exception as e:
        print(f"Scraping error for {brewery_url}: {e}")
        return {"taps": [], "food": [], "scraped": False, "error": str(e)}

# ─── GPT-4 Fallback for Brewery Details ────────────────────────────────────────
def get_brewery_details_from_gpt(brewery_name):
    """Use GPT-4 to get brewery details when scraping fails"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a beer expert. Provide information about breweries including typical beer styles they make and any known food offerings. Keep responses concise."},
                {"role": "user", "content": f"Tell me about {brewery_name} brewery - what types of beers do they typically have on tap and do they serve food?"}
            ],
            max_tokens=300
        )
        return {
            "gpt_info": response.choices[0].message.content,
            "source": "gpt_fallback"
        }
    except Exception as e:
        return {"gpt_info": f"Unable to get information about {brewery_name}", "source": "error"}

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

def get_brewery_details(brewery_name: str):
    """Get detailed information about a specific brewery including current taps and food"""
    local_breweries = load_cville_breweries()
    
    # Find brewery in local data first
    brewery_data = None
    for brewery in local_breweries:
        if brewery_name.lower() in brewery["name"].lower():
            brewery_data = brewery
            break
    
    if not brewery_data:
        return {
            "error": f"Brewery '{brewery_name}' not found in our database",
            "suggestion": "Try asking for a list of breweries first"
        }
    
    # Try to scrape the website
    scrape_results = scrape_brewery_website(brewery_data["brewery_url"])
    
    result = {
        "name": brewery_data["name"],
        "address": brewery_data["address"],
        "website": brewery_data["brewery_url"],
        "untappd": brewery_data["untappd_url"]
    }
    
    if scrape_results["scraped"]:
        result.update({
            "current_taps": scrape_results["taps"],
            "food_info": scrape_results["food"],
            "data_source": "scraped"
        })
    else:
        # Fallback to GPT-4
        gpt_info = get_brewery_details_from_gpt(brewery_data["name"])
        result.update({
            "general_info": gpt_info["gpt_info"],
            "data_source": "gpt_fallback",
            "scrape_error": scrape_results.get("error", "Unknown scraping error")
        })
    
    return result

def get_restaurants(meal: str = None, location: dict = None):
    """List local restaurants or bars near the user's location"""
    restaurants = [
        {"name": "The Local", "meal": "dinner", "rating": 4.8, "url": "https://thelocal-cville.com/", "address": "824 Hinton Ave, Charlottesville, VA"},
        {"name": "Mas Tapas", "meal": "dinner", "rating": 4.7, "url": "https://mastapas.com/", "address": "120 11th St NE, Charlottesville, VA"},
        {"name": "Bodo's Bagels", "meal": "lunch", "rating": 4.9, "url": "https://bodosbagels.com/", "address": "1418 Emmet St N, Charlottesville, VA"},
        {"name": "Citizen Burger Bar", "meal": "lunch", "rating": 4.3, "url": "https://citizenburgerbar.com/", "address": "212 E Main St, Charlottesville, VA"}
    ]
    
    # TODO: Use Google Places API with location data
    # if location:
    #     lat, lng = location.get("lat"), location.get("lng")
    #     # Call Google Places API here
    #     pass
    
    if meal:
        return [r for r in restaurants if r["meal"] == meal]
    return restaurants

# Map function names to actual functions
available_functions = {
    "get_breweries": get_breweries,
    "get_brewery_details": get_brewery_details,
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
            "name": "get_brewery_details",
            "description": "Get detailed information about a specific brewery including current taps and food offerings",
            "parameters": {
                "type": "object",
                "properties": {
                    "brewery_name": {"type": "string", "description": "Name of the brewery to get details for"}
                },
                "required": ["brewery_name"],
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

# ─── Chat endpoint (with tool-calling and location) ────────────────────────────
@app.post("/chat")
async def chat(request: ChatRequest):
    user_msg = request.message
    user_location = request.location
    
    if not user_msg:
        raise HTTPException(status_code=400, detail="Missing 'message' field")

    # Create system prompt that includes location context
    location_context = ""
    if user_location:
        location_context = f" The user is currently at coordinates {user_location['lat']}, {user_location['lng']}."

    messages = [
        {"role": "system", "content": f"You're Sam Calagione, a beer-savvy travel assistant with a swagger and sense of humor.{location_context} When suggesting places, prioritize those near the user's location."},
        {"role": "user", "content": user_msg}
    ]
    
    response = client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    if tool_calls:
        messages.append(response_message)
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_to_call = available_functions[function_name]
            function_args = json.loads(tool_call.function.arguments)
            
            # Only pass location to functions that accept it
            if user_location and function_name in ["get_breweries", "get_restaurants"]:
                function_args["location"] = user_location
                
            function_response = function_to_call(**function_args)
            
            messages.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_response),
                }
            )
        
        final_response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
        )
        reply = final_response.choices[0].message.content
    else:
        reply = response_message.content

    return {"reply": reply}
