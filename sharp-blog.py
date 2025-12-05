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
import os # Import os for environment variable fallback

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V8 (3-Agent System)", page_icon="🎩", layout="wide")

# --- INITIALIZE SESSION STATE ---
if 'log_events' not in st.session_state:
    st.session_state.log_events = ["System Initialized. Ready for input."]
if 'current_workflow_status' not in st.session_state:
    st.session_state.current_workflow_status = "Awaiting Topic."
# Initialize a safe key for the Claude model selection
if 'claude_model_selection' not in st.session_state:
    st.session_state.claude_model_selection = "claude-sonnet-4-20250514"
if 'last_claude_model' not in st.session_state:
    st.session_state.last_claude_model = "claude-sonnet-4-20250514"
if 'seo_keywords' not in st.session_state:
    st.session_state['seo_keywords'] = ""
if 'elite_blog_v8' not in st.session_state:
    st.session_state['elite_blog_v8'] = None


# --- SECRET LOADING (Centralized and robust) ---
try:
    # Ghost Credentials
    GHOST_ADMIN_KEY = st.secrets.get("GHOST_ADMIN_API_KEY") or os.environ["GHOST_ADMIN_API_KEY"]
    GHOST_API_URL = (st.secrets.get("GHOST_API_URL") or os.environ["GHOST_API_URL"]).rstrip('/')
    
    # AI Credentials
    PPLX_API_KEY = st.secrets.get("PERPLEXITY_API_KEY") or os.environ["PERPLEXITY_API_KEY"]
    ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"]
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"]
    
except KeyError as e:
    st.error(f"❌ Missing Secret: {e}. Please set all five keys in `st.secrets` or environment variables.")
    # Use st.stop() to prevent further execution if keys are missing
    st.stop()


def add_log(message):
    st.session_state.log_events.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}")
    # We keep all logs in session state now for the full scrollable view

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
    try:
        # Note: file must be a file-like object with a name attribute, or a temp file wrapper
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=file
        )
        return transcript.text
    except Exception as e:
        add_log(f"Whisper Error: {str(e)}")
        return f"Error transcribing audio (OpenAI API Issue): {str(e)}"

# --- FIX: Ensure the input is always a string before URL encoding ---
def generate_social_links(text, platform):
    # Defensive programming: ensure text is a string to prevent TypeError on quoting
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    elif not isinstance(text, str):
        text = str(text) 

    encoded_text = urllib.parse.quote(text)
    if platform == "twitter":
        return f"https://twitter.com/intent/tweet?text={encoded_text}"
    elif platform == "linkedin":
        return f"https://www.linkedin.com/feed/?shareActive=true&text={encoded_text}"
    elif platform == "reddit":
        return f"https://www.reddit.com/submit?selftext=true&title=Check%20out%20my%20new%20post&text={encoded_text}"
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

# --- NEW: Function to download DALL-E image and upload it to Ghost ---
def upload_image_to_ghost(image_url):
    """Downloads image from DALL-E URL and uploads binary data to Ghost's image endpoint."""
    add_log(f"Attempting to upload image from {image_url[:40]}... to Ghost.")
    token = create_ghost_token()
    if not token:
        add_log("Image upload failed: Could not generate Ghost token.")
        return None

    # 1. Download the image data
    try:
        image_response = requests.get(image_url, stream=True)
        image_response.raise_for_status()
        image_data = image_response.content
        mime_type = image_response.headers.get('Content-Type', 'image/png') # Default to PNG
        file_extension = mime_type.split('/')[-1]
        filename = f"dalle_image_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.{file_extension}"
        
        # Use simple in-memory binary data for uploading (Ghost handles optimization)
        files = {'file': (filename, image_data, mime_type)}
    except Exception as e:
        add_log(f"Error downloading image: {e}")
        return None
        
    # 2. Upload the binary data to Ghost image endpoint
    headers = {'Authorization': f'Ghost {token}'}
    upload_url = f"{GHOST_API_URL}/ghost/api/admin/images/upload/"
    
    try:
        upload_response = requests.post(upload_url, headers=headers, files=files)
        upload_response.raise_for_status()
        
        uploaded_data = upload_response.json()
        ghost_url = uploaded_data['images'][0]['url']
        add_log(f"Image successfully uploaded to Ghost. URL: {ghost_url[:40]}...")
        return ghost_url
    except requests.exceptions.HTTPError as http_err:
        add_log(f"Ghost image upload HTTP error: {http_err}. Response: {upload_response.text[:100]}")
        st.error(f"Ghost image upload failed. Check Ghost API permissions. Status: {upload_response.status_code}")
        return None
    except Exception as e:
        add_log(f"Ghost image upload error: {e}")
        return None


