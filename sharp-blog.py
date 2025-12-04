import streamlit as st
import requests
import jwt # pip install pyjwt
import datetime
import json
from openai import OpenAI
from anthropic import Anthropic

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V2", page_icon="🎩", layout="wide")

try:
    # Ghost Credentials
    GHOST_ADMIN_KEY = st.secrets["GHOST_ADMIN_API_KEY"]
    GHOST_API_URL = st.secrets["GHOST_API_URL"].rstrip('/')
    
    # AI Credentials
    PPLX_API_KEY = st.secrets["PERPLEXITY_API_KEY"]
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"] # Needed for DALL-E 3
    
except Exception as e:
    st.error(f"Missing Secrets: {e}. Please ensure GHOST_..., PERPLEXITY_..., ANTHROPIC_..., and OPENAI_... keys are in secrets.toml")
    st.stop()

# --- INITIALIZE SPECIALISTS ---

# 1. The Researcher (Perplexity)
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")

# 2. The Writer (Claude)
writer = Anthropic(api_key=ANTHROPIC_API_KEY)

# 3. The Artist (OpenAI DALL-E)
artist = OpenAI(api_key=OPENAI_API_KEY)

# --- CORE FUNCTIONS ---

def create_ghost_token():
    """Generates the secure JWT token for Ghost Admin API."""
    try:
        key_id, secret = GHOST_ADMIN_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        header = {'alg': 'HS256', 'typ': 'JWT', 'kid': key_id}
        payload = {
            'iat': iat,
            'exp': iat + (5 * 60),
            'aud': '/admin/'
        }
        return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    except Exception as e:
        return None

def agent_research(topic):
    """AGENT 1: THE RESEARCHER (Perplexity)"""
    system_prompt = "You are an elite academic researcher. Find detailed, factual information on the given topic. Prioritize accurate data, dates, and technical details."
    
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Research this topic deeply: {topic}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Research Agent Failed: {e}")
        return None

def agent_writer(topic, research_notes, style_sample):
    """AGENT 2: THE WRITER (Claude 3.5 Sonnet) with Style Mimicry"""
    
    # If a sample is provided, we instruct Claude to mimic it.
    style_instruction = ""
    if style_sample:
        style_instruction = f"""
        STYLE MIMICRY INSTRUCTIONS:
        Analyze the following writing sample provided by the user:
        "{style_sample}"
        
        Adopt the sentence structure, vocabulary complexity, humor, and rhythm of this sample. 
        Write the blog post AS IF the author of that sample wrote it.
        """
    else:
        style_instruction = "Use a professional, engaging, and human tone."

    prompt = f"""
    You are a world-class ghostwriter.
    
    TOPIC: {topic}
    
    BASE MATERIAL (RESEARCH):
    {research_notes}
    
    {style_instruction}
    
    OUTPUT FORMAT:
    Return a valid JSON object with these exact keys:
    - "title": (String) A catchy headline.
    - "meta_title": (String) SEO title (under 60 chars).
    - "meta_description": (String) SEO description (under 155 chars).
    - "excerpt": (String) Blog excerpt.
    - "html_content": (String) The full blog post in semantic HTML (h2, h3, p, ul, strong, etc).
    
    Do NOT include markdown formatting like ```json ... ```. Just return the raw JSON string if possible.
    """

    try:
        message = writer.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=4000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        # Clean up if Claude wraps in markdown
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
            
        return json.loads(response_text)
    except Exception as e:
        st.error(f"Writer Agent Failed: {e}")
        return None

def agent_artist(topic):
    """AGENT 3: THE ARTIST (DALL-E 3)"""
    try:
        response = artist.images.generate(
            model="dall-e-3",
            prompt=f"A high-quality, modern editorial illustration about {topic}. Minimalist, tech-forward, 16:9 aspect ratio. No text.",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        return response.data[0].url
    except Exception as e:
        st.warning(f"Image generation failed: {e}")
        return None

def publish_to_ghost(data, image_url, tags):
    """Sends the data to Ghost."""
    token = create_ghost_token()
    headers = {'Authorization': f'Ghost {token}'}
    url = f"{GHOST_API_URL}/ghost/api/admin/posts/?source=html"
    
    body = {
        "posts": [{
            "title": data['title'],
            "custom_excerpt": data['excerpt'],
            "meta_title": data.get('meta_title', data['title']),
            "meta_description": data.get('meta_description', data['excerpt']),
            "html": data['html_content'],
            "feature_image": image_url,
            "status": "draft",
            "tags": [{"name": t} for t in tags] 
        }]
    }

    return requests.post(url, json=body, headers=headers)

# --- UI LAYOUT ---

st.title("🎩 Elite AI Blog Agent V2")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# SIDEBAR CONFIG
with st.sidebar:
    st.header("Configuration")
    st.info("Paste a paragraph of your own writing below. Claude will analyze it to mimic your specific voice.")
    style_sample = st.text_area("Your Writing Style Sample", height=200, placeholder="Paste a previous blog post or email here...")
    
# MAIN INPUT
topic = st.text_input("Enter Topic", placeholder="e.g. The impact of solid state batteries on EVs")

if st.button("Start Elite Workflow", type="primary"):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        
        # 1. RESEARCH
        with st.status("🕵️ Agent 1: Perplexity is researching...", expanded=True) as status:
            research_data = agent_research(topic)
            if research_data:
                st.write("✅ Facts gathered.")
                with st.expander("View Research Data"):
                    st.write(research_data)
            else:
                status.update(label="Research Failed", state="error")
                st.stop()
            
            # 2. WRITING
            status.update(label="✍️ Agent 2: Claude is writing in your style...", state="running")
            blog_post = agent_writer(topic, research_data, style_sample)
            if blog_post:
                st.session_state['elite_blog_v2'] = blog_post
            else:
                status.update(label="Writing Failed", state="error")
                st.stop()
                
            # 3. ART
            status.update(label="🎨 Agent 3: DALL-E is painting...", state="running")
            image_url = agent_artist(topic)
            st.session_state['elite_image_v2'] = image_url
            
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW & PUBLISH
if 'elite_blog_v2' in st.session_state:
    post = st.session_state['elite_blog_v2']
    img_url = st.session_state.get('elite_image_v2', '')
    
    st.divider()
    st.subheader("Review & Publish")
    
    # Image Preview
    col1, col2 = st.columns([1, 2])
    with col1:
        if img_url:
            st.image(img_url, caption="Generated Header", use_container_width=True)
    with col2:
        final_img = st.text_input("Image URL", value=img_url)
        st.info("You can replace this with an Unsplash URL if preferred.")

    # Text Fields
    title = st.text_input("Title", value=post.get('title', ''))
    
    with st.expander("SEO Metadata (Google Search)"):
        meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''))
        meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''))
        
    excerpt = st.text_input("Excerpt", value=post.get('excerpt', ''))
    content = st.text_area("HTML Content", value=post.get('html_content', ''), height=500)
    
    if st.button("🚀 Upload Draft to Ghost"):
        with st.spinner("Uploading to Ghost..."):
            # Update the post object with any edits
            post['title'] = title
            post['excerpt'] = excerpt
            post['meta_title'] = meta_title
            post['meta_description'] = meta_desc
            post['html_content'] = content
            
            result = publish_to_ghost(post, final_img, ["Elite AI", "V2"])
            
            if result.status_code in [200, 201]:
                st.balloons()
                st.success(f"Success! Draft created.")
                st.markdown(f"[Open in Ghost Admin]({GHOST_API_URL}/ghost/#/posts)")
            else:
                st.error(f"Error: {result.text}")
