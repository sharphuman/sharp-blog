import requests
import jwt # pip install pyjwt
import datetime
from openai import OpenAI

# --- CONFIGURATION ---
# Add these to your Streamlit Secrets!
GHOST_ADMIN_API_KEY = "6931d3c7fae204000147a888:ce4c605e645bdd4ac6b9aceddb55d048f04dccee68e2c96d45fe4f7157092b27"
GHOST_API_URL = "https://sharphuman.ghost.io"
OPENAI_API_KEY = "sk-proj-..." # Your OpenAI Key

client = OpenAI(api_key=OPENAI_API_KEY)

def create_ghost_token():
    """Generates the short-lived token required to talk to Ghost."""
    id, secret = GHOST_ADMIN_API_KEY.split(':')
    iat = int(datetime.datetime.now().timestamp())
    header = {'alg': 'HS256', 'typ': 'JWT', 'kid': id}
    payload = {
        'iat': iat,
        'exp': iat + (5 * 60),
        'aud': '/admin/'
    }
    return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)

def post_to_ghost(title, html_content, tags=["Growth Systems"]):
    """
    Uploads the HTML blog post to Ghost as a Draft.
    """
    token = create_ghost_token()
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
            "status": "draft", # Set to 'published' to go live instantly
            "tags": [{"name": t} for t in tags]
        }]
    }

    url = f"{GHOST_API_URL}/ghost/api/admin/posts/"
    r = requests.post(url, json=body, headers=headers)
    
    if r.status_code == 201:
        return f"Success! Post created. ID: {r.json()['posts'][0]['id']}"
    else:
        return f"Error: {r.text}"

# --- EXAMPLE USAGE IN STREAMLIT ---
# if st.button("Publish to Ghost"):
#     result = post_to_ghost(topic, html_content)
#     st.success(result)
