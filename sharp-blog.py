import streamlit as st
import requests
import jwt # pip install pyjwt
import datetime
import json
import io
from openai import OpenAI
from anthropic import Anthropic
from pypdf import PdfReader # pip install pypdf
from docx import Document # pip install python-docx

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V4", page_icon="🎩", layout="wide")

try:
    # Ghost Credentials
    GHOST_ADMIN_KEY = st.secrets.get("GHOST_ADMIN_API_KEY") or st.secrets["GHOST_ADMIN_API_KEY"]
    GHOST_API_URL = st.secrets.get("GHOST_API_URL") or st.secrets["GHOST_API_URL"]
    GHOST_API_URL = GHOST_API_URL.rstrip('/')
    
    # AI Credentials
    PPLX_API_KEY = st.secrets.get("PERPLEXITY_API_KEY") or st.secrets["PERPLEXITY_API_KEY"]
    ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY") or st.secrets["ANTHROPIC_API_KEY"]
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or st.secrets["OPENAI_API_KEY"]
    
except Exception as e:
    # Fallback for when secrets are environment variables
    import os
    try:
        GHOST_ADMIN_KEY = os.environ["GHOST_ADMIN_API_KEY"]
        GHOST_API_URL = os.environ["GHOST_API_URL"].rstrip('/')
        PPLX_API_KEY = os.environ["PERPLEXITY_API_KEY"]
        ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
        OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
    except KeyError as env_error:
        st.error(f"Missing Secrets: {env_error}. Please set environment variables or .streamlit/secrets.toml")
        st.stop()

# --- INITIALIZE SPECIALISTS ---

# 1. The Researcher (Perplexity)
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")

# 2. The Writer (Claude)
writer = Anthropic(api_key=ANTHROPIC_API_KEY)

# 3. The Artist & Transcriber (OpenAI)
# We use the standard OpenAI client for DALL-E and Whisper
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER FUNCTIONS: FILE PROCESSING ---

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
    # OpenAI Whisper API has a 25MB limit. 
    # For a robust app, we would chunk larger files, but for this MVP we send directly.
    try:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1", 
            file=file
        )
        return transcript.text
    except Exception as e:
        return f"Error transcribing audio: {str(e)}"

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

def agent_research(topic, transcript_context=None):
    """AGENT 1: THE RESEARCHER (Perplexity)"""
    if transcript_context:
        system_prompt = "You are a fact-checking assistant. The user will provide a topic based on a conversation/document. Find external data, stats, or definitions to support and enrich the content."
    else:
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

def agent_writer(topic, research_notes, style_sample, temperature, transcript_text=None):
    """AGENT 2: THE WRITER (Claude 3.5 Sonnet)"""
    
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

    if transcript_text:
        # Limit transcript length to avoid token limits (approx 50k chars is safe for Sonnet)
        safe_transcript = transcript_text[:50000] 
        source_material_instruction = f"""
        PRIMARY SOURCE (USER UPLOAD):
        {safe_transcript}

        SECONDARY SOURCE (EXTERNAL RESEARCH):
        {research_notes}

        INSTRUCTIONS:
        The user wants a blog post about: "{topic}".
        1. Base the core narrative on the PRIMARY SOURCE.
        2. Use the SECONDARY SOURCE to clarify terms, add missing dates, or fact-check.
        3. Specifically refer to the discussion points mentioned in the prompt.
        """
    else:
        source_material_instruction = f"""
        BASE MATERIAL (RESEARCH):
        {research_notes}
        
        INSTRUCTIONS:
        Write a high-quality blog post about "{topic}" based on the research above.
        """

    prompt = f"""
    You are a world-class ghostwriter.
    
    {source_material_instruction}
    
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
            model="claude-3-5-sonnet-20241022",
            max_tokens=8000,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
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
        response = openai_client.images.generate(
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

st.title("🎩 Elite AI Blog Agent V4")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

st.markdown("""
<div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
    <h4>🚀 The World's Most Advanced AI Editorial Team</h4>
    <p>Turn ideas OR conversations into publish-ready articles in minutes.</p>
    <ul>
        <li>🗣️ <b>Multi-Format Ingestion:</b> Upload <b>PDFs, Docs, MP3s, or MP4s</b>. We transcribe and read everything.</li>
        <li>🔍 <b>Contextual Research:</b> We use the uploaded content as the "Source of Truth" and Perplexity to fact-check it.</li>
        <li>✍️ <b>Human-Grade Prose:</b> Claude 3.5 Sonnet mimics your voice to write the final piece.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# SIDEBAR CONFIG
