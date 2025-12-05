import streamlit as st
import requests
import jwt # pip install pyjwt
import datetime
import json
import io
import urllib.parse
from anthropic import Anthropic
from pypdf import PdfReader
from docx import Document
from openai import OpenAI
import os

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V8.2", page_icon="🎩", layout="wide")

# --- INITIALIZE SESSION STATE ---
if 'log_events' not in st.session_state:
    st.session_state.log_events = [] # Initialize empty
if 'current_workflow_status' not in st.session_state:
    st.session_state.current_workflow_status = "Awaiting Topic."
if 'claude_model_selection' not in st.session_state:
    st.session_state.claude_model_selection = "claude-sonnet-4-20250514"
if 'last_claude_model' not in st.session_state:
    st.session_state.last_claude_model = "claude-sonnet-4-20250514"
if 'seo_keywords' not in st.session_state:
    st.session_state['seo_keywords'] = ""
if 'elite_blog_v8' not in st.session_state:
    st.session_state['elite_blog_v8'] = None
if 'transcript_context' not in st.session_state:
    st.session_state['transcript_context'] = False


# --- SECRET LOADING ---
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
    # DEEP THINK FIX: Prepend to list (Insert at 0) so the newest is always at the top.
    # This solves the "scrolling" issue by keeping the active log visible without scrolling.
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    st.session_state.log_events.insert(0, f"[{timestamp}] {message}")

# --- INITIALIZE SPECIALISTS ---
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
writer = Anthropic(api_key=ANTHROPIC_API_KEY)

# --- ISOLATE OPENAI CLIENT INITIALIZATION ---
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    openai_client_is_valid = True
    add_log("OpenAI client initialized.")
except Exception:
    openai_client = None
    openai_client_is_valid = False
    add_log("OpenAI client failed. DALL-E/Whisper disabled.")

# --- HELPER FUNCTIONS ---

def extract_text_from_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_text_from_docx(file):
    doc = Document(file)
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text

def transcribe_audio(file):
    global openai_client_is_valid
    if not openai_client_is_valid:
        return "Audio transcription skipped: OpenAI client not initialized."
    
    # DEEP THINK SCAN: OpenAI Whisper limit is 25MB.
    # If the user uploads a 90MB file, this call WILL fail with a 413 error.
    # We catch that specific error to give a helpful message.
    try:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=file
        )
        return transcript.text
    except Exception as e:
        error_str = str(e)
        if "413" in error_str:
            add_log(f"Whisper Error: File too large (>25MB).")
            return "Error: File exceeds OpenAI's 25MB limit. Please compress or split the file."
        add_log(f"Whisper Error: {error_str}")
        return f"Error transcribing audio: {error_str}"

def generate_social_links(text, platform):
    if isinstance(text, bytes): text = text.decode('utf-8')
    elif not isinstance(text, str): text = str(text) 
    encoded_text = urllib.parse.quote(text)
    if platform == "twitter": return f"https://twitter.com/intent/tweet?text={encoded_text}"
    elif platform == "linkedin": return f"https://www.linkedin.com/feed/?shareActive=true&text={encoded_text}"
    elif platform == "reddit": return f"https://www.reddit.com/submit?selftext=true&title=Check%20out%20my%20new%20post&text={encoded_text}"
    return "#"

# --- CORE AGENT FUNCTIONS ---

def create_ghost_token():
    try:
        id, secret = GHOST_ADMIN_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        header = {'alg': 'HS256', 'typ': 'JWT', 'kid': id}
        payload = {'iat': iat, 'exp': iat + (5 * 60), 'aud': '/admin/'}
        return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    except Exception as e:
        add_log(f"Ghost Token Error: {e}")
        return None

def upload_image_to_ghost(image_url):
    add_log(f"Uploading image to Ghost...")
    token = create_ghost_token()
    if not token: return None

    try:
        image_response = requests.get(image_url, stream=True)
        image_response.raise_for_status()
        image_data = image_response.content
        mime_type = image_response.headers.get('Content-Type', 'image/png')
        filename = f"dalle_image_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        files = {'file': (filename, image_data, mime_type)}
    except Exception as e:
        add_log(f"Error downloading image: {e}")
        return None
        
    headers = {'Authorization': f'Ghost {token}'}
    upload_url = f"{GHOST_API_URL}/ghost/api/admin/images/upload/"
    
    try:
        upload_response = requests.post(upload_url, headers=headers, files=files)
        upload_response.raise_for_status()
        uploaded_data = upload_response.json()
        ghost_url = uploaded_data['images'][0]['url']
        add_log(f"Image uploaded successfully.")
        return ghost_url
    except Exception as e:
        add_log(f"Ghost image upload error: {e}")
        return None


