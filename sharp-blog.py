import streamlit as st
import streamlit.components.v1 as components
import requests
import jwt
import datetime
import json
import io
import urllib.parse
import base64
import random
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
st.set_page_config(page_title="Elite AI Blog Agent v0.14.6", page_icon="🧠", layout="wide")

st.markdown("""
<style>
    /* MAIN BACKGROUND */
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    
    /* INPUTS */
    .stTextArea textarea, .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1c1c1c !important;
        color: #00e5ff !important; /* Neon Cyan */
        border: 1px solid #333 !important;
        font-family: 'Helvetica Neue', sans-serif !important;
    }
    
    /* SQUARE FILE UPLOADER */
    div[data-testid="stFileUploader"] section {
        background-color: #161b22;
        border: 2px dashed #00e5ff; 
        border-radius: 15px;
        min-height: 160px !important; 
        display: flex; align-items: center; justify-content: center;
    }

    /* HEADERS */
    h1, h2, h3 {
        background: -webkit-linear-gradient(45deg, #00e5ff, #d500f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* GRADIENT START BUTTON */
    div[data-testid="stButton"] button {
        background: linear-gradient(45deg, #00e5ff, #00ffab) !important;
        color: #000000 !important;
        border: none !important;
        font-weight: 800 !important;
        font-size: 1.2rem !important;
        text-transform: uppercase;
        transition: all 0.3s ease;
    }
    div[data-testid="stButton"] button:hover {
        box-shadow: 0 0 20px #00ffab;
        transform: scale(1.02);
        color: #000000 !important;
    }
    
    .stAlert { background-color: #1c1c1c; border: 1px solid #333; color: #00e5ff; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'log_events' not in st.session_state: st.session_state.log_events = []
if 'current_workflow_status' not in st.session_state: st.session_state.current_workflow_status = "Ready."
if 'costs' not in st.session_state: st.session_state.costs = {"Anthropic": 0.0, "OpenAI": 0.0, "Perplexity": 0.0}
if 'elite_blog_v8' not in st.session_state: st.session_state.elite_blog_v8 = None
if 'transcript_context' not in st.session_state: st.session_state.transcript_context = False
if 'final_title' not in st.session_state: st.session_state.final_title = ""
if 'final_content' not in st.session_state: st.session_state.final_content = ""
if 'final_excerpt' not in st.session_state: st.session_state.final_excerpt = ""
if 'seo_keywords' not in st.session_state: st.session_state.seo_keywords = ""
if 'last_claude_model' not in st.session_state: st.session_state.last_claude_model = "claude-sonnet-4-20250514"
if 'claude_model_selection' not in st.session_state: st.session_state.claude_model_selection = "claude-sonnet-4-20250514"
if 'headline_ideas' not in st.session_state: st.session_state.headline_ideas = ""

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

# --- CLIENTS ---
@st.cache_resource
def get_clients():
    pplx = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
    anth = Anthropic(api_key=ANTHROPIC_API_KEY)
    try: oai = OpenAI(api_key=OPENAI_API_KEY)
    except: oai = None
    return pplx, anth, oai

researcher, writer, openai_client = get_clients()
openai_client_is_valid = openai_client is not None

# --- CUSTOM CELEBRATION ENGINE ---
def celebrate_with_logos():
    """
    Floats the specific Sharp Human logo files up the screen.
    """
    
    # 1. UPDATED LOGO LIST
    logo_files = [
        "logo1-1.png", "logo1-2.png", "logo1-3.png", 
        "logo1-4.png", "logo1-5.png", "logo1-6.png"
    ]
    
    # 2. Helper to load image as Base64
    def get_img_tag(filename):
        if os.path.exists(filename):
            with open(filename, "rb") as f:
                data = f.read()
                b64 = base64.b64encode(data).decode()
                # Added filter: drop-shadow for neon effect
                return f'<img src="data:image/png;base64,{b64}" style="width: 80px; opacity: 0.95; filter: drop-shadow(0 0 5px rgba(0,229,255,0.5));">'
        return None

    # 3. Generate Particles
    particles = []
    
    for _ in range(50): # Number of logos
        left = random.randint(0, 95)
        delay = random.uniform(0, 3)
        duration = random.uniform(4, 8)
        
        chosen_file = random.choice(logo_files)
        img_tag = get_img_tag(chosen_file)
        
        if not img_tag:
            # Fallback if file missing: Neon Square
            color = random.choice(["#00e5ff", "#39ff14", "#d500f9"])
            content = f'<div style="width: 20px; height: 20px; background-color: {color}; transform: rotate(45deg); box-shadow: 0 0 10px {color};"></div>'
        else:
            content = img_tag

        particle_html = f"""
        <div style="position: fixed; left: {left}%; bottom: -100px; 
                    animation: floatUp {duration}s ease-in {delay}s forwards; 
                    z-index: 9999; pointer-events: none;">
            {content}
        </div>
        """
        particles.append(particle_html)

    # 4. Inject CSS Animation
    full_html = f"""
    <style>
        @keyframes floatUp {{
            0% {{ bottom: -120px; opacity: 0; transform: scale(0.5) rotate(0deg); }}
            10% {{ opacity: 1; }}
            100% {{ bottom: 120vh; opacity: 0; transform: scale(1.1) rotate(20deg); }}
        }}
    </style>
    {''.join(particles)}
    """
    st.markdown(full_html, unsafe_allow_html=True)

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
        transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=file)
        track_cost("OpenAI", 0.06)
        return transcript.text
    except Exception as e:
        if "413" in str(e): return "Error: File >25MB (OpenAI Limit)."
        return f"Error: {e}"

def generate_social_link(text, platform):
    if platform == "twitter": safe = urllib.parse.quote(text[:2500]) 
    elif platform == "linkedin": safe = urllib.parse.quote(text[:2000])
    elif platform == "reddit": safe = urllib.parse.quote(text[:3000])
    
    if platform == "twitter": return f"https://twitter.com/intent/tweet?text={safe}"
    if platform == "linkedin": return f"https://www.linkedin.com/feed/?shareActive=true&text={safe}"
    if platform == "reddit": return f"https://www.reddit.com/submit?selftext=true&title=New%20Post&text={safe}"
    return "#"

# --- AGENTS ---

def agent_headlines(topic):
    add_log("Generating Headlines...")
    try:
        res = researcher.chat.completions.create(model="sonar", messages=[{"role": "user", "content": f"Generate 5 engaging, helpful blog headlines for the topic: '{topic}'. Do not use clickbait like 'Death of'. Be professional and inviting."}])
        track_cost("Perplexity", 0.005)
        return res.choices[0].message.content
    except: return "Error generating headlines."

def agent_seo(topic):
    add_log("SEO: Analyzing...")
    try:
        res = researcher.chat.completions.create(model="sonar", messages=[{"role": "user", "content": f"Suggest 5-7 high-impact SEO keywords for: {topic}. Comma separated."}])
        track_cost("Perplexity", 0.005)
        return res.choices[0].message.content
    except: return ""

def agent_research(topic, context):
    add_log("Agent 1: Researching...")
    sys_prompt = "You are a Fact-Checking Researcher." if context else "You are an elite researcher."
    try:
        res = researcher.chat.completions.create(model="sonar-pro", messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Research: {topic}"}])
        track_cost("Perplexity", 0.02)
        return res.choices[0].message.content
    except: return None

def clean_json_response(txt):
    txt = txt.strip()
    if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
    elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
    return txt.strip()

def agent_writer(topic, headline_hint, research, style, tone, keywords, audience, context_txt, model):
    add_log(f"Agent 2: Writing...")
    
    headline_inst = ""
    if headline_hint:
        headline_inst = f"MANDATORY HEADLINE: You MUST use this exact headline or a close variation: '{headline_hint}'"

    prompt = f"""
    You are a world-class Ghostwriter and Editor. Write a helpful, high-quality blog post.
    
    **STRATEGY:**
    - TOPIC: "{topic}"
    - {headline_inst}
    - AUDIENCE: {audience}
    - TONE: {tone}
    - KEYWORDS: {keywords}
    
    **DATA SOURCES:**
    - RESEARCH: {research}
    - CONTEXT FILE: {context_txt[:40000] if context_txt else "None"}

    *** 🚨 RULES OF ENGAGEMENT 🚨 ***
    1. **PUNCTUATION:** **NEVER USE LONG HYPHENS (EM-DASHES —)**. Structure your sentences naturally so they aren't needed. Use commas or periods.
    2. **BOLDING:** Do **NOT** use bold text inside paragraphs. Save bolding for Headers (H2/H3) only.
    3. **PRIVACY:** Generalize all anecdotes. Use "Industry trends show..." instead of "Bob said...". Keep it industry-agnostic.
    4. **NO INLINE LINKS:** Do not distract the reader. List sources at the bottom.
    5. **HUMAN FLOW:** Write like a human. Varied sentence structure. Warm but professional.
    
    **OUTPUT FORMAT:**
    Return ONLY a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content".
    """
    try:
        msg = writer.messages.create(model=model, max_tokens=8000, temperature=0.7, messages=[{"role": "user", "content": prompt}])
        track_cost("Anthropic", 0.03)
        return json.loads(clean_json_response(msg.content[0].text))
    except Exception as e:
        add_log(f"Writer Error: {e}")
        return None

def agent_socials(blog_html, model):
    add_log("Agent 3: Creating Socials...")
    clean_text = blog_html.replace("<p>", "").replace("</p>", "\n")[:15000]
    prompt = f"""
    Create social posts based on this BLOG:
    {clean_text}
    
    1. LinkedIn: Professional, bullets.
    2. Twitter/X: THREAD (3-5 tweets). Tweet 1: Hook. Last: CTA.
    3. Reddit: Engaging Title + Body.
    
    IMPORTANT: Return ONLY valid JSON.
    OUTPUT: JSON with keys: "linkedin", "twitter_thread" (Array of strings), "reddit".
    """
    try:
        msg = writer.messages.create(model=model, max_tokens=2000, temperature=0.7, messages=[{"role": "user", "content": prompt}])
        track_cost("Anthropic", 0.01)
        return json.loads(clean_json_response(msg.content[0].text))
    except: return {"linkedin": "", "twitter_thread": [], "reddit": ""}

def agent_artist(topic, tone, audience, custom_prompt=None):
    add_log("Agent 4: Generating Art...")
    if not openai_client_is_valid: return None
    
    base_prompt = custom_prompt if custom_prompt else f"A visualization of {topic}"
    visual_style = "High-end editorial photography, shallow depth of field, Leica M11 style."
    if "Teenager" in audience or "Child" in audience: visual_style = "Vibrant 3D render, Pixar-style."
    elif "Technical" in tone: visual_style = "Isometric data art, matte black background."

    full_prompt = f"{base_prompt}. Style: {visual_style}. No text. Aspect Ratio: 16:9."
    try:
        res = openai_client.images.generate(model="dall-e-3", prompt=full_prompt, size="1024x1024", quality="standard", n=1)
        track_cost("OpenAI", 0.04)
        return res.data[0].url
    except: return None

def agent_refine(data, feedback, model):
    add_log("Agent 5: Refining...")
    prompt = f"""
    Refine this blog post.
    CURRENT DATA: {json.dumps(data)}
    FEEDBACK: {feedback}
    RULES: Keep HTML format. No Emojis. No Em-dashes. No Bold in paragraphs.
    OUTPUT: JSON with keys title, meta_title, meta_description, excerpt, html_content.
    """
    try:
        msg = writer.messages.create(model=model, max_tokens=8000, temperature=0.4, messages=[{"role": "user", "content": prompt}])
        track_cost("Anthropic", 0.02)
        return json.loads(clean_json_response(msg.content[0].text))
    except: return None

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

st.title("🧠 Elite AI Blog Agent v0.14.6")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# --- 3-COLUMN LAYOUT ---
col1, col2, col3 = st.columns([1, 1, 1])

with col1:
    st.markdown("### ✍️ Style")
    style_sample = st.text_area("Voice Mimicry", height=200, placeholder="Paste text here...")

with col2:
    st.write("")
    st.write("")
    st.markdown("### 📎 Context")
    uploaded_file = st.file_uploader("", type=['txt','pdf','docx','mp3','mp4'], label_visibility="collapsed")

with col3:
    st.markdown("### 🎯 Target")
    
    # DESCRIPTIVE OPTIONS
    tone_options = [
        "Conversational (Friendly, relatable, uses contractions)",
        "Technical (Precise, industry jargon, dense)",
        "Professional (Corporate, authoritative, accessible)",
        "Witty (Clever, light humor, entertaining)",
        "Storyteller (Narrative arc, emotive, scene-setting)",
        "Journalistic (Objective, fact-based, inverted pyramid)"
    ]
    tone_setting = st.selectbox("Tone", tone_options)
    
    aud_options = [
        "General Public (Accessible, clear, no jargon)",
        "Developer (Technical depth, code concepts)",
        "Executive (Strategic, high-level summary, ROI focus)",
        "Recruiter (Skills focus, career progression)",
        "Grand Parent (Simple metaphors, respectful, patient)",
        "Teenager (Fast-paced, authentic, minimal slang)",
        "Child (Simple words, exciting analogies, educational)",
        "Hobbyist (Passionate, detailed, practical tips)",
        "CEO (Concise, strategic, bottom-line upfront)"
    ]
    audience_setting = st.selectbox("Audience", aud_options)
    
    st.markdown("#### 📜 Activity Log")
    st.text_area("", value="\n".join(st.session_state.log_events), height=100, disabled=True, key="logs_display")

# --- TOPIC SECTION ---
st.markdown("---")
st.markdown("### 💡 Topic")
topic = st.text_area("", height=100, placeholder="Enter prompt...", label_visibility="collapsed")

# ROW 2: HEADLINE & IMAGE PROMPT (Side by Side)
c_head, c_img = st.columns(2)
with c_head:
    headline_hint = st.text_input("Suggested Headline (Optional)", placeholder="Enter a headline to guide the AI...")
with c_img:
    img_prompt = st.text_input("Custom Image Prompt (Optional)", placeholder="Describe the image... (Leave empty for auto-gen)")

# ROW 3: SEO
st.markdown("### 🔑 SEO Keywords")
c_seo_txt, c_seo_btn = st.columns([4, 1])
with c_seo_txt:
    keywords = st.text_area("", value=st.session_state.seo_keywords, height=68, label_visibility="collapsed")
    st.session_state.seo_keywords = keywords
with c_seo_btn:
    if st.button("✨ Choose For Me"):
        if topic: st.session_state.seo_keywords = agent_seo(topic)

# --- STATUS & COST ---
st.markdown("---")
s1, s2 = st.columns(2)
with s1:
    st.info(f"**Status:** {st.session_state.current_workflow_status}")
with s2:
    with st.expander("💰 Costs & Settings", expanded=False):
        st.write(st.session_state.costs)
        st.selectbox("Model:", ["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus"], key="claude_model_selection")

# START BUTTON (GRADIENT VIA CSS)
st.write("")
if st.button("Start Sharp Bloggling", type="primary", use_container_width=True):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        st.session_state.log_events = [] 
        add_log("Workflow Initialized.")
        st.session_state.current_workflow_status = "Processing Context..."
        st.session_state.last_claude_model = st.session_state.claude_model_selection
        st.session_state.transcript_context = False
        transcript_txt = None
        
        if uploaded_file:
            if uploaded_file.name.endswith(('.mp3','.mp4','.wav','.m4a')): transcript_txt = transcribe_audio(uploaded_file)
            else: transcript_txt = extract_text(uploaded_file)
            if transcript_txt and "Error" not in transcript_txt:
                st.session_state.transcript_context = True
                add_log("Context Loaded.")
        
        st.session_state.current_workflow_status = "Researching..."
        research_data = agent_research(topic, st.session_state.transcript_context)
        
        if research_data:
            st.session_state.current_workflow_status = "Drafting..."
            blog = agent_writer(topic, headline_hint, research_data, style_sample, tone_setting, keywords, audience_setting, transcript_txt, st.session_state.claude_model_selection)
            
            if blog:
                st.session_state.elite_blog_v8 = blog
                st.session_state.final_title = blog['title']
                st.session_state.final_content = blog['html_content']
                st.session_state.final_excerpt = blog['excerpt']
                
                st.session_state.current_workflow_status = "Socials & Art..."
                st.session_state.elite_socials = agent_socials(blog['html_content'], st.session_state.claude_model_selection)
                img = agent_artist(topic, tone_setting, audience_setting, custom_prompt=img_prompt)
                if img: st.session_state.elite_image_v8 = img
                
                st.session_state.current_workflow_status = "Done! Review below."
                st.rerun()

# --- PREVIEW & REFINE ---
if st.session_state.elite_blog_v8:
    st.divider()
    t1, t2 = st.tabs(["📝 Review & Refine", "📱 Social Media"])
    
    with t1:
        st.subheader("👁️ Preview")
        
        c_preview_img, c_preview_html = st.columns(2)

        with c_preview_img:
            if st.session_state.get('elite_image_v8'):
                st.image(st.session_state.elite_image_v8, use_container_width=True)
                with st.expander("🎨 Regenerate Image"):
                    regen_prompt = st.text_input("New Image Prompt", placeholder="Describe desired image...", key="regen_box")
                    if st.button("Regenerate Art", key="regen_btn"):
                        with st.spinner("Painting..."):
                            new_url = agent_artist(topic, tone_setting, audience_setting, custom_prompt=regen_prompt)
                            if new_url: 
                                st.session_state.elite_image_v8 = new_url
                                st.rerun()

        with c_preview_html:
             html_preview = f"""
            <div style="background-color: white; color: black; padding: 40px; border-radius: 10px; font-family: sans-serif;">
                <h1 style="color: black;">{st.session_state.final_title}</h1>
                <p><em>{st.session_state.final_excerpt}</em></p>
                <hr>
                {st.session_state.final_content}
            </div>
            """
             components.html(html_preview, height=600, scrolling=True)

        st.divider()
        st.markdown("### 🔄 Refine Draft")
        c_ref_txt, c_ref_btn = st.columns([3, 1])
        with c_ref_txt:
            refine_inst = st.text_area("Instructions", height=100, placeholder="e.g. Make it punchier...")
        with c_ref_btn:
            st.write("")
            st.write("")
            if st.button("✨ Refine"):
                with st.spinner("Refining..."):
                    curr = {
                        'title': st.session_state.final_title,
                        'excerpt': st.session_state.final_excerpt,
                        'html_content': st.session_state.final_content,
                        'meta_title': st.session_state.elite_blog_v8.get('meta_title'),
                        'meta_description': st.session_state.elite_blog_v8.get('meta_description')
                    }
                    new_post = agent_refine(curr, refine_inst, st.session_state.claude_model_selection)
                    if new_post:
                        st.session_state.final_title = new_post['title']
                        st.session_state.final_content = new_post['html_content']
                        st.session_state.final_excerpt = new_post['excerpt']
                        st.rerun()

        st.markdown("### ✏️ HTML Editor")
        st.text_input("Title", key='final_title')
        st.text_area("Excerpt (Max 300)", key='final_excerpt', max_chars=300)
        st.text_area("HTML Body", key='final_content', height=600)

        if st.button("🚀 Publish to Ghost", type="primary"):
            tags = ["Sharp Blog"] 
            if st.session_state.transcript_context: tags.append("Context Aware")
            final_data = {
                'title': st.session_state.final_title,
                'excerpt': st.session_state.final_excerpt,
                'html_content': st.session_state.final_content,
                'meta_title': st.session_state.elite_blog_v8.get('meta_title'),
                'meta_description': st.session_state.elite_blog_v8.get('meta_description')
            }
            if upload_ghost(final_data, st.session_state.get('elite_image_v8'), tags):
                celebrate_with_logos()
                st.success("Published!")
            else:
                st.error("Failed.")

    with t2:
        s = st.session_state.get('elite_socials', {})
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("### LinkedIn")
            li = st.text_area("LinkedIn", value=s.get('linkedin', ''), height=200)
            st.link_button("Post", generate_social_link(li, "linkedin"))
        with c2:
            st.markdown("### X")
            tw = s.get('twitter_thread', [])
            if isinstance(tw, str): tw = [tw]
            hook = st.text_area("Hook", value=tw[0] if tw else "", height=100)
            st.link_button("Post", generate_social_link(hook, "twitter"))
            st.text_area("Thread", value="\n\n".join(tw[1:]), height=100)
        with c3:
            st.markdown("### Reddit")
            rd = st.text_area("Reddit", value=s.get('reddit', ''), height=200)
            st.link_button("Post", generate_social_link(rd, "reddit"))