def agent_seo_suggestion(topic):
    """AGENT 0: THE SEO STRATEGIST (Perplexity)"""
    add_log("Starting SEO Keyword Suggestion...")
    system_prompt = "You are an SEO expert. Given a topic, suggest 5-7 high-impact, relevant keywords or phrases separated by commas. Do not explain, just list them."
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Topic: {topic}"}
            ]
        )
        add_log("SEO Keywords generated by Perplexity.")
        return response.choices[0].message.content
    except Exception as e:
        add_log(f"SEO Suggestion Failed: {e}")
        return ""

def agent_research(topic, transcript_context=None):
    """AGENT 1: THE RESEARCHER & TRUTH VALIDATOR (Perplexity)"""
    add_log("Agent 1 (Perplexity) starting research phase...")
    if transcript_context:
        system_prompt = "You are a specialized Fact-Checking Researcher. The user has provided context in a file. Your job is to: 1. Research the main topic. 2. Verify claims or assumptions that might be relevant. 3. Find external data/stats to validate the user's premise."
    else:
        system_prompt = "You are an elite academic researcher. Find detailed, factual information on the given topic. Prioritize accurate data, dates, and technical details. Validate all claims with recent sources."
    
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Research this topic deeply: {topic}"}
            ]
        )
        add_log("Research data fetched successfully.")
        # Note: Perplexity often embeds citations/sources within the response text, 
        # which the Writer Agent will be instructed to extract and reformat.
        return response.choices[0].message.content
    except Exception as e:
        add_log(f"Research Agent Failed: {e}")
        st.error(f"Research Agent Failed: {e}")
        return None