def agent_seo_suggestion(topic):
    add_log("Generating keywords...")
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": "You are an SEO expert. Suggest 5-7 high-impact keywords. List only."},
                {"role": "user", "content": f"Topic: {topic}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        add_log(f"SEO Failed: {e}")
        return ""

def agent_research(topic, transcript_context_bool):
    add_log("Agent 1 (Perplexity): Researching...")
    if transcript_context_bool:
        system_prompt = "You are a Fact-Checking Researcher. 1. Research the topic. 2. Verify claims in the user's context. 3. Find external data to validate."
    else:
        system_prompt = "You are an elite academic researcher. Find detailed, factual information. Prioritize accurate data, dates, and technical details."
    
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Research this topic deeply: {topic}"}
            ]
        )
        add_log("Research complete.")
        return response.choices[0].message.content
    except Exception as e:
        add_log(f"Research Failed: {e}")
        return None

def agent_writer(topic, research_notes, style_sample, tone_setting, keywords, audience_setting, transcript_context_bool, transcript_text, claude_model):
    """AGENT 2: THE WRITER (Claude)"""
    add_log(f"Agent 2 (Claude): Drafting content...")
    
    tone_map = {
        "Technical": (0.2, "Focus on technical accuracy, use industry jargon appropriate for experts, be precise."),
        "Professional": (0.5, "Use a clean, corporate, and concise voice. Be authoritative but accessible."),
        "Conversational": (0.7, "Write like a human speaking to a friend. Use contractions, rhetorical questions, and be relatable."),
        "Witty": (0.8, "Use clever wordplay, light humor, and an entertaining voice. Be sharp."),
        "Storyteller": (0.9, "Focus on narrative arc, emotive language, and painting a scene.")
    }
    temperature, tone_instruction = tone_map.get(tone_setting, (0.7, "Professional and engaging."))

    style_instruction = f"TONE: {tone_instruction}"
    if style_sample:
        style_instruction += f"\nSPECIFIC MIMICRY REQUEST: Analyze this writing sample: '{style_sample}'. Adopt the sentence structure and rhythm."

    keyword_instruction = ""
    if keywords:
        keyword_instruction = f"SEO MANDATE: Naturally include: {keywords}."

    # EXPANDED AUDIENCE LOGIC
    audience_desc = audience_setting
    if audience_setting == "Grand Parent":
        audience_desc = "Older adults. Use clear, large metaphors. Avoid modern slang. Be respectful, patient, and clear. Focus on legacy and ease of use."
    elif audience_setting == "Teenager":
        audience_desc = "Gen Z/Alpha. Fast-paced, authentic, maybe minimal slang but not 'cringe'. Focus on identity, social proof, and 'now'."
    elif audience_setting == "Child":
        audience_desc = "Kids (8-12). Simple vocabulary, short sentences, exciting analogies. Focus on fun and curiosity."
    elif audience_setting == "Hobbyist":
        audience_desc = "Passionate amateurs. Focus on the 'love of the craft', practical tips, and community. Less business jargon."
    elif audience_setting == "CEO":
        audience_desc = "High-level executives. ROI-focused, strategic, extremely concise. Bottom-line up front (BLUF)."
    
    audience_instruction = f"AUDIENCE: {audience_desc}."

    context_prompt = ""
    if transcript_context_bool and transcript_text:
        context_prompt = f"CONTEXT (FILE): {transcript_text[:50000]}\nUse the CONTEXT to frame the narrative."

    prompt = f"""
    You are a world-class ghostwriter.
    USER'S MAIN GOAL: "{topic}"
    {context_prompt}
    RESEARCH (VALIDATION): {research_notes}

    INSTRUCTIONS:
    1. Write a blog post addressing the MAIN GOAL.
    2. Use RESEARCH to validate claims.
    3. CRITICAL: **Do not use in-paragraph hyperlinks or citations.** List source URLs at the very bottom under "Sources and Further Reading".
    4. **TONE MANDATE:** Do not give away proprietary 'secret sauce'. Entice the reader to seek further expert consultation (e.g., from 'Sharp Human's services').
    
    *** STRICT FORMATTING RULES ***
    - **NO EMOJIS**. Do not use emojis anywhere in the text.
    - **NO EM-DASHES (—)**. Humans rarely type these on standard keyboards. Use standard hyphens (-) or commas instead. 
    - Write as human as possible.
    
    {style_instruction}
    {keyword_instruction}
    {audience_instruction}
    
    OUTPUT FORMAT:
    Return a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content" (semantic HTML).
    """

    try:
        message = writer.messages.create(
            model=claude_model,
            max_tokens=8000,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text: response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text: response_text = response_text.split("```")[1].split("```")[0]
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Writing Failed: {e}")
        return None

def agent_refiner(current_post_json, user_feedback, claude_model):
    """AGENT 5: THE EDITOR/REFINER"""
    add_log(f"Agent 5 (Claude): Refining content...")
    current_content_str = json.dumps(current_post_json, indent=2)
    
    prompt = f"""
    You are a world-class editorial editor. Refine this draft based on feedback.

    CURRENT DRAFT (JSON):
    {current_content_str}

    USER FEEDBACK:
    {user_feedback}

    INSTRUCTIONS:
    1. Apply ALL user feedback.
    2. **STRICTLY NO EMOJIS**.
    3. **STRICTLY NO EM-DASHES (—)**. Use standard hyphens (-) only.
    4. Maintain the 'Sources and Further Reading' section.
    5. Maintain the original professional ghostwriter style (unless feedback says otherwise).

    OUTPUT FORMAT:
    Return a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content".
    """

    try:
        message = writer.messages.create(
            model=claude_model,
            max_tokens=8000,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text: response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text: response_text = response_text.split("```")[1].split("```")[0]
        add_log("Draft refinement complete.")
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Refinement Failed: {e}")
        return None


def agent_social_media(blog_content, claude_model):
    """AGENT 3: SOCIAL MEDIA"""
    add_log(f"Agent 3 (Claude): Drafting socials...")
    prompt = f"""
    Generate social media posts for this blog.
    1. LinkedIn (Professional, bullet points).
    2. Twitter (Hook).
    3. Reddit (Title + Body).
    
    **NO EMOJIS** in the content unless strictly necessary for the platform style (keep it minimal).
    **NO EM-DASHES**.
    
    BLOG CONTENT: {blog_content[:15000]}...
    
    OUTPUT FORMAT:
    Return a valid JSON object with keys: "linkedin", "twitter", "reddit".
    """
    try:
        message = writer.messages.create(
            model=claude_model,
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text: response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text: response_text = response_text.split("```")[1].split("```")[0]
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Social Media Agent Failed: {e}")
        return {"linkedin": "Error", "twitter": "Error", "reddit": "Error"}

def agent_artist(topic, tone_setting, audience_setting, custom_prompt=None):
    """AGENT 4: THE ARTIST (DALL-E)"""
    add_log("Agent 4 (DALL-E): Creating art...")
    if not openai_client_is_valid: return None
    
    if custom_prompt:
        prompt = f"A high-quality, modern editorial illustration. {custom_prompt} Minimalist, 16:9 aspect ratio. No text."
    else:
        # Dynamic Prompt based on new audiences
        style_modifier = "Minimalist, tech-forward."
        if audience_setting == "Executive": style_modifier = "Abstract concepts of strategy, chess pieces, maps, high-level business metaphors."
        elif audience_setting == "Recruiter": style_modifier = "Human connection, diverse teams, career ladders."
        elif audience_setting == "Grand Parent": style_modifier = "Warm, clear, classic illustration style. Nostalgic but clear."
        elif audience_setting == "Teenager": style_modifier = "Vibrant, neon accents, digital art style, dynamic composition."
        elif audience_setting == "Child": style_modifier = "Bright colors, simple shapes, storybook illustration style, whimsical."
        elif audience_setting == "Hobbyist": style_modifier = "Detailed, workshop aesthetic, tools of the trade, hands-on feel."
        elif audience_setting == "CEO": style_modifier = "Clean architectural lines, upward graphs, marble textures, premium feel."
        
        if tone_setting in ["Witty", "Storyteller"]: style_modifier += " Narrative-driven elements."

        prompt = f"A high-quality, modern editorial illustration about {topic}. {style_modifier} 16:9 aspect ratio. No text."
    
    add_log(f"DALL-E Prompt: {prompt[:50]}...")

    try:
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        add_log("Image URL received.")
        return response.data[0].url
    except Exception as e:
        add_log(f"Image generation failed: {e}")
        return None

def publish_to_ghost(data, image_url, tags):
    add_log("Publishing to Ghost...")
    token = create_ghost_token()
    if not token: return requests.Response()

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
    
    try:
        response = requests.post(url, json=body, headers=headers)
        if response.status_code in [200, 201]:
            add_log("Draft successfully published!")
        else:
            add_log(f"Publish Failed: {response.status_code}")
        return response
    except Exception as e:
        add_log(f"Publish connection error: {e}")
        return requests.Response()

# --- UI LAYOUT ---

st.title("🎩 Elite AI Blog Agent V8.2 (Human-Optimized)")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

# --- STATUS DASHBOARD ---
st.subheader("Workflow Status")
col_tech, col_user, col_log = st.columns(3)

with col_tech:
    st.markdown("**1. Technical Stack**")
    writer_model = st.session_state.get('last_claude_model', 'N/A')
    st.info(f"Writer: {writer_model}\nResearch: Perplexity (Sonar)")

with col_user:
    st.markdown("**2. User Workflow Status**")
    st.warning(st.session_state.current_workflow_status)
    
with col_log:
    st.markdown("**3. Live Logging**")
    # Newest logs are at index 0, so no need to scroll down.
    log_content = "\n".join(st.session_state.log_events)
    st.text_area("Log History (Newest First)", value=log_content, height=150, disabled=True, key="log_display_area")

# SIDEBAR
with st.sidebar:
    st.header("Configuration")
    if not openai_client_is_valid: st.error("OpenAI Key failed.")
        
    style_sample = st.text_area("Your Writing Style Sample", height=100, placeholder="Paste a previous blog post...")
    st.divider()
    
    st.subheader("Tone & Voice")
    tone_setting = st.select_slider("Choose your vibe:", options=["Technical", "Professional", "Conversational", "Witty", "Storyteller"], value="Conversational")

    st.divider()
    st.subheader("Target Audience")
    # UPDATED AUDIENCE LIST
    audience_setting = st.selectbox("Who is reading this post?", 
        options=[
            "General Public", "Developer (Technical)", "Executive (Strategy/ROI)", "Recruiter (Career/Skills)",
            "Grand Parent", "Teenager", "Child", "Hobbyist", "CEO"
        ], 
        index=0, key="audience_setting_select")

    st.divider()
    st.subheader("🛠️ Debugging")
    st.selectbox("Claude Model:", options=["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus", "claude-3-sonnet"], index=0, key='claude_model_selection')

claude_model_select = st.session_state.get('claude_model_selection', "claude-sonnet-4-20250514")


# MAIN INPUT AREA
# UI FIX: Moved File Uploader to a full-width container for better usability
topic = st.text_input("Main Blog Topic / Prompt", placeholder="e.g. Guide on 'Scaling Databases'...")

# LARGE FILE AREA
with st.container():
    st.caption("Attach Context (Audio/Video/Docs) - Max 100MB")
    # FILE SIZE FIX: Note that Streamlit limit is usually 200MB default, but we check audio strictly for OpenAI
    uploaded_file = st.file_uploader("", type=['txt', 'md', 'pdf', 'docx', 'mp3', 'mp4', 'm4a', 'mpeg', 'wav'])

col_seo_btn, col_seo_txt = st.columns([1, 3])
with col_seo_btn:
    st.write("") # Spacer
    st.write("")
    if st.button("✨ Suggest Keywords"):
        if not topic: st.toast("Enter topic first!")
        else:
            with st.spinner("Analyzing SEO..."):
                st.session_state['seo_keywords'] = agent_seo_suggestion(topic)

with col_seo_txt:
    keywords = st.text_input("Target SEO Keywords", value=st.session_state.get('seo_keywords', ''), key='seo_keywords_input')
    st.session_state['seo_keywords'] = st.session_state['seo_keywords_input']

st.divider()

if st.button("Start Elite Workflow", type="primary", use_container_width=True):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        st.session_state.log_events = ["Workflow started."]
        st.session_state.current_workflow_status = "Processing Files..."
        st.session_state.last_claude_model = claude_model_select
        
        # Reset context flag
        st.session_state['transcript_context'] = False 
        transcript_text = None
        
        if uploaded_file:
            file_type = uploaded_file.name.split('.')[-1].lower()
            # FILE SIZE UPDATE: 100MB limit check
            if uploaded_file.size > 100 * 1024 * 1024:
                st.error("File is too large (>100MB).")
                uploaded_file = None
            
            if uploaded_file:
                with st.status(f"📂 Reading Context...", expanded=True) as status:
                    try:
                        if file_type == 'pdf': transcript_text = extract_text_from_pdf(uploaded_file)
                        elif file_type == 'docx': transcript_text = extract_text_from_docx(uploaded_file)
                        elif file_type in ['txt', 'md']: transcript_text = uploaded_file.read().decode("utf-8")
                        elif file_type in ['mp3', 'mp4', 'm4a', 'wav']:
                            # Whisper check inside function will handle >25MB errors gracefully
                            transcript_text = transcribe_audio(uploaded_file)
                            
                        if transcript_text and "Error" not in transcript_text: 
                            st.write(f"✅ Context Loaded.")
                            st.session_state['transcript_context'] = True 
                        else: 
                            # If it was a size error, the function returned a friendly error string
                            st.warning(transcript_text) 
                    except Exception as e:
                        st.error(f"File error: {e}")
                        st.stop()
                    status.update(label="Context Ready!", state="complete", expanded=False)

        # 1. RESEARCH
        st.session_state.current_workflow_status = "Researching..."
        with st.status("🕵️ Agent 1: Researching...", expanded=True) as status:
            research_data = agent_research(topic, st.session_state['transcript_context']) 
            if not research_data: st.stop()
            
            # 2. WRITING
            st.session_state.current_workflow_status = "Drafting..."
            status.update(label=f"✍️ Agent 2: Writing ({tone_setting})...", state="running")
            blog_post = agent_writer(topic, research_data, style_sample, tone_setting, keywords, audience_setting, st.session_state['transcript_context'], transcript_text, claude_model_select)
            if blog_post: st.session_state['elite_blog_v8'] = blog_post
            else: st.stop()
            
            # 3. SOCIALS
            st.session_state.current_workflow_status = "Socials..."
            status.update(label="📱 Agent 3: Socials...", state="running")
            st.session_state['elite_socials'] = agent_social_media(blog_post['html_content'], claude_model_select)
            
            # 4. ART
            st.session_state.current_workflow_status = "Art..."
            status.update(label="🎨 Agent 4: Painting...", state="running")
            temp_image_url = agent_artist(topic, tone_setting, audience_setting)
            
            if temp_image_url:
                status.update(label="☁️ Uploading Image...", state="running")
                st.session_state['elite_image_v8'] = upload_image_to_ghost(temp_image_url) or temp_image_url
            
            st.session_state.current_workflow_status = "Done."
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW AREA
if st.session_state['elite_blog_v8']:
    post = st.session_state['elite_blog_v8']
    socials = st.session_state.get('elite_socials', {})
    img_url = st.session_state.get('elite_image_v8', '')
    
    st.divider()
    c1, c2 = st.columns([3, 1])
    with c1: st.subheader("Review & Publish")

    # --- REFINEMENT SECTION ---
    st.markdown("### 🔄 Refine Draft")
    refine_col1, refine_col2 = st.columns([3, 1])
    with refine_col1:
        refinement_feedback = st.text_input("Instructions (e.g., 'Make it punchier', 'Fix the intro')", key='refinement_feedback_input')
    with refine_col2:
        if st.button("✨ Refine", type="secondary", disabled=not refinement_feedback):
            with st.spinner("Refining..."):
                current_data = {
                    'title': st.session_state.get('final_title', post.get('title')),
                    'excerpt': st.session_state.get('final_excerpt', post.get('excerpt')),
                    'html_content': st.session_state.get('final_content', post.get('html_content')),
                    'meta_title': st.session_state.get('final_meta_title', post.get('meta_title')),
                    'meta_description': st.session_state.get('final_meta_desc', post.get('meta_description'))
                }
                refined_post = agent_refiner(current_data, refinement_feedback, claude_model_select)
                if refined_post:
                    st.session_state['elite_blog_v8'] = refined_post
                    # CRITICAL FIX: Update the specific widget keys so the inputs refresh
                    st.session_state['final_title'] = refined_post['title']
                    st.session_state['final_excerpt'] = refined_post['excerpt']
                    st.session_state['final_content'] = refined_post['html_content']
                    st.session_state['final_meta_title'] = refined_post['meta_title']
                    st.session_state['final_meta_desc'] = refined_post['meta_description']
                    st.rerun()

    st.divider()

    # TABS
    tab_blog, tab_social = st.tabs(["📝 Blog Post", "📱 Social Media Pack"])

    with tab_blog:
        col1, col2 = st.columns([1, 2])
        with col1:
            if img_url: 
                st.image(img_url, caption="Feature Image", use_container_width=True)
                
                # --- REGENERATE IMAGE SECTION ---
                with st.expander("🔄 Regenerate Image"):
                    custom_img_prompt = st.text_input("Custom Image Prompt", placeholder="e.g. A futuristic city made of code...")
                    if st.button("Regenerate Art"):
                        with st.spinner("Painting new image..."):
                            new_url = agent_artist(topic, tone_setting, audience_setting, custom_prompt=custom_img_prompt)
                            if new_url:
                                hosted_url = upload_image_to_ghost(new_url) or new_url
                                st.session_state['elite_image_v8'] = hosted_url
                                st.session_state['final_img_url'] = hosted_url
                                st.rerun()
            else: 
                st.info("No image generated.")
                
        with col2:
            final_img = st.text_input("Feature Image URL", value=img_url or "", key='final_img_url')

        # Content Inputs
        title = st.text_input("Title", value=post.get('title', ''), key='final_title')
        
        # --- PREVIEW TOGGLE ---
        with st.expander("👁️ View Rendered Post (Preview)", expanded=True):
             st.markdown(st.session_state.get('final_content', post.get('html_content', '')), unsafe_allow_html=True)
        
        content = st.text_area("HTML Content (Edit Here)", value=post.get('html_content', ''), height=400, key='final_content')
        excerpt = st.text_input("Excerpt", value=post.get('excerpt', ''), key='final_excerpt')
        
        with st.expander("SEO Metadata"):
            meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''), key='final_meta_title')
            meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''), key='final_meta_desc')

        if st.button("🚀 Upload Draft to Ghost", type="primary"):
            with st.spinner("Uploading..."):
                final_post_data = {
                    'title': st.session_state['final_title'], 
                    'excerpt': st.session_state['final_excerpt'], 
                    'meta_title': st.session_state['final_meta_title'], 
                    'meta_description': st.session_state['final_meta_desc'], 
                    'html_content': st.session_state['final_content']
                }
                
                tags = ["Elite AI"]
                # FIX: Use session state variable safely
                if st.session_state.get('transcript_context', False): tags.append("Context Aware")
                
                result = publish_to_ghost(final_post_data, st.session_state['final_img_url'], tags)
                if result.status_code in [200, 201]:
                    st.balloons()
                    st.success("Draft created in Ghost!")
                    st.markdown(f"[Open Ghost Admin]({GHOST_API_URL}/ghost/#/posts)")
                else:
                    st.error(f"Error: {result.text}")

    with tab_social:
        st.info("Social Media Drafts")
        li_text = socials.get('linkedin', '')
        st.text_area("LinkedIn", value=li_text, height=150)
        st.link_button("Post LinkedIn", generate_social_links(li_text, "linkedin"))
        st.divider()
        tw_text = socials.get('twitter', '')
        st.text_area("X / Twitter", value=tw_text, height=100)
        st.link_button("Post X", generate_social_links(tw_text, "twitter"))
        st.divider()
        rd_text = socials.get('reddit', '')
        st.text_area("Reddit", value=rd_text, height=100)
        st.link_button("Post Reddit", generate_social_links(rd_text, "reddit"))
