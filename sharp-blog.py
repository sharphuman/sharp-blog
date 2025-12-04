import requests
import jwt # pip install pyjwt
import datetime
import json
import streamlit as st
from openai import OpenAI

# --- CONFIGURATION ---
# We use st.secrets.get() to safely retrieve keys from .streamlit/secrets.toml
GHOST_ADMIN_API_KEY = st.secrets.get("GHOST_ADMIN_API_KEY")
GHOST_API_URL = st.secrets.get("GHOST_API_URL")
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") 

# Initialize OpenAI (Optional: Only if you are generating text in this script)
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

def create_ghost_token():
    """Generates the short-lived token required to talk to Ghost."""
    try:
        id, secret = GHOST_ADMIN_API_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        header = {'alg': 'HS256', 'typ': 'JWT', 'kid': id}
        payload = {
            'iat': iat,
            'exp': iat + (5 * 60),
            'aud': '/admin/'
        }
        # bytes.fromhex is required for Ghost's secret format
        return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    except Exception as e:
        st.error(f"Error creating token. Check your API Key format. Details: {e}")
        return None

def post_to_ghost(title, html_content, tags=["Growth Systems"]):
    """
    Uploads the HTML blog post to Ghost as a Draft.
    """
    token = create_ghost_token()
    if not token:
        return "Failed to generate auth token."

    headers = {'Authorization': 'Ghost {}'.format(token)}
    
    # Convert 'HTML' to 'Mobiledoc' (Ghost's internal format)
    # We wrap our HTML in a simple Mobiledoc card structure
    mobiledoc = json.dumps({
        "version": "0.3.1",
        "atoms": [],
        "cards": [["html", {"html": html_content}]],
        "markups": [],
        "sections": [[10, 0]]
    })

    body = {
        "posts": [{
            "title": title,
            "mobiledoc": mobiledoc,
            "status": "draft", # Change to 'published' to go live immediately
            "tags": [{"name": t} for t in tags]
        }]
    }

    # Ensure URL is formatted correctly (handles trailing slash issues)
    base_url = GHOST_API_URL.rstrip('/')
    url = f"{base_url}/ghost/api/admin/posts/"
    
    try:
        r = requests.post(url, json=body, headers=headers)
        if r.status_code in [200, 201]:
            # Ghost usually returns 201 for created
            return f"Success! Post created. ID: {r.json()['posts'][0]['id']}"
        else:
            return f"Error {r.status_code}: {r.text}"
    except Exception as e:
        return f"Connection Error: {e}"

# --- EXAMPLE USAGE IN STREAMLIT ---
# st.title("Sharp Blog Publisher")
# topic = "Test Post"
# html_content = "<p>This is a test post from <b>Python</b>.</p>"

# if st.button("Publish to Ghost"):
#     with st.spinner("Publishing..."):
#         result = post_to_ghost(topic, html_content)
#         if "Success" in result:
#             st.success(result)
#         else:
#             st.error(result)
