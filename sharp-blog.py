import streamlit as st
import requests
import jwt
import datetime
import json
import io
import urllib.parse
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

# --- CONFIGURATION ---
st.set_page_config(page_title="Elite AI Blog Agent V11", page_icon="🎩", layout="wide")

# --- CSS: CORPORATE STYLING & LAYOUT HACKS ---
st.markdown("""
<style>
    /* 1. Global Typography */
    .stTextArea textarea, .stSelectbox div, .stButton button, p, h1, h2, h3 {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    }
    
    /* 2. Text Area & Input Styling */
    .stTextArea textarea {
        font-size: 15px !important;
        line-height: 1.5 !important;
    }
    
    /* 3. File Uploader HACK: Make it tall and square */
    div[data-testid="stFileUploader"] section {
        min-height: 200px !important; /* Twice the normal height */
        padding-top: 60px !important; /* Center the icon */
        border: 2px dashed #cccccc;
        background-color: #f9f9f9;
        border-radius: 10px;
    }
    div[data-testid="stFileUploader"] section:hover {
        border-color: #FF4B4B; /* Streamlit Red on hover */
    }

    /* 4. Expander Styling */
    div[data-testid="stExpander"] {
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        background-color: white;
    }
    
    /* 5. Button Styling */
    .stButton button {
        width: 100%;
        border-radius: 6px;
        font-weight: 600;
        height: 3rem;
    }
    
    /* 6. Header Spacing */
    h3 { padding-top: 0px !important; margin-top: 0px !important; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'log_events' not in st.session_state: st.session_state.log_events = []
if 'current_workflow_status' not in st.session_state: st.session_state.current_workflow_status = "Ready."
if 'claude_model_selection' not in st.session_state: st.session_state.claude_model_selection = "claude-sonnet-4-20250514"
if 'last_claude_model' not in st.session_state: st.session_state.last_claude_model = "None (Awaiting Run)"
if 'elite_blog_v8' not in st.session_state: st.session_state.elite_blog_v8 = None
if 'transcript_context' not in st.session_state: st.session_state.transcript_context = False
if 'final_title' not in st.session_state: st.session_state.final_title = ""
if 'final_content' not in st.session_state: st.session_state.final_content = ""
if 'final_excerpt' not in st.session_state: st.session_state.final_excerpt = ""
if 'seo_keywords' not in st.session_state: st.session_state.seo_keywords = ""

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

def set_status(user_msg):
    st.session_state.current_workflow_status = user_msg

# --- CLIENTS ---
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
writer = Anthropic(api_key=ANTHROPIC_API_KEY)
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    openai_client_is_valid = True
except:
    openai_client = None
    openai_client_is_valid = False

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
        return openai_client.audio.transcriptions.create(model="whisper-1", file=file).text
    except Exception as e:
        if "413" in str(e): return "Error: File >25MB (OpenAI Limit). Please split file."
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
    add_log("SEO Agent: Starting...")
    try:
        res = researcher.chat.completions.create(
            model="sonar", 
            messages=[{"role": "user", "content": f"Suggest 5-7 high-impact SEO keywords for: {topic}. Comma separated. List only."}]
        )
        add_log("SEO Agent: Success.")
        return res.choices[0].message.content
    except Exception as e:
        add_log(f"SEO Agent Failed: {e}")
        return ""

@st.cache_data(show_spinner=False)
def agent_research(topic, context):
    sys_prompt = "You are a Fact-Checking Researcher." if context else "You are an elite academic researcher."
    try:
        res = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Research: {topic}"}]
        )
        return res.choices[0].message.content
    except Exception as e:
        return None

def agent_writer(topic, research, style, tone, keywords, audience, context_txt, model):
    add_log(f"Agent 2 (Claude): Writing ({tone})...")
    
    aud_map = {
        "Grand Parent": "Simple metaphors, respectful, clear, large concepts. Avoid slang.",
        "Teenager": "Fast-paced, authentic, minimal slang, focus on identity and social proof.",
        "Child": "Simple words, short sentences, exciting analogies, educational but fun.",
        "CEO": "ROI-focused, strategic, concise (BLUF). No fluff.",
        "Hobbyist": "Passionate, detailed, practical tips, community-focused.",
        "Developer": "Technical depth, code concepts, implementation details.",
        "Executive": "Strategic impact, business outcomes, high-level summary.",
        "General Public": "Accessible, clear, relatable, no jargon."
    }
    aud_inst = aud_map.get(audience, "Professional and clear.")

    prompt = f"""
    Write a blog post.
    TOPIC: "{topic}"
    AUDIENCE: {aud_inst}
    TONE: {tone}. {f"MIMIC STYLE: {style}" if style else ""}
    KEYWORDS: {keywords}
    RESEARCH: {research}
    CONTEXT: {context_txt[:30000] if context_txt else "None"}

    *** PRIVACY & ANONYMITY PROTOCOL (MANDATORY) ***
    - The CONTEXT contains a raw interview/transcript.
    - **NEVER use specific personal names** from the transcript (e.g. "John mentioned...").
    - **ALWAYS generalize** anecdotes into market trends (e.g. "It is common for users to report...").
    - Treat the transcript as "Market Data", not "Quotes".

    RULES:
    1. NO EMOJIS in body text.
    2. NO EM-DASHES (—). Use hyphens (-) or commas.
    3. No inline links. List "Sources" at the end.
    4. Human-like flow. Vary sentence length.
    5. **EXCERPT must be concise (< 280 chars).**
    
    OUTPUT: JSON with keys: title, meta_title, meta_description, excerpt, html_content.
    """
    try:
        msg = writer.messages.create(
            model=model, max_tokens=8000, temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        return json.loads(txt)
    except Exception as e:
        add_log(f"Writing Error: {e}")
        return None

def agent_socials(content, model):
    add_log("Agent 3 (Claude): Drafting Socials...")
    prompt = f"""
    Create social posts.
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
        txt = msg.content[0].text
        cleaned_txt = txt.strip()
        if "```json" in cleaned_txt: cleaned_txt = cleaned_txt.split("```json")[1].split("```")[0]
        elif "```" in cleaned_txt: cleaned_txt = cleaned_txt.split("```")[1].split("```")[0]
        
        return json.loads(cleaned_txt.strip())
    except Exception as e:
        add_log(f"Socials JSON Error: {e}")
        return {"linkedin": f"Error: {e}", "twitter_thread": [], "reddit": ""}

def agent_artist(topic, tone, audience, custom_prompt=None):
    add_log("Agent 4 (DALL-E): Generating Art...")
    if not openai_client_is_valid: return None
    
    if custom_prompt:
        base_prompt = custom_prompt
    else:
        base_prompt = f"A visualization of {topic}"

    visual_style = "Award-winning editorial photography, shot on Leica M11, 50mm lens, soft natural lighting, realistic textures, shallow depth of field."
    
    if "Teenager" in audience or "Child" in audience:
        visual_style = "High-quality Pixar-style 3D render, soft rounded shapes, vibrant but harmonious colors."
    elif "Technical" in tone:
        visual_style = "Minimalist isometric data art, matte black background, glass and steel textures, architectural lighting."
    elif "Executive" in audience or "CEO" in audience:
        visual_style = "Abstract corporate art, geometric shapes, marble and gold textures, minimalist and premium."

    full_prompt = f"{base_prompt}. Style: {visual_style}. Negative Prompt: No text, no words, no cartoons, no distorted faces, no uncanny valley, no bad anatomy. Aspect Ratio: 16:9."
    
    try:
        res = openai_client.images.generate(model="dall-e-3", prompt=full_prompt, size="1024x1024", quality="standard", n=1)
        return res.data[0].url
    except Exception as e:
        add_log(f"Art Error: {e}")
        return None

def agent_refine(data, feedback, model):
    add_log("Agent 5 (Refiner): Updating Draft...")
    prompt = f"""
    Refine this blog post.
    CURRENT DATA: {json.dumps(data)}
    FEEDBACK: {feedback}
    RULES: Keep HTML format. No Emojis. No Em-dashes. Anonymize names.
    OUTPUT: JSON with keys title, meta_title, meta_description, excerpt, html_content.
    """
    try:
        msg = writer.messages.create(
            model=model, max_tokens=8000, temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        return json.loads(txt)
    except: return None

def upload_ghost(data, img_url, tags):
    add_log("Publishing to Ghost...")
    try:
        id, sec = GHOST_ADMIN_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        token = jwt.encode({'iat': iat, 'exp': iat+300, 'aud': '/admin/'}, bytes.fromhex(sec), algorithm='HS256', headers={'kid': id})
        
        final_img = img_url
        if "oaidalleapiprod" in img_url:
            img_data = requests.get(img_url).content
            files = {'file': (f"img_{iat}.png", img_data, 'image/png')}
            up_res = requests.post(f"{GHOST_API_URL}/ghost/api/admin/images/upload/", headers={'Authorization': f'Ghost {token}'}, files=files)
            if up_res.status_code == 201: final_img = up_res.json()['images'][0]['url']

        # Ghost Safety Truncation
        safe_excerpt = data['excerpt']
        if len(safe_excerpt) > 300: safe_excerpt = safe_excerpt[:297] + "..."

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

# --- LAYOUT CONSTRUCTION ---

st.title("🎩 Elite AI Blog Agent V11.0")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# MAIN COLUMNS
left_col, right_col = st.columns([2, 1])

# --- RIGHT COLUMN (LOGS & STATUS) - TOP PRIORITY ---
with right_col:
    # 1. Live Logs
    st.markdown("### 📜 Live Logs")
    st.text_area("", value="\n".join(st.session_state.log_events), height=250, disabled=True, key="logs_display")
    
    # 2. High Level Status
    st.markdown("### 🟢 User Status")
    st.info(st.session_state.current_workflow_status)
    
    # 3. Technical Status
    with st.expander("🛠️ Technical / Low Level Status", expanded=True):
        st.write(f"**Writer:** {st.session_state.last_claude_model}")
        st.write("**Research:** Perplexity Sonar")
        st.write("**Art:** DALL-E 3 (Editorial Mode)")
        if textstat_installed:
            st.write("**Readability:** TextStat Active")
        else:
            st.write("**Readability:** Disabled (Missing textstat)")

# --- LEFT COLUMN (INPUTS) ---
with left_col:
    st.markdown("### 📝 Strategy")
    
    # Row 1: Tone & Audience
    c1, c2 = st.columns(2)
    with c1:
        tone_setting = st.selectbox("Tone & Voice", ["Conversational", "Technical", "Professional", "Witty", "Storyteller", "Journalistic"])
    with c2:
        audience_setting = st.selectbox("Target Audience", [
            "General Public", "Developer (Technical)", "Executive (Strategy/ROI)", "Recruiter (Career/Skills)",
            "Grand Parent", "Teenager", "Child", "Hobbyist", "CEO"
        ])
    
    # Row 2: Writing Style (Full Width, Scrollable)
    style_sample = st.text_area("Writing Style / Voice Mimicry", height=100, placeholder="Paste text here to match its rhythm and vocabulary...")

    # Row 3: File Uploader (Taller via CSS)
    st.markdown("##### 📎 Context (Audio/PDF/Doc)")
    uploaded_file = st.file_uploader("", type=['txt','pdf','docx','mp3','mp4'], label_visibility="collapsed")

    # Row 4: Topic
    st.markdown("##### 💡 Main Topic")
    topic = st.text_area("Enter your detailed prompt here...", height=150, placeholder="e.g. A comprehensive guide on...")
    
    # Row 5: Keywords
    st.markdown("##### 🔑 SEO Keywords")
    ck1, ck2 = st.columns([1, 4])
    with ck1:
        st.write("")
        st.write("")
        if st.button("✨ Suggest"):
            if topic:
                with st.spinner("Thinking..."):
                    st.session_state.seo_keywords = agent_seo(topic)
    with ck2:
        keywords = st.text_area("", value=st.session_state.seo_keywords, height=68, label_visibility="collapsed")
        st.session_state.seo_keywords = keywords

    st.write("")
    if st.button("🚀 Start Elite Workflow", type="primary", use_container_width=True):
        if not topic:
            st.warning("Please enter a topic.")
        else:
            st.session_state.log_events = [] 
            add_log("Workflow Initialized.")
            set_status("Reading Context Files...")
            
            # Update Model Tracker
            st.session_state.last_claude_model = st.session_state.claude_model_selection
            
            st.session_state.transcript_context = False
            transcript_txt = None
            
            if uploaded_file:
                if uploaded_file.size > 100 * 1024 * 1024: st.error("File too large (>100MB).")
                else:
                    if uploaded_file.name.endswith(('.mp3','.mp4','.wav','.m4a')):
                         transcript_txt = transcribe_audio(uploaded_file)
                    else:
                         transcript_txt = extract_text(uploaded_file)
                    
                    if transcript_txt and "Error" not in transcript_txt:
                        st.session_state.transcript_context = True
                        add_log("Context Successfully Loaded.")
            
            # --- AGENT 1: RESEARCH ---
            set_status("Agent 1: Researching Topic...")
            add_log("Calling Perplexity...")
            research_data = agent_research(topic, st.session_state.transcript_context)
            add_log("Research Complete.")
            
            if research_data:
                # --- AGENT 2: WRITING ---
                set_status("Agent 2: Drafting Content...")
                blog = agent_writer(topic, research_data, style_sample, tone_setting, keywords, audience_setting, transcript_txt, st.session_state.claude_model_selection)
                
                if blog:
                    st.session_state.elite_blog_v8 = blog
                    
                    # Pre-fill State
                    st.session_state.final_title = blog['title']
                    st.session_state.final_content = blog['html_content']
                    st.session_state.final_excerpt = blog['excerpt']
                    st.session_state.final_meta_title = blog.get('meta_title', '')
                    st.session_state.final_meta_desc = blog.get('meta_description', '')
                    
                    # --- AGENT 3: SOCIALS ---
                    set_status("Agent 3: Creating Socials...")
                    st.session_state.elite_socials = agent_socials(blog['html_content'], st.session_state.claude_model_selection)
                    
                    # --- AGENT 4: ART ---
                    set_status("Agent 4: Generating Art...")
                    img = agent_artist(topic, tone_setting, audience_setting)
                    if img: st.session_state.elite_image_v8 = img
                    
                    set_status("Workflow Complete. Review below.")
                    add_log("All Agents Finished.")
                    st.rerun()

# --- RESULTS AREA (Full Width) ---
if st.session_state.elite_blog_v8:
    post = st.session_state.elite_blog_v8
    socials = st.session_state.get('elite_socials', {})
    
    st.divider()
    
    tab_blog, tab_social = st.tabs(["📝 Blog Editor & Preview", "📱 Social Media Pack"])

    with tab_blog:
        col_preview, col_edit = st.columns([1, 1])
        
        # --- PREVIEW COLUMN ---
        with col_preview:
            st.subheader("👁️ Rendered Preview")
            if st.session_state.get('elite_image_v8'):
                st.image(st.session_state.elite_image_v8, use_container_width=True)
                with st.expander("🎨 Regenerate Image"):
                    new_prompt = st.text_input("Custom Prompt")
                    if st.button("Regenerate"):
                        new_url = agent_artist(topic, tone_setting, audience_setting, new_prompt)
                        if new_url: 
                            st.session_state.elite_image_v8 = new_url
                            st.rerun()

            current_title = st.session_state.get('final_title', post.get('title'))
            current_content = st.session_state.get('final_content', post.get('html_content'))
            current_excerpt = st.session_state.get('final_excerpt', post.get('excerpt'))

            st.markdown(f"# {current_title}")
            st.markdown(f"*{current_excerpt}*")
            st.markdown("---")
            st.markdown(current_content, unsafe_allow_html=True)
            
            if textstat_installed:
                score = textstat.flesch_kincaid_grade(current_content)
                score_color = "red" if score > 12 else "orange" if score > 10 else "green"
                st.caption(f"Readability Grade Level: :{score_color}[{score}] (Aim for 8-10)")

            if st.button("🔄 Refresh Preview", help="Click to update preview after manual edits"):
                st.rerun()

        # --- EDITOR COLUMN ---
        with col_edit:
            st.subheader("✏️ Editor")
            
            with st.expander("SEO Metadata", expanded=False):
                st.text_input("Meta Title", key='final_meta_title')
                st.text_input("Meta Description", key='final_meta_desc')

            st.text_input("Title", key='final_title')
            
            excerpt_val = st.session_state.get('final_excerpt', '')
            excerpt_len = len(excerpt_val)
            ex_color = "red" if excerpt_len > 300 else "green"
            st.caption(f"Excerpt Length: :{ex_color}[{excerpt_len}/300]")
            st.text_area("Excerpt", key='final_excerpt', height=100)
            
            st.text_area("HTML Content", key='final_content', height=600)

        # --- REFINE DRAFT ---
        st.divider()
        st.subheader("🔄 Refine Draft (Agent 5)")
        ref_col_in, ref_col_btn = st.columns([4, 1])
        with ref_col_in:
            refine_inst = st.text_area("Refinement Instructions", height=100, placeholder="e.g. Make the intro punchier...")
        with ref_col_btn:
            st.write("")
            st.write("")
            if st.button("✨ Refine Now"):
                with st.spinner("Refining..."):
                    curr_data = {
                        'title': st.session_state.final_title,
                        'excerpt': st.session_state.final_excerpt,
                        'html_content': st.session_state.final_content,
                        'meta_title': st.session_state.final_meta_title,
                        'meta_description': st.session_state.final_meta_desc
                    }
                    new_post = agent_refine(curr_data, refine_inst, st.session_state.claude_model_selection)
                    if new_post:
                        st.session_state.final_title = new_post['title']
                        st.session_state.final_content = new_post['html_content']
                        st.session_state.final_excerpt = new_post['excerpt']
                        st.session_state.final_meta_title = new_post.get('meta_title')
                        st.session_state.final_meta_desc = new_post.get('meta_description')
                        st.rerun()

        if st.button("🚀 Upload Draft to Ghost", type="primary", use_container_width=True):
             tags = ["Elite AI"]
             if st.session_state.transcript_context: tags.append("Context Aware")
             
             final_data = {
                 'title': st.session_state.final_title,
                 'excerpt': st.session_state.final_excerpt,
                 'html_content': st.session_state.final_content,
                 'meta_title': st.session_state.final_meta_title,
                 'meta_description': st.session_state.final_meta_desc
             }
             
             if upload_ghost(final_data, st.session_state.elite_image_v8, tags):
                 st.balloons()
                 st.success("Published to Ghost successfully!")
             else:
                 st.error("Publish failed. Check logs.")

    with tab_social:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("### LinkedIn")
            li_txt = st.text_area("LinkedIn Post", value=socials.get('linkedin', ''), height=300)
            st.link_button("Post to LinkedIn", generate_social_link(li_txt, "linkedin"))

        with c2:
            st.markdown("### X / Twitter Thread")
            tw_data = socials.get('twitter_thread', [])
            if isinstance(tw_data, str): tw_data = [tw_data]
            
            hook_txt = st.text_area("Tweet 1 (Hook)", value=tw_data[0] if tw_data else "", height=100)
            st.link_button("Post Hook to X", generate_social_link(hook_txt, "twitter"))
            
            if len(tw_data) > 1:
                st.caption("Rest of Thread (Copy/Paste as replies):")
                thread_body = "\n\n---\n\n".join(tw_data[1:])
                st.text_area("Thread Body", value=thread_body, height=200)

        with c3:
            st.markdown("### Reddit")
            rd_txt = st.text_area("Reddit Post", value=socials.get('reddit', ''), height=300)
            st.link_button("Post to Reddit", generate_social_link(rd_txt, "reddit"))
