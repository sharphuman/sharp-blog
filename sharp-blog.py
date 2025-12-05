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

# --- CONFIGURATION ---
st.set_page_config(page_title="Elite AI Blog Agent V9.1", page_icon="🎩", layout="wide")

# --- CSS TWEAKS FOR LAYOUT ---
st.markdown("""
<style>
    .stTextArea textarea {
        font-size: 16px !important;
    }
    .stSelectbox div[data-baseweb="select"] > div {
        font-size: 16px !important;
    }
    div[data-testid="stExpander"] div[role="button"] p {
        font-size: 1.1rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'log_events' not in st.session_state: st.session_state.log_events = []
if 'current_workflow_status' not in st.session_state: st.session_state.current_workflow_status = "Awaiting Input."
if 'claude_model_selection' not in st.session_state: st.session_state.claude_model_selection = "claude-sonnet-4-20250514"
if 'last_claude_model' not in st.session_state: st.session_state.last_claude_model = "claude-sonnet-4-20250514"
if 'seo_keywords' not in st.session_state: st.session_state['seo_keywords'] = ""
if 'elite_blog_v8' not in st.session_state: st.session_state['elite_blog_v8'] = None
if 'transcript_context' not in st.session_state: st.session_state['transcript_context'] = False

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

# --- CLIENTS ---
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
writer = Anthropic(api_key=ANTHROPIC_API_KEY)
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    openai_client_is_valid = True
    add_log("OpenAI client initialized.")
except:
    openai_client = None
    openai_client_is_valid = False
    add_log("OpenAI Client Failed.")

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
        if "413" in str(e): return "Error: File >25MB (OpenAI Limit)."
        return f"Error: {e}"

def generate_social_link(text, platform):
    # Truncate for URL safety limits
    if platform == "twitter":
        safe_text = urllib.parse.quote(text[:2500]) 
        return f"https://twitter.com/intent/tweet?text={safe_text}"
    elif platform == "linkedin":
        safe_text = urllib.parse.quote(text[:2000])
        return f"https://www.linkedin.com/feed/?shareActive=true&text={safe_text}"
    elif platform == "reddit":
        safe_text = urllib.parse.quote(text[:3000])
        return f"https://www.reddit.com/submit?selftext=true&title=New%20Post&text={safe_text}"
    return "#"

# --- AGENTS ---

def agent_seo(topic):
    try:
        res = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Suggest 5-7 high-impact SEO keywords for: {topic}. Comma separated."}]
        )
        return res.choices[0].message.content
    except: return ""

def agent_research(topic, context):
    add_log("Agent 1: Researching...")
    sys_prompt = "You are a Fact-Checking Researcher." if context else "You are an elite academic researcher."
    try:
        res = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Research: {topic}"}]
        )
        return res.choices[0].message.content
    except Exception as e:
        add_log(f"Research Failed: {e}")
        return None

def agent_writer(topic, research, style, tone, keywords, audience, context_txt, model):
    add_log("Agent 2: Writing...")
    
    aud_map = {
        "Grand Parent": "Simple metaphors, respectful, clear, large concepts.",
        "Teenager": "Fast-paced, authentic, minimal slang, focus on identity.",
        "Child": "Simple words, short sentences, exciting analogies.",
        "CEO": "ROI-focused, strategic, concise (BLUF).",
        "Hobbyist": "Passionate, detailed, practical tips.",
        "Developer": "Technical depth, code concepts.",
        "Executive": "Strategic impact, business outcomes.",
        "General Public": "Accessible, clear, relatable."
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

    RULES:
    1. NO EMOJIS in body text.
    2. NO EM-DASHES (—). Use hyphens (-).
    3. No inline links. List "Sources" at the end.
    4. Human-like flow. Short paragraphs.
    5. **EXCERPT must be under 280 characters.**
    
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
    add_log("Agent 3: Socials...")
    prompt = f"""
    Create social posts based on this blog.
    1. LinkedIn: Professional, bullets.
    2. Twitter/X: A THREAD of 3-5 tweets. 
       - Tweet 1: Hook/Attention grabber.
       - Tweet 2-4: Key insights.
       - Tweet 5: Call to action.
    3. Reddit: Engaging Title + Body.

    OUTPUT: JSON with keys: "linkedin", "twitter_thread" (Array of strings), "reddit".
    """
    try:
        msg = writer.messages.create(
            model=model, max_tokens=2000, temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        txt = msg.content[0].text
        if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
        return json.loads(txt)
    except: return {}

def agent_artist(topic, tone, audience, custom_prompt=None):
    add_log("Agent 4: Generating Image...")
    if not openai_client_is_valid: return None
    
    if custom_prompt:
        base_prompt = custom_prompt
    else:
        base_prompt = f"A visualization of {topic}"

    visual_style = "High-end editorial photography, shallow depth of field, Leica M11 style."
    if "Teenager" in audience or "Child" in audience:
        visual_style = "Vibrant 3D render, Pixar-style lighting, soft shapes, high saturation."
    elif "Technical" in tone or "Developer" in audience:
        visual_style = "Abstract isometric data visualization, glassmorphism, dark mode cyber aesthetic, Unreal Engine 5 render."
    elif "History" in tone or "Grand Parent" in audience:
        visual_style = "Oil painting style, warm lighting, textured canvas detail."

    full_prompt = f"{base_prompt}. {visual_style} No text, no words, 16:9 aspect ratio, high resolution, cinematic lighting."
    
    try:
        res = openai_client.images.generate(model="dall-e-3", prompt=full_prompt, size="1024x1024", quality="standard", n=1)
        return res.data[0].url
    except Exception as e:
        add_log(f"Art Error: {e}")
        return None

def agent_refine(data, feedback, model):
    add_log("Agent 5: Refining...")
    prompt = f"""
    Refine this blog post.
    CURRENT DATA: {json.dumps(data)}
    FEEDBACK: {feedback}
    RULES: Keep HTML format. No Emojis. No Em-dashes. **Excerpt must be < 280 chars**.
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

        # --- FIX: HARD TRUNCATE EXCERPT TO 300 CHARS ---
        safe_excerpt = data['excerpt'][:300] if data['excerpt'] else ""

        body = {
            "posts": [{
                "title": data['title'], 
                "html": data['html_content'], 
                "feature_image": final_img,
                "custom_excerpt": safe_excerpt, # <--- SAFETY FIX HERE
                "status": "draft", 
                "tags": [{"name": t} for t in tags],
                "meta_title": data.get('meta_title'), 
                "meta_description": data.get('meta_description')
            }]
        }
        res = requests.post(f"{GHOST_API_URL}/ghost/api/admin/posts/?source=html", json=body, headers={'Authorization': f'Ghost {token}'})
        
        if res.status_code != 201:
            add_log(f"Ghost Upload Error: {res.text}")
            
        return res.status_code == 201
    except Exception as e:
        add_log(f"Ghost Error: {e}")
        return False

# --- LAYOUT CONSTRUCTION ---

st.title("🎩 Elite AI Blog Agent V9.1")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# MAIN COLUMNS
left_col, right_col = st.columns([2, 1])

# --- LEFT COLUMN (INPUTS) ---
with left_col:
    st.subheader("📝 Content Strategy")
    
    col_style, col_tone = st.columns(2)
    with col_style:
        style_sample = st.text_area("Your Writing Style Sample", height=100, placeholder="Paste a previous blog post to mimic...")
    with col_tone:
        tone_setting = st.selectbox("Tone & Voice", ["Conversational", "Technical", "Professional", "Witty", "Storyteller", "Journalistic"])
        audience_setting = st.selectbox("Target Audience", [
            "General Public", "Developer (Technical)", "Executive (Strategy/ROI)", "Recruiter (Career/Skills)",
            "Grand Parent", "Teenager", "Child", "Hobbyist", "CEO"
        ])

    st.markdown("##### 💡 Main Topic / Prompt")
    topic = st.text_area("Enter your detailed prompt here...", height=150, placeholder="e.g. A comprehensive guide on...")
    
    st.markdown("##### 🔑 SEO Keywords")
    col_key_btn, col_key_txt = st.columns([1, 4])
    with col_key_btn:
        st.write("")
        st.write("")
        if st.button("✨ Suggest"):
            if topic:
                with st.spinner("Thinking..."):
                    st.session_state['seo_keywords'] = agent_seo(topic)
    with col_key_txt:
        keywords = st.text_area("Keywords (Comma separated)", value=st.session_state.get('seo_keywords', ''), height=68)
        st.session_state['seo_keywords'] = keywords

    uploaded_file = st.file_uploader("Attach Context (Max 100MB)", type=['txt','pdf','docx','mp3','mp4'])

    st.write("")
    if st.button("🚀 Start Elite Workflow", type="primary", use_container_width=True):
        if not topic:
            st.warning("Please enter a topic.")
        else:
            st.session_state.log_events = ["Workflow started."]
            st.session_state.current_workflow_status = "Reading Files..."
            st.session_state.transcript_context = False
            transcript_txt = None
            
            if uploaded_file:
                if uploaded_file.size > 100 * 1024 * 1024: st.error("File too large.")
                else:
                    if uploaded_file.name.endswith(('.mp3','.mp4','.wav','.m4a')):
                         transcript_txt = transcribe_audio(uploaded_file)
                    else:
                         transcript_txt = extract_text(uploaded_file)
                    
                    if transcript_txt and "Error" not in transcript_txt:
                        st.session_state.transcript_context = True
                        add_log("Context Loaded.")
            
            st.session_state.current_workflow_status = "Researching..."
            research_data = agent_research(topic, st.session_state.transcript_context)
            if research_data:
                st.session_state.current_workflow_status = "Drafting..."
                blog = agent_writer(topic, research_data, style_sample, tone_setting, keywords, audience_setting, transcript_txt, st.session_state.claude_model_selection)
                if blog:
                    st.session_state.elite_blog_v8 = blog
                    st.session_state.current_workflow_status = "Socials..."
                    st.session_state.elite_socials = agent_socials(blog['html_content'], st.session_state.claude_model_selection)
                    st.session_state.current_workflow_status = "Art..."
                    img = agent_artist(topic, tone_setting, audience_setting)
                    if img: st.session_state.elite_image_v8 = img
                    st.session_state.current_workflow_status = "Done."
                    st.rerun()


# --- RIGHT COLUMN (STATUS & DEBUG) ---
with right_col:
    st.subheader("⚙️ System Status")
    st.info(f"Status: {st.session_state.current_workflow_status}")
    st.markdown("**📜 Live Logs**")
    st.text_area("", value="\n".join(st.session_state.log_events), height=300, disabled=True, key="logs_display")
    with st.expander("🛠️ Technical Stack & Debug"):
        st.caption(f"Writer Model: {st.session_state.last_claude_model}")
        st.caption("Research: Perplexity Sonar")
        st.caption("Art: DALL-E 3 (Editorial Mode)")
        st.selectbox("Change Writer Model:", ["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus"], key="claude_model_selection")


# --- RESULTS AREA (Full Width) ---
if st.session_state.elite_blog_v8:
    post = st.session_state.elite_blog_v8
    socials = st.session_state.get('elite_socials', {})
    
    st.divider()
    
    tab_blog, tab_social = st.tabs(["📝 Blog Editor", "📱 Social Media Pack"])

    with tab_blog:
        col_preview, col_edit = st.columns([1, 1])
        
        with col_preview:
            st.subheader("👁️ Preview")
            if st.session_state.get('elite_image_v8'):
                st.image(st.session_state.elite_image_v8, use_container_width=True)
                with st.expander("🎨 Regenerate Image"):
                    new_prompt = st.text_input("Custom Prompt")
                    if st.button("Regenerate"):
                        new_url = agent_artist(topic, tone_setting, audience_setting, new_prompt)
                        if new_url: 
                            st.session_state.elite_image_v8 = new_url
                            st.rerun()

            st.markdown(f"# {post.get('title')}")
            st.markdown(f"*{post.get('excerpt')}*")
            st.markdown("---")
            st.markdown(st.session_state.get('final_content', post.get('html_content', '')), unsafe_allow_html=True)

        with col_edit:
            st.subheader("✏️ Editor")
            with st.expander("SEO Metadata", expanded=False):
                meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''), key='final_meta_title')
                meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''), key='final_meta_desc')

            title = st.text_input("Title", value=post.get('title', ''), key='final_title')
            # --- FIX: ADDED max_chars TO EXCERPT ---
            excerpt = st.text_area("Excerpt (Max 300 chars)", value=post.get('excerpt', ''), height=100, max_chars=300, key='final_excerpt')
            content = st.text_area("HTML Content", value=post.get('html_content', ''), height=600, key='final_content')

        st.divider()
        st.subheader("🔄 Refine Draft")
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
                        st.session_state.elite_blog_v8 = new_post
                        st.session_state.final_content = new_post['html_content'] 
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
                 st.success("Published to Ghost!")
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
