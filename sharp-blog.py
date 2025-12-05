import streamlit as st
import streamlit.components.v1 as components
import requests
import jwt
import datetime
import json
import io
import urllib.parse
import pandas as pd
from anthropic import Anthropic
from pypdf import PdfReader
from docx import Document
from openai import OpenAI
import os

# --- SAFE IMPORT FOR TEXTSTAT ---
try:
    import textstat
    textstat_installed = True
except ImportError:
    textstat_installed = False

# --- CONFIGURATION & NEON THEME ---
st.set_page_config(page_title="Elite AI Blog Agent V12", page_icon="🧠", layout="wide")

# Custom CSS for "Sharp Human" Neon/Black Theme
st.markdown("""
<style>
    /* MAIN BACKGROUND - Deep Black/Grey */
    .stApp {
        background-color: #0e1117;
        color: #e0e0e0;
    }
    
    /* INPUTS - Dark Grey with Neon Border focus */
    .stTextArea textarea, .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1c1c1c !important;
        color: #00e5ff !important; /* Neon Cyan Text */
        border: 1px solid #333 !important;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #d500f9 !important; /* Neon Purple Focus */
    }

    /* HEADERS - Neon Gradient effect text */
    h1, h2, h3 {
        background: -webkit-linear-gradient(45deg, #00e5ff, #d500f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-family: 'Helvetica Neue', sans-serif !important;
        letter-spacing: -0.5px;
    }

    /* FILE UPLOADER - Square & Centered */
    div[data-testid="stFileUploader"] section {
        background-color: #161b22;
        border: 2px dashed #00e5ff; /* Neon Cyan Dashes */
        border-radius: 15px;
        min-height: 200px; /* Make it square-ish */
        display: flex;
        align-items: center;
        justify-content: center;
    }
    div[data-testid="stFileUploader"] section:hover {
        border-color: #d500f9; /* Purple on hover */
    }

    /* BUTTONS - Neon Gradient */
    .stButton button {
        background: linear-gradient(45deg, #212121, #000);
        border: 1px solid #00e5ff;
        color: #00e5ff;
        border-radius: 4px;
        font-weight: 600;
        transition: all 0.3s;
    }
    .stButton button:hover {
        border-color: #d500f9;
        color: #d500f9;
        box-shadow: 0 0 10px #d500f9;
    }
    
    /* CUSTOM IMAGE PROMPT BOX */
    .custom-img-prompt {
        border: 1px solid #00ff00; /* Lime Green */
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE & COST TRACKING ---
if 'log_events' not in st.session_state: st.session_state.log_events = []
if 'current_workflow_status' not in st.session_state: st.session_state.current_workflow_status = "Ready."
if 'costs' not in st.session_state: st.session_state.costs = {"Anthropic (Claude)": 0.0, "OpenAI (DALL-E/Whisper)": 0.0, "Perplexity (Research)": 0.0}
if 'elite_blog_v8' not in st.session_state: st.session_state.elite_blog_v8 = None
if 'transcript_context' not in st.session_state: st.session_state.transcript_context = False
if 'final_title' not in st.session_state: st.session_state.final_title = ""
if 'final_content' not in st.session_state: st.session_state.final_content = ""
if 'final_excerpt' not in st.session_state: st.session_state.final_excerpt = ""
if 'seo_keywords' not in st.session_state: st.session_state.seo_keywords = ""
if 'last_claude_model' not in st.session_state: st.session_state.last_claude_model = "claude-sonnet-4-20250514"

# --- SECRETS ---
try:
    GHOST_ADMIN_KEY = st.secrets.get("GHOST_ADMIN_API_KEY") or os.environ["GHOST_ADMIN_API_KEY"]
    GHOST_API_URL = (st.secrets.get("GHOST_API_URL") or os.environ["GHOST_API_URL"]).rstrip('/')
    PPLX_API_KEY = st.secrets.get("PERPLEXITY_API_KEY") or os.environ["PERPLEXITY_API_KEY"]
    ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"]
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"]
except KeyError as e:
    st.error(f"❌ Missing Secret: {e}. Please set all keys.")
    st.stop()

def add_log(message):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    st.session_state.log_events.insert(0, f"[{timestamp}] {message}")

def track_cost(provider, amount):
    st.session_state.costs[provider] += amount

# --- CLIENTS (Cached for Speed) ---
@st.cache_resource
def get_clients():
    pplx = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
    anth = Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        oai = OpenAI(api_key=OPENAI_API_KEY)
    except:
        oai = None
    return pplx, anth, oai

researcher, writer, openai_client = get_clients()
openai_client_is_valid = openai_client is not None

# --- HELPERS ---
def extract_text(file):
    try:
        if file.name.endswith('.pdf'):
            reader = PdfReader(file)
            return "\n".join([p.extract_text() for p in reader.pages])
        elif file.name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        elif file.name.endswith('.txt') or file.name.endswith('.md'):
            return file.read().decode("utf-8")
        return ""
    except: return "Error reading file."

def transcribe_audio(file):
    if not openai_client_is_valid: return "OpenAI Key Missing."
    try:
        # Cost: $0.006 / minute
        transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=file)
        track_cost("OpenAI (DALL-E/Whisper)", 0.06) # Est $0.06 for a 10 min file avg
        return transcript.text
    except Exception as e:
        if "413" in str(e): return "Error: File >25MB (OpenAI Limit)."
        return f"Error: {e}"

def generate_social_link(text, platform):
    if platform == "twitter":
        safe = urllib.parse.quote(text[:2500]) 
        return f"https://twitter.com/intent/tweet?text={safe}"
    elif platform == "linkedin":
        safe = urllib.parse.quote(text[:2000])
        return f"https://www.linkedin.com/feed/?shareActive=true&text={safe}"
    elif platform == "reddit":
        safe = urllib.parse.quote(text[:3000])
        return f"https://www.reddit.com/submit?selftext=true&title=New%20Post&text={safe}"
    return "#"

# --- AGENTS ---

def agent_seo(topic):
    add_log("SEO Agent: Thinking...")
    try:
        # Sonar Cost: ~$0.005 per request
        res = researcher.chat.completions.create(
            model="sonar", 
            messages=[{"role": "user", "content": f"Suggest 5-7 high-impact SEO keywords for: {topic}. Comma separated. List only."}]
        )
        track_cost("Perplexity (Research)", 0.005)
        return res.choices[0].message.content
    except Exception as e:
        add_log(f"SEO Failed: {e}")
        return ""

def agent_research(topic, context):
    add_log("Agent 1: Researching...")
    sys_prompt = "You are a Fact-Checking Researcher." if context else "You are an elite academic researcher."
    try:
        # Sonar Pro Cost: ~$0.02 per request (higher tier)
        res = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Research: {topic}"}]
        )
        track_cost("Perplexity (Research)", 0.02)
        return res.choices[0].message.content
    except Exception as e:
        return None

def agent_writer(topic, research, style, tone, keywords, audience, context_txt, model):
    add_log(f"Agent 2 (Claude): Writing...")
    
    prompt = f"""
    Write a blog post.
    TOPIC: "{topic}"
    AUDIENCE: {audience}
    TONE: {tone}. {f"MIMIC STYLE: {style}" if style else ""}
    KEYWORDS: {keywords}
    RESEARCH: {research}
    CONTEXT: {context_txt[:30000] if context_txt else "None"}

    *** PRIVACY PROTOCOL ***
    - **NEVER use real names** from the transcript/context.
    - Generalize anecdotes (e.g. "One user said..." NOT "John said...").

    RULES:
    1. NO EMOJIS in body.
    2. NO EM-DASHES (—).
    3. No inline links.
    4. Short paragraphs.
    5. **EXCERPT < 280 chars.**
    
    OUTPUT: JSON with keys: title, meta_title, meta_description, excerpt, html_content.
    """
    try:
        # Claude 3.5 Sonnet Cost: ~$3/1M input, ~$15/1M output. 
        # Approx $0.03 for a long blog post generation.
        msg = writer.messages.create(
            model=model, max_tokens=8000, temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        track_cost("Anthropic (Claude)", 0.03) 
        
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        return json.loads(txt)
    except Exception as e:
        add_log(f"Writing Error: {e}")
        return None

def agent_socials(blog_html, model):
    add_log("Agent 3: Creating Socials from Blog...")
    
    # FIX: We now pass the ACTUAL BLOG CONTENT, not just the topic
    # Stripping HTML tags for cleaner reading by the social agent
    clean_text = blog_html.replace("<p>", "").replace("</p>", "\n").replace("<h2>", "\n# ").replace("</h2>", "")[:15000]

    prompt = f"""
    Create social posts based on this **BLOG CONTENT**:
    
    {clean_text}
    
    1. LinkedIn: Professional, bullets.
    2. Twitter/X: A THREAD of 3-5 tweets. Tweet 1: Hook. Last Tweet: CTA.
    3. Reddit: Engaging Title + Body.
    
    IMPORTANT: Return ONLY valid JSON.
    OUTPUT: JSON with keys: "linkedin", "twitter_thread" (Array of strings), "reddit".
    """
    try:
        msg = writer.messages.create(
            model=model, max_tokens=2000, temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        track_cost("Anthropic (Claude)", 0.01)
        
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        return json.loads(txt.strip())
    except Exception as e:
        add_log(f"Socials Error: {e}")
        return {"linkedin": "", "twitter_thread": [], "reddit": ""}

def agent_artist(topic, tone, audience, custom_prompt=None):
    add_log("Agent 4 (DALL-E): Generating Art...")
    if not openai_client_is_valid: return None
    
    if custom_prompt:
        base_prompt = custom_prompt
    else:
        base_prompt = f"A visualization of {topic}"

    visual_style = "High-end editorial photography, shallow depth of field."
    if "Teenager" in audience or "Child" in audience:
        visual_style = "Vibrant 3D render, Pixar-style."
    elif "Technical" in tone:
        visual_style = "Isometric data art, matte black background, neon accents."

    full_prompt = f"{base_prompt}. Style: {visual_style}. No text. Aspect Ratio: 16:9."
    
    try:
        # DALL-E 3 Standard Cost: $0.040 per image
        res = openai_client.images.generate(model="dall-e-3", prompt=full_prompt, size="1024x1024", quality="standard", n=1)
        track_cost("OpenAI (DALL-E/Whisper)", 0.04)
        return res.data[0].url
    except Exception as e:
        add_log(f"Art Error: {e}")
        return None

def upload_ghost(data, img_url, tags):
    add_log("Publishing to Ghost...")
    try:
        id, sec = GHOST_ADMIN_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        token = jwt.encode({'iat': iat, 'exp': iat+300, 'aud': '/admin/'}, bytes.fromhex(sec), algorithm='HS256', headers={'kid': id})
        
        final_img = img_url
        if img_url and "oaidalleapiprod" in img_url:
            img_data = requests.get(img_url).content
            files = {'file': (f"img_{iat}.png", img_data, 'image/png')}
            up_res = requests.post(f"{GHOST_API_URL}/ghost/api/admin/images/upload/", headers={'Authorization': f'Ghost {token}'}, files=files)
            if up_res.status_code == 201: final_img = up_res.json()['images'][0]['url']

        safe_excerpt = data['excerpt'][:300] if data['excerpt'] else ""

        body = {
            "posts": [{
                "title": data['title'], 
                "html": data['html_content'], 
                "feature_image": final_img,
                "custom_excerpt": safe_excerpt, 
                "status": "draft", 
                "tags": [{"name": t} for t in tags],
                "meta_title": data.get('meta_title'), 
                "meta_description": data.get('meta_description')
            }]
        }
        res = requests.post(f"{GHOST_API_URL}/ghost/api/admin/posts/?source=html", json=body, headers={'Authorization': f'Ghost {token}'})
        return res.status_code == 201
    except Exception as e:
        add_log(f"Ghost Error: {e}")
        return False

# --- UI LAYOUT ---

st.title("🧠 Elite AI Blog Agent V12")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# CUSTOM IMAGE PROMPT ON MAIN SCREEN
img_prompt = st.text_input("🎨 Custom Image Description (Optional)", placeholder="Describe the header image you want... (Leave empty for auto-generation)", key="main_img_prompt")

# --- 3-COLUMN SYMMETRICAL LAYOUT ---
col1, col2, col3 = st.columns([1, 1, 1])

# Left Column: Writing Style
with col1:
    st.markdown("### ✍️ Style")
    style_sample = st.text_area("Voice Mimicry / Sample", height=250, placeholder="Paste your writing sample here...", help="The AI will mimic the sentence structure and vocabulary of this text.")

# Center Column: File Uploader (Square)
with col2:
    st.markdown("### 📎 Context")
    # CSS hacks above make this square and tall
    uploaded_file = st.file_uploader("Upload", type=['txt','pdf','docx','mp3','mp4'], label_visibility="collapsed")

# Right Column: Audience & Tone
with col3:
    st.markdown("### 🎯 Target")
    tone_setting = st.selectbox("Tone", ["Conversational", "Technical", "Professional", "Witty", "Storyteller", "Journalistic"])
    audience_setting = st.selectbox("Audience", ["General Public", "Developer", "Executive", "Recruiter", "Grand Parent", "Teenager", "Child", "Hobbyist", "CEO"])
    
    # Cost Tracker (Restored)
    st.markdown("#### 💰 Session Cost")
    df_costs = pd.DataFrame(list(st.session_state.costs.items()), columns=["Provider", "Cost ($)"])
    df_costs = df_costs.sort_values(by="Cost ($)", ascending=False)
    st.dataframe(df_costs, hide_index=True, use_container_width=True)

# Main Prompt (Full Width below columns)
st.markdown("---")
col_topic, col_logs = st.columns([2, 1])

with col_topic:
    st.markdown("### 💡 Topic & SEO")
    topic = st.text_area("Main Blog Topic", height=100, placeholder="Enter detailed prompt...")
    
    c_btn, c_txt = st.columns([1, 4])
    with c_btn:
        st.write("")
        st.write("")
        if st.button("✨ Keywords"):
            if topic: st.session_state.seo_keywords = agent_seo(topic)
    with c_txt:
        keywords = st.text_area("SEO Keywords", value=st.session_state.seo_keywords, height=68, label_visibility="collapsed")
        st.session_state.seo_keywords = keywords

with col_logs:
    st.markdown("### 📜 Live Logs")
    st.text_area("", value="\n".join(st.session_state.log_events), height=220, disabled=True, key="logs_display")

# START BUTTON
st.write("")
if st.button("🚀 Start Elite Workflow", type="primary", use_container_width=True):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        st.session_state.log_events = [] 
        add_log("Workflow Initialized.")
        st.session_state.transcript_context = False
        transcript_txt = None
        
        # File Processing
        if uploaded_file:
            if uploaded_file.name.endswith(('.mp3','.mp4','.wav','.m4a')):
                 transcript_txt = transcribe_audio(uploaded_file)
            else:
                 transcript_txt = extract_text(uploaded_file)
            
            if transcript_txt and "Error" not in transcript_txt:
                st.session_state.transcript_context = True
                add_log("Context Loaded.")
        
        # Agents
        research_data = agent_research(topic, st.session_state.transcript_context)
        if research_data:
            blog = agent_writer(topic, research_data, style_sample, tone_setting, keywords, audience_setting, transcript_txt, "claude-sonnet-4-20250514")
            
            if blog:
                st.session_state.elite_blog_v8 = blog
                
                # Setup Edit State
                st.session_state.final_title = blog['title']
                st.session_state.final_content = blog['html_content']
                st.session_state.final_excerpt = blog['excerpt']
                
                # Socials (NOW USING BLOG CONTENT)
                st.session_state.elite_socials = agent_socials(blog['html_content'], "claude-sonnet-4-20250514")
                
                # Art (USING CUSTOM PROMPT IF SET)
                img = agent_artist(topic, tone_setting, audience_setting, custom_prompt=img_prompt)
                if img: st.session_state.elite_image_v8 = img
                
                add_log("Workflow Complete.")
                st.rerun()

# --- PREVIEW AREA ---
if st.session_state.elite_blog_v8:
    st.divider()
    t1, t2 = st.tabs(["📝 Editor", "📱 Socials"])
    
    with t1:
        c_prev, c_edit = st.columns(2)
        with c_prev:
            st.subheader("👁️ Preview")
            if st.session_state.get('elite_image_v8'):
                st.image(st.session_state.elite_image_v8)
            
            # TITLE & EXCERPT PREVIEW
            st.markdown(f"### {st.session_state.final_title}")
            st.markdown(f"_{st.session_state.final_excerpt}_")
            st.divider()
            
            # HTML PREVIEW (FIXED: Isolated Component)
            components.html(st.session_state.final_content, height=600, scrolling=True)

        with c_edit:
            st.subheader("✏️ Edit")
            st.text_input("Title", key='final_title')
            st.text_area("Excerpt (Max 300)", key='final_excerpt', max_chars=300)
            st.text_area("HTML Body", key='final_content', height=500)
            
            if st.button("🚀 Publish to Ghost", type="primary"):
                tags = ["Elite AI"]
                if st.session_state.transcript_context: tags.append("Context Aware")
                
                final_data = {
                    'title': st.session_state.final_title,
                    'excerpt': st.session_state.final_excerpt,
                    'html_content': st.session_state.final_content,
                    'meta_title': st.session_state.final_title,
                    'meta_description': st.session_state.final_excerpt
                }
                
                if upload_ghost(final_data, st.session_state.get('elite_image_v8'), tags):
                    st.success("Published!")
                    st.balloons()
                else:
                    st.error("Failed.")

    with t2:
        s = st.session_state.get('elite_socials', {})
        st.text_area("LinkedIn", value=s.get('linkedin', ''), height=200)
        st.link_button("Post LinkedIn", generate_social_link(s.get('linkedin', ''), "linkedin"))
        
        tw = s.get('twitter_thread', [])
        if isinstance(tw, str): tw = [tw]
        st.text_area("X Hook", value=tw[0] if tw else "", height=100)
        st.link_button("Post X", generate_social_link(tw[0] if tw else "", "twitter"))
        st.text_area("Rest of Thread", value="\n\n".join(tw[1:]), height=200)