# --- UPDATED: Source Citation and Tone Mandates ---
def agent_writer(topic, research_notes, style_sample, tone_setting, keywords, audience_setting, transcript_context=None, transcript_text=None, claude_model="claude-sonnet-4-20250514"):
    """AGENT 2: THE WRITER (Claude)"""
    # Use a local variable to ensure the model argument is respected
    final_claude_model = claude_model
    add_log(f"Agent 2 (Claude) starting content drafting using model: {final_claude_model}")
    
    tone_map = {
        "Technical": (0.2, "Focus on technical accuracy, use industry jargon appropriate for experts, be precise and dense."),
        "Professional": (0.5, "Use a clean, corporate, and concise voice. Be authoritative but accessible."),
        "Conversational": (0.7, "Write like a human speaking to a friend. Use contractions, rhetorical questions, and be relatable."),
        "Witty": (0.8, "Use clever wordplay, light humor, and an entertaining voice. Be sharp and engaging."),
        "Storyteller": (0.9, "Focus on narrative arc, emotive language, and painting a scene. Use metaphors and storytelling elements.")
    }
    
    temperature, tone_instruction = tone_map.get(tone_setting, (0.7, "Professional and engaging."))

    # 1. Style Instruction (User sample overrides generic tone if provided)
    style_instruction = f"TONE: {tone_instruction}"
    if style_sample:
        style_instruction += f"""
        \nSPECIFIC MIMICRY REQUEST:
        Analyze this writing sample: "{style_sample}"
        Adopt the sentence structure, vocabulary, and rhythm of this sample, while maintaining the '{tone_setting}' vibe.
        """

    # 2. Keyword Instruction
    keyword_instruction = ""
    if keywords:
        keyword_instruction = f"""
        SEO MANDATE:
        You MUST naturally include the following keywords in the text: {keywords}.
        Do not stuff them; use them where they fit logically for search optimization.
        """

    # 3. Audience Instruction
    audience_instruction = ""
    if audience_setting == "Developer (Technical)":
        audience_instruction = "AUDIENCE: Developer. Use technical depth, code examples (in Markdown format), and focus on implementation details."
    elif audience_setting == "Executive (Strategy/ROI)":
        audience_instruction = "AUDIENCE: Executive. Focus on strategic impact, return on investment (ROI), business outcomes, and high-level summaries. Avoid deep technical jargon."
    elif audience_setting == "Recruiter (Career/Skills)":
        audience_instruction = "AUDIENCE: Recruiter. Focus on relevant skills, industry trends related to hiring, and career progression. Emphasize transferable skills."
    elif audience_setting == "General Public":
        audience_instruction = "AUDIENCE: General Public. Use clear, accessible language, define any complex terms, and focus on relatable real-world impact."

    # 4. Source Logic and Secret Sauce Mandates
    if transcript_text:
        safe_transcript = transcript_text[:50000]
        source_material_instruction = f"""
        USER'S MAIN GOAL: "{topic}"
        CONTEXT (FILE): {safe_transcript}
        RESEARCH (VALIDATION): {research_notes}

        INSTRUCTIONS:
        1. Write a blog post addressing the MAIN GOAL.
        2. Use the CONTEXT to frame the problem/narrative (e.g. "As discussed...").
        3. Use RESEARCH to validate claims and add external credibility.
        4. CRITICAL: **Do not use in-paragraph hyperlinks or citations.** Instead, extract the main source URLs (if any exist in RESEARCH) and list them clearly at the very bottom of the HTML content under a section titled "Sources and Further Reading".
        5. **TONE MANDATE:** Do not give away proprietary or overly technical 'secret sauce'. Entice the reader to seek further expert consultation (e.g., from 'Sharp Human's services') for implementation or advanced solutions.
        """
    else:
        source_material_instruction = f"""
        USER'S MAIN GOAL: "{topic}"
        RESEARCH (VALIDATION): {research_notes}
        INSTRUCTIONS: Write a blog post about "{topic}" based on the research.
        4. CRITICAL: **Do not use in-paragraph hyperlinks or citations.** Instead, extract the main source URLs (if any exist in RESEARCH) and list them clearly at the very bottom of the HTML content under a section titled "Sources and Further Reading".
        5. **TONE MANDATE:** Do not give away proprietary or overly technical 'secret sauce'. Entice the reader to seek further expert consultation (e.g., from 'Sharp Human's services') for implementation or advanced solutions.
        """

    prompt = f"""
    You are a world-class ghostwriter.
    {source_material_instruction}
    {style_instruction}
    {keyword_instruction}
    {audience_instruction}
    
    OUTPUT FORMAT:
    Return a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content" (semantic HTML).
    """

    try:
        message = writer.messages.create(
            model=final_claude_model, # Using the selected model
            max_tokens=8000,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
            
        add_log("Content drafting complete.")
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Writing Failed: {e}")
        st.error(f"Writer Agent Failed: {e}")
        return None

# --- NEW AGENT: Refinement Loop ---
def agent_refiner(current_post_json, user_feedback, claude_model="claude-sonnet-4-20250514"):
    """AGENT 5: THE EDITOR/REFINER (Claude)"""
    add_log(f"Agent 5 (Claude) refining content based on feedback.")
    
    # Use the current post data stringified
    current_content_str = json.dumps(current_post_json, indent=2)
    
    prompt = f"""
    You are a world-class editorial editor, tasked with refining a draft blog post based on user feedback.

    CURRENT DRAFT (JSON):
    {current_content_str}

    USER FEEDBACK / REFINEMENT INSTRUCTIONS:
    {user_feedback}

    INSTRUCTIONS:
    1. Apply ALL user feedback to the current draft (TITLE, METADATA, HTML_CONTENT, etc.).
    2. Maintain the original professional ghostwriter style.
    3. Ensure the output is a VALID, complete JSON object.
    4. CRITICAL: **Maintain all previous tone and citation mandates.** The final HTML content MUST NOT contain in-paragraph hyperlinks and MUST contain a "Sources and Further Reading" section at the end. The tone should entice the reader to seek further services (e.g., from 'Sharp Human's services').

    OUTPUT FORMAT:
    Return a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content" (semantic HTML).
    """

    try:
        message = writer.messages.create(
            model=claude_model,
            max_tokens=8000,
            temperature=0.4, # Lower temperature for editing stability
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
            
        add_log("Draft refinement complete.")
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Refinement Failed: {e}")
        st.error(f"Refinement Agent Failed: {e}")
        return None


# --- UPDATED: Default model is now "claude-sonnet-4-20250514" ---
def agent_social_media(blog_content, claude_model="claude-sonnet-4-20250514"):
    """AGENT 3: THE SOCIAL MEDIA MANAGER (Claude)"""
    # Use a local variable to ensure the model argument is respected
    final_claude_model = claude_model
    add_log(f"Agent 3 (Claude) drafting social posts using model: {final_claude_model}")
    
    prompt = f"""
    You are a expert social media manager. Based on this blog post content, generate:
    1. A LinkedIn Post (professional, engaging, bullet points).
    2. A Twitter Thread (Just the first tweet hook).
    3. A Reddit Post (Title + Body).
    
    BLOG CONTENT:
    {blog_content[:15000]}... (truncated)
    
    OUTPUT FORMAT:
    Return a valid JSON object with keys: "linkedin", "twitter", "reddit".
    """
    try:
        message = writer.messages.create(
            model=final_claude_model, # Using the selected model
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
            
        add_log("Social posts generated.")
        return json.loads(response_text)
    except Exception as e:
        add_log(f"Social Media Agent Failed: {e}")
        return {"linkedin": "Error", "twitter": "Error", "reddit": "Error"}

# --- UPDATED: Now accepts tone and audience for better image generation ---
def agent_artist(topic, tone_setting, audience_setting):
    """AGENT 4: THE ARTIST (DALL-E)"""
    add_log("Agent 4 (DALL-E) starting image generation...")
    global openai_client_is_valid
    if not openai_client_is_valid:
        add_log("DALL-E skipped due to invalid key.")
        return None
    
    # --- NEW: Dynamic Prompt Generation based on Audience/Tone ---
    style_modifier = ""
    if audience_setting == "Developer (Technical)":
        style_modifier = "Focus on clean UI/UX, schematic representations, or minimalist code aesthetics."
    elif audience_setting == "Executive (Strategy/ROI)":
        style_modifier = "Focus on abstract concepts of growth, strategy, or high-level business metaphors."
    elif audience_setting == "Recruiter (Career/Skills)":
        style_modifier = "Focus on human connection, diverse teams, or career path visualizations."
    
    if tone_setting in ["Witty", "Storyteller"]:
        style_modifier += " Use a vibrant, slightly playful, or narrative-driven style."
    else:
        style_modifier += " Maintain a professional and modern editorial feel."

    prompt = f"A high-quality, modern editorial illustration about {topic}. {style_modifier} Minimalist, tech-forward, 16:9 aspect ratio. No text."
    add_log(f"DALL-E Prompt: {prompt[:80]}...")
    # --- END NEW LOGIC ---

    try:
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        add_log("Image URL received.")
        # Return the original URL; the workflow will now upload it to Ghost
        return response.data[0].url
    except Exception as e:
        add_log(f"Image generation failed: {e}")
        st.warning(f"Image generation failed: {e}")
        return None

def publish_to_ghost(data, image_url, tags):
    add_log("Attempting to publish draft to Ghost...")
    token = create_ghost_token()
    if not token:
        add_log("Publish failed: Could not generate Ghost token.")
        # Return a dummy response object
        response = requests.Response()
        response.status_code = 401
        return response

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
            add_log("Draft successfully published! (Status 201)")
        else:
            add_log(f"Publish Failed (Status {response.status_code}): {response.text[:100]}...")
        return response
    except Exception as e:
        add_log(f"Publish connection error: {e}")
        # Return a dummy response object on connection failure
        response = requests.Response()
        response.status_code = 500
        return response

# --- UI LAYOUT ---

st.title("🎩 Elite AI Blog Agent V8 (3-Agent System)")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

st.markdown("""
<div style="border: 1px solid #ddd; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
    <h4>🚀 The World's Most Advanced AI Editorial Team</h4>
    <ul>
        <li>🗣️ <b>Multi-Format Context:</b> Upload files (PDF, Doc, <b>Audio/Video</b>). We transcribe and read everything.</li>
        <li>🔍 <b>Research & Validation:</b> Perplexity performs deep research AND <b>fact-checks claims</b>.</li>
        <li>✍️ <b>Style & SEO:</b> Claude mimics your voice AND targets your keywords.</li>
        <li>🎨 <b>Instant Visuals:</b> DALL-E 3 automatically generates a high-quality cover image.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# --- STATUS DASHBOARD (New Feature) ---
st.subheader("Workflow Status")
col_tech, col_user, col_log = st.columns(3)

with col_tech:
    st.markdown("**1. Technical Stack**")
    # Use the session state variable for writer model
    writer_model = st.session_state.get('last_claude_model', 'N/A')
    st.info(f"Writer: {writer_model}\nResearch: Perplexity (Sonar)")

with col_user:
    st.markdown("**2. User Workflow Status**")
    st.warning(st.session_state.current_workflow_status)
    
with col_log:
    st.markdown("**3. Live Logging**")
    # --- UPDATED: Full, scrollable log area ---
    log_content = "\n".join(st.session_state.log_events)
    st.text_area(
        label="Log History",
        value=log_content,
        height=200,
        disabled=True,
        key="log_display_area",
        help="All log events are captured here for review and copy/paste."
    )
# --- END STATUS DASHBOARD ---

# SIDEBAR
with st.sidebar:
    st.header("Configuration")
    if not openai_client_is_valid:
        st.error("OpenAI Key failed. DALL-E/Whisper disabled.")
        
    style_sample = st.text_area("Your Writing Style Sample", height=100, placeholder="Paste a previous blog post...")
    st.divider()
    
    # IMPROVED SLIDER: Select Box for clearer options
    st.subheader("Tone & Voice")
    tone_setting = st.select_slider(
        "Choose your vibe:",
        options=["Technical", "Professional", "Conversational", "Witty", "Storyteller"],
        value="Conversational"
    )

    st.divider()
    # --- NEW: Target Audience Selector ---
    st.subheader("Target Audience")
    audience_setting = st.selectbox(
        "Who is reading this post?",
        options=["General Public", "Developer (Technical)", "Executive (Strategy/ROI)", "Recruiter (Career/Skills)"],
        index=0,
        key="audience_setting_select",
        help="This dictates the level of jargon and focus (e.g., code vs. business value)."
    )

    st.divider()
    st.subheader("🛠️ Debugging/Model Select")
    # --- FIX: Use a key to store selection in session_state, making it robust across re-runs ---
    st.selectbox(
        "Claude Model (Select if getting 404 errors):",
        options=["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus", "claude-3-sonnet"],
        index=0,
        key='claude_model_selection', # <-- Stored in session_state
        help="The error means your key cannot access the model. Try switching to a different model if the default fails."
    )

# --- FIX: Safely retrieve the model selection from session state ---
claude_model_select = st.session_state['claude_model_selection']


# MAIN INPUT AREA
col_input, col_file = st.columns([2, 1])

with col_input:
    topic = st.text_input("Main Blog Topic / Prompt", placeholder="e.g. Guide on 'Scaling Databases' addressing pain points in the call...")
    
    # STEP 2: SEO KEYWORDS (With Suggestion Button)
    col_seo_btn, col_seo_txt = st.columns([1, 2])
    with col_seo_btn:
        st.write("")
        st.write("")
        if st.button("✨ Suggest Keywords", help="Ask Perplexity for high-impact keywords"):
            if not topic:
                st.toast("Please enter a topic first!", icon="⚠️")
            else:
                with st.spinner("Analyzing SEO trends..."):
                    st.session_state.current_workflow_status = "Generating Keywords..."
                    suggestions = agent_seo_suggestion(topic)
                    st.session_state['seo_keywords'] = suggestions
                    st.session_state.current_workflow_status = "Awaiting Generation Start."
    
    with col_seo_txt:
        keywords = st.text_input(
            "Target SEO Keywords (Optional)",
            value=st.session_state.get('seo_keywords', ''),
            placeholder="e.g. database sharding, sql vs nosql",
            key='seo_keywords_input', # Keep value updated in session state
            help="Edit these or add your own."
        )
        # Update session state with the manually edited value
        st.session_state['seo_keywords'] = st.session_state['seo_keywords_input']


with col_file:
    # Full file support restored
    uploaded_file = st.file_uploader("Attach Context (Optional)", type=['txt', 'md', 'pdf', 'docx', 'mp3', 'mp4', 'm4a', 'mpeg', 'wav'])

st.divider()

if st.button("Start Elite Workflow", type="primary", use_container_width=True):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        # Clear logs and set initial status
        st.session_state.log_events = ["Workflow started."]
        st.session_state.current_workflow_status = "Processing Files..."
        # Use the safely retrieved variable
        st.session_state.last_claude_model = claude_model_select # Save for status display
        
        # ESTIMATED COST TRACKER
        est_cost = 0.00
        
        # PROCESS FILE
        transcript_text = None
        if uploaded_file:
            file_type = uploaded_file.name.split('.')[-1].lower()
            add_log(f"File detected: {uploaded_file.name}. Type: {file_type}")
            
            with st.status(f"📂 Reading Context: {file_type.upper()}...", expanded=True) as status:
                try:
                    if file_type in ['pdf']: transcript_text = extract_text_from_pdf(uploaded_file)
                    elif file_type in ['docx']: transcript_text = extract_text_from_docx(uploaded_file)
                    elif file_type in ['txt', 'md']: transcript_text = uploaded_file.read().decode("utf-8")
                    elif file_type in ['mp3', 'mp4', 'm4a', 'mpeg', 'wav']:
                        add_log("Starting audio transcription via Whisper...")
                        transcript_text = transcribe_audio(uploaded_file)
                        if "Error" not in transcript_text:
                            est_cost += 0.01
                        
                    if transcript_text and "Error" not in transcript_text: st.write(f"✅ Context Loaded.")
                    else: st.error(f"File processing error: {transcript_text}")
                except Exception as e:
                    add_log(f"FATAL File processing error: {e}")
                    status.update(label="Context Processing Failed", state="error")
                    st.stop()
                status.update(label="Context Ready!", state="complete", expanded=False)

        # 1. RESEARCH
        st.session_state.current_workflow_status = "Researching and Validating Facts..."
        with st.status("🕵️ Agent 1: Perplexity is researching & validating...", expanded=True) as status:
            research_data = agent_research(topic, transcript_context=bool(transcript_text))
            if research_data:
                st.write("✅ Facts verified.")
                est_cost += 0.01
            else:
                status.update(label="Research Failed", state="error")
                st.stop()
            
            # 2. WRITING
            st.session_state.current_workflow_status = "Drafting Content (Claude)..."
            status.update(label=f"✍️ Agent 2: Claude is writing ({tone_setting} tone, for {audience_setting})...", state="running")
            # --- Pass audience_setting to the writer agent ---
            blog_post = agent_writer(topic, research_data, style_sample, tone_setting, keywords, audience_setting, transcript_context, transcript_text, claude_model_select)
            if blog_post:
                st.session_state['elite_blog_v8'] = blog_post
                # Placeholder cost for Claude 3.5 Sonnet (~$0.003/k token, estimating $0.05 per long post)
                est_cost += 0.05
            else:
                status.update(label="Writing Failed", state="error")
                st.stop()
            
            # 3. SOCIAL MEDIA
            st.session_state.current_workflow_status = "Generating Social Media Assets..."
            status.update(label="📱 Agent 3: Drafting Socials...", state="running")
            # --- Pass the user-selected model ---
            socials = agent_social_media(blog_post['html_content'], claude_model_select)
            st.session_state['elite_socials'] = socials
            
            # 4. ART & IMAGE UPLOAD
            st.session_state.current_workflow_status = "Generating Image & Uploading to Ghost..."
            status.update(label="🎨 Agent 4: DALL-E is painting...", state="running")
            # Generate the temporary DALL-E URL
            temp_image_url = agent_artist(topic, tone_setting, audience_setting)
            
            ghost_image_url = None
            if temp_image_url:
                # --- NEW: Download and upload to Ghost for hosting/optimization ---
                status.update(label="☁️ Uploading Image to Ghost for Hosting...", state="running")
                ghost_image_url = upload_image_to_ghost(temp_image_url)
                if ghost_image_url:
                    est_cost += 0.04
                else:
                    st.warning("Ghost image upload failed. Using DALL-E URL directly.")
                    ghost_image_url = temp_image_url # Fallback
            
            st.session_state['elite_image_v8'] = ghost_image_url
            st.session_state['est_cost'] = est_cost
            st.session_state.current_workflow_status = "Draft Ready for Review."
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW AREA
if st.session_state['elite_blog_v8']:
    post = st.session_state['elite_blog_v8']
    socials = st.session_state.get('elite_socials', {})
    img_url = st.session_state.get('elite_image_v8', '')
    
    st.divider()
    c1, c2 = st.columns([3, 1])
    with c1: st.subheader("Review & Publish")
    with c2: st.caption(f"Est. Generation Cost: ${st.session_state.get('est_cost', 0.00):.2f}")

    # --- NEW: Refinement Section ---
    st.subheader("🔄 Post-Draft Refinement")
    refinement_feedback = st.text_area(
        "Refinement Feedback / Instructions:",
        placeholder="e.g., 'Make the introduction wittier', 'Shorten the third paragraph', or 'Suggest a better title.'",
        height=100,
        key='refinement_feedback_input'
    )
    
    # Use the selected Claude model from the session state
    claude_model_select = st.session_state.get('last_claude_model', "claude-sonnet-4-20250514")

    if st.button("✨ Refine Draft with Claude", type="secondary", disabled=not refinement_feedback):
        with st.status("🧠 Agent 5: Refinement in progress...", expanded=True) as status:
            st.session_state.current_workflow_status = "Refining Content..."
            
            # Fetching current UI values to pass to the refiner
            current_post_data = {
                'title': st.session_state.get('final_title', post.get('title')),
                'excerpt': st.session_state.get('final_excerpt', post.get('excerpt')),
                'meta_title': st.session_state.get('final_meta_title', post.get('meta_title')),
                'meta_description': st.session_state.get('final_meta_desc', post.get('meta_description')),
                'html_content': st.session_state.get('final_content', post.get('html_content'))
            }
            
            refined_post = agent_refiner(current_post_data, refinement_feedback, claude_model_select)
            
            if refined_post:
                st.session_state['elite_blog_v8'] = refined_post # Overwrite the session state with new draft
                st.session_state.current_workflow_status = "Refinement Complete."
                status.update(label="Draft Refined!", state="complete")
                # Force a re-run to refresh the text areas with the new content
                st.rerun() 
            else:
                status.update(label="Refinement Failed", state="error")
                st.error("Refinement failed. Check the logs for details.")
    
    st.divider()
    # --- END Refinement Section ---

    # TABS FOR VIEWING
    tab_blog, tab_social = st.tabs(["📝 Blog Post", "📱 Social Media Pack"])

    with tab_blog:
        col1, col2 = st.columns([1, 2])
        with col1:
            if img_url: st.image(img_url, caption="Header", use_container_width=True)
            else: st.info("Image generation skipped or failed (Check OpenAI Key).")
        with col2:
            final_img = st.text_input("Feature Image URL", value=img_url or "", help="Paste your own image URL here, or use the generated one.", key='final_img_url')

        # Text inputs are now refreshed with refined content if needed
        title = st.text_input("Title", value=post.get('title', ''), key='final_title')
        with st.expander("SEO Metadata"):
            meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''), key='final_meta_title')
            meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''), key='final_meta_desc')
            
        excerpt = st.text_input("Excerpt", value=post.get('excerpt', ''), key='final_excerpt')
        content = st.text_area("HTML Content", value=post.get('html_content', ''), height=500, key='final_content')

        if st.button("🚀 Upload Draft to Ghost"):
            with st.spinner("Uploading..."):
                # Use the keys from the UI inputs for the final post
                # We need to explicitly check if the key exists before assuming it's been updated by the refinement loop or a manual edit.
                final_post_data = {
                    'title': st.session_state.get('final_title', post.get('title')), 
                    'excerpt': st.session_state.get('final_excerpt', post.get('excerpt')), 
                    'meta_title': st.session_state.get('final_meta_title', post.get('meta_title')), 
                    'meta_description': st.session_state.get('final_meta_desc', post.get('meta_description')), 
                    'html_content': st.session_state.get('final_content', post.get('html_content'))
                }
                
                tags = ["Elite AI"]
                if uploaded_file: tags.append("Context Aware")
                result = publish_to_ghost(final_post_data, st.session_state['final_img_url'], tags)
                if result.status_code in [200, 201]:
                    st.balloons()
                    st.success("Success! Draft created.")
                    st.markdown(f"[Open in Ghost Admin]({GHOST_API_URL}/ghost/#/posts)")
                else:
                    st.error(f"Ghost Publishing Error Status: {result.status_code}. Response: {result.text}")

    with tab_social:
        st.info("Click the buttons below to open a draft on your favorite platform.")
        
        # LinkedIn
        li_text = socials.get('linkedin', '')
        st.text_area("LinkedIn Draft", value=li_text, height=150)
        st.link_button("Post to LinkedIn", generate_social_links(li_text, "linkedin"))
        
        st.divider()
        
        # Twitter
        tw_text = socials.get('twitter', '')
        st.text_area("X / Twitter Draft", value=tw_text, height=100)
        st.link_button("Post to X", generate_social_links(tw_text, "twitter"))
        
        st.divider()

        # Reddit
        rd_text = socials.get('reddit', '')
        st.text_area("Reddit Draft", value=rd_text, height=100)
        st.link_button("Post to Reddit", generate_social_links(rd_text, "reddit"))