with st.sidebar:
    st.header("Configuration")
    st.info("Paste a paragraph of your own writing below. Claude will analyze it to mimic your specific voice.")
    style_sample = st.text_area("Your Writing Style Sample", height=150, placeholder="Paste a previous blog post or email here...")
    st.divider()
    st.subheader("Fine-Tuning")
    temperature = st.slider("Creativity", 0.0, 1.0, 0.7)

# MAIN INPUT
col_input, col_file = st.columns([2, 1])

with col_input:
    topic = st.text_input("Prompt / Instruction", placeholder="e.g. Refer to the discussion on 'Scalability' in the transcript and write a blog post...")
    st.caption("Tell the AI what to focus on in your uploaded file.")

with col_file:
    uploaded_file = st.file_uploader("Attach File (Audio/Video/Doc)", type=['txt', 'md', 'pdf', 'docx', 'mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm'])

if st.button("Start Elite Workflow", type="primary"):
    if not topic:
        st.warning("Please enter a topic or instruction.")
    else:
        # PROCESS FILE
        transcript_text = None
        if uploaded_file is not None:
            file_type = uploaded_file.name.split('.')[-1].lower()
            
            with st.status(f"📂 Processing {file_type.upper()} file...", expanded=True) as status:
                try:
                    if file_type in ['pdf']:
                        transcript_text = extract_text_from_pdf(uploaded_file)
                    elif file_type in ['docx']:
                        transcript_text = extract_text_from_docx(uploaded_file)
                    elif file_type in ['txt', 'md']:
                        transcript_text = uploaded_file.read().decode("utf-8")
                    elif file_type in ['mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm']:
                        st.write("Transcribing audio/video (this may take a moment)...")
                        transcript_text = transcribe_audio(uploaded_file)
                    
                    if transcript_text:
                        st.write(f"✅ Extracted {len(transcript_text)} characters.")
                    else:
                        st.error("Could not extract text.")
                        st.stop()
                        
                except Exception as e:
                    st.error(f"Error processing file: {e}")
                    st.stop()
                    
                status.update(label="File Processed!", state="complete", expanded=False)

        # 1. RESEARCH
        with st.status("🕵️ Agent 1: Perplexity is researching...", expanded=True) as status:
            research_data = agent_research(topic, transcript_context=bool(transcript_text))
            
            if research_data:
                st.write("✅ Data gathered.")
                with st.expander("View Research Data"):
                    st.write(research_data)
            else:
                status.update(label="Research Failed", state="error")
                st.stop()
            
            # 2. WRITING
            status.update(label="✍️ Agent 2: Claude is writing...", state="running")
            blog_post = agent_writer(topic, research_data, style_sample, temperature, transcript_text)
            
            if blog_post:
                st.session_state['elite_blog_v4'] = blog_post
            else:
                status.update(label="Writing Failed", state="error")
                st.stop()
                
            # 3. ART
            status.update(label="🎨 Agent 3: DALL-E is painting...", state="running")
            image_url = agent_artist(topic)
            st.session_state['elite_image_v4'] = image_url
            
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW & PUBLISH
if 'elite_blog_v4' in st.session_state:
    post = st.session_state['elite_blog_v4']
    img_url = st.session_state.get('elite_image_v4', '')
    
    st.divider()
    st.subheader("Review & Publish")
    
    # Image Preview
    col1, col2 = st.columns([1, 2])
    with col1:
        if img_url:
            st.image(img_url, caption="Generated Header", use_container_width=True)
    with col2:
        final_img = st.text_input("Image URL", value=img_url)

    # Text Fields
    title = st.text_input("Title", value=post.get('title', ''))
    
    with st.expander("SEO Metadata (Google Search)"):
        meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''))
        meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''))
        
    excerpt = st.text_input("Excerpt", value=post.get('excerpt', ''))
    content = st.text_area("HTML Content", value=post.get('html_content', ''), height=500)
    
    if st.button("🚀 Upload Draft to Ghost"):
        with st.spinner("Uploading to Ghost..."):
            post['title'] = title
            post['excerpt'] = excerpt
            post['meta_title'] = meta_title
            post['meta_description'] = meta_desc
            post['html_content'] = content
            
            tags = ["Elite AI"]
            if uploaded_file: tags.append("From File")
            
            result = publish_to_ghost(post, final_img, tags)
            
            if result.status_code in [200, 201]:
                st.balloons()
                st.success(f"Success! Draft created.")
                st.markdown(f"[Open in Ghost Admin]({GHOST_API_URL}/ghost/#/posts)")
            else:
                st.error(f"Error: {result.text}")
