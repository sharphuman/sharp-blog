import streamlit as st
import requests
import jwt # pip install pyjwt
import datetime
import json
import io
import urllib.parse
from openai import OpenAI
from anthropic import Anthropic
from pypdf import PdfReader # pip install pypdf
from docx import Document # pip install python-docx

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V5", page_icon="🎩", layout="wide")

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
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
writer = Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
    try:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1", 
            file=file
        )
        return transcript.text
    except Exception as e:
        return f"Error transcribing audio: {str(e)}"

def generate_social_links(text, platform):
    """Generates intent links for social sharing without API keys."""
    encoded_text = urllib.parse.quote(text)
    if platform == "twitter":
        return f"https://twitter.com/intent/tweet?text={encoded_text}"
    elif platform == "linkedin":
        return f"https://www.linkedin.com/feed/?shareActive=true&text={encoded_text}"
    elif platform == "reddit":
        return f"https://www.reddit.com/submit?selftext=true&title=Check%20out%20my%20new%20post&text={encoded_text}"
    return "#"

# --- CORE FUNCTIONS ---

def create_ghost_token():
    try:
        key_id, secret = GHOST_ADMIN_KEY.split(':')
        iat = int(datetime.datetime.now().timestamp())
        header = {'alg': 'HS256', 'typ': 'JWT', 'kid': key_id}
        payload = {'iat': iat, 'exp': iat + (5 * 60), 'aud': '/admin/'}
        return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    except Exception as e:
        return None

def agent_research(topic, transcript_context=None):
    if transcript_context:
        system_prompt = "You are a fact-checking assistant. The user has provided context in a file. Find external data, stats, or definitions to support the user's main topic."
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

def agent_writer(topic, research_notes, style_sample, temperature, keywords, transcript_text=None):
    
    style_instruction = ""
    if style_sample:
        style_instruction = f"""
        STYLE MIMICRY INSTRUCTIONS:
        Analyze this writing sample: "{style_sample}"
        Adopt the sentence structure, vocabulary, and rhythm of this sample.
        """
    else:
        style_instruction = "Use a professional, engaging, and human tone."

    keyword_instruction = ""
    if keywords:
        keyword_instruction = f"""
        SEO MANDATE:
        You MUST naturally include the following keywords in the text: {keywords}.
        Do not stuff them; use them where they fit logically.
        """

    if transcript_text:
        safe_transcript = transcript_text[:50000]
        source_material_instruction = f"""
        USER'S MAIN GOAL: "{topic}"
        CONTEXT (FILE): {safe_transcript}
        RESEARCH: {research_notes}

        INSTRUCTIONS:
        1. Write a blog post addressing the MAIN GOAL.
        2. Use the CONTEXT to frame the problem/narrative.
        3. Use RESEARCH to validate claims.
        """
    else:
        source_material_instruction = f"""
        USER'S MAIN GOAL: "{topic}"
        RESEARCH: {research_notes}
        INSTRUCTIONS: Write a blog post about "{topic}" based on the research.
        """

    prompt = f"""
    You are a world-class ghostwriter.
    {source_material_instruction}
    {style_instruction}
    {keyword_instruction}
    
    OUTPUT FORMAT:
    Return a valid JSON object with keys: "title", "meta_title", "meta_description", "excerpt", "html_content" (semantic HTML).
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

def agent_social_media(blog_content):
    """AGENT 4: THE SOCIAL MEDIA MANAGER"""
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
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        return json.loads(response_text)
    except Exception as e:
        return {"linkedin": "Error", "twitter": "Error", "reddit": "Error"}

def agent_artist(topic):
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

st.title("🎩 Elite AI Blog Agent V5")
st.markdown("Research by **Perplexity** | Writing by **Claude** | Art by **DALL-E**")

st.markdown("""
<div style="border: 1px solid #ddd; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
    <h4>🚀 The World's Most Advanced AI Editorial Team</h4>
    <ul>
        <li>🗣️ <b>Context Aware:</b> Upload calls/notes (PDF, Doc, Audio) as backstory.</li>
        <li>🔍 <b>Fact Checking:</b> Perplexity validates claims.</li>
        <li>✍️ <b>Style & SEO:</b> Claude mimics your voice AND targets your keywords.</li>
        <li>📱 <b>Social Pack:</b> Auto-generates LinkedIn, Twitter & Reddit drafts.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# SIDEBAR
with st.sidebar:
    st.header("Configuration")
    style_sample = st.text_area("Your Writing Style Sample", height=100, placeholder="Paste a previous blog post...")
    st.divider()
    temperature = st.slider("Creativity", 0.0, 1.0, 0.7)

# MAIN INPUT
col_input, col_file = st.columns([2, 1])

with col_input:
    topic = st.text_input("Main Blog Topic / Prompt", placeholder="e.g. Guide on 'Scaling Databases' addressing pain points in the call...")
    keywords = st.text_input("Target SEO Keywords (Optional)", placeholder="e.g. database sharding, sql vs nosql")

with col_file:
    uploaded_file = st.file_uploader("Attach Context (Optional)", type=['txt', 'md', 'pdf', 'docx', 'mp3', 'mp4', 'm4a', 'mpeg', 'wav'])

if st.button("Start Elite Workflow", type="primary"):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        # ESTIMATED COST TRACKER
        est_cost = 0.00
        
        # PROCESS FILE
        transcript_text = None
        if uploaded_file:
            file_type = uploaded_file.name.split('.')[-1].lower()
            with st.status(f"📂 Reading Context: {file_type.upper()}...", expanded=True) as status:
                try:
                    if file_type in ['pdf']: transcript_text = extract_text_from_pdf(uploaded_file)
                    elif file_type in ['docx']: transcript_text = extract_text_from_docx(uploaded_file)
                    elif file_type in ['txt', 'md']: transcript_text = uploaded_file.read().decode("utf-8")
                    elif file_type in ['mp3', 'mp4', 'm4a', 'mpeg', 'wav']:
                        st.write("Transcribing audio...")
                        transcript_text = transcribe_audio(uploaded_file)
                        est_cost += 0.01 
                    
                    if transcript_text: st.write(f"✅ Context Loaded.")
                except Exception as e:
                    st.error(f"Error: {e}")
                    st.stop()
                status.update(label="Context Ready!", state="complete", expanded=False)

        # 1. RESEARCH
        with st.status("🕵️ Agent 1: Perplexity is researching...", expanded=True) as status:
            research_data = agent_research(topic, transcript_context=bool(transcript_text))
            if research_data:
                st.write("✅ Data gathered.")
                est_cost += 0.01 
            else:
                status.update(label="Research Failed", state="error")
                st.stop()
            
            # 2. WRITING
            status.update(label="✍️ Agent 2: Claude is writing...", state="running")
            blog_post = agent_writer(topic, research_data, style_sample, temperature, keywords, transcript_text)
            if blog_post:
                st.session_state['elite_blog_v5'] = blog_post
                est_cost += 0.05 
            else:
                status.update(label="Writing Failed", state="error")
                st.stop()
            
            # 3. SOCIAL MEDIA
            status.update(label="📱 Agent 3: Drafting Socials...", state="running")
            socials = agent_social_media(blog_post['html_content'])
            st.session_state['elite_socials'] = socials
            
            # 4. ART
            status.update(label="🎨 Agent 4: DALL-E is painting...", state="running")
            image_url = agent_artist(topic)
            st.session_state['elite_image_v5'] = image_url
            est_cost += 0.04 
            
            st.session_state['est_cost'] = est_cost
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW AREA
if 'elite_blog_v5' in st.session_state:
    post = st.session_state['elite_blog_v5']
    socials = st.session_state.get('elite_socials', {})
    img_url = st.session_state.get('elite_image_v5', '')
    
    st.divider()
    c1, c2 = st.columns([3, 1])
    with c1: st.subheader("Review & Publish")
    with c2: st.caption(f"Est. Generation Cost: ${st.session_state.get('est_cost', 0.00):.2f}")

    # TABS FOR VIEWING
    tab_blog, tab_social = st.tabs(["📝 Blog Post", "📱 Social Media Pack"])

    with tab_blog:
        col1, col2 = st.columns([1, 2])
        with col1:
            if img_url: st.image(img_url, caption="Header", use_container_width=True)
        with col2:
            final_img = st.text_input("Image URL", value=img_url)

        title = st.text_input("Title", value=post.get('title', ''))
        with st.expander("SEO Metadata"):
            meta_title = st.text_input("Meta Title", value=post.get('meta_title', ''))
            meta_desc = st.text_input("Meta Description", value=post.get('meta_description', ''))
        
        excerpt = st.text_input("Excerpt", value=post.get('excerpt', ''))
        content = st.text_area("HTML Content", value=post.get('html_content', ''), height=500)

        if st.button("🚀 Upload Draft to Ghost"):
            with st.spinner("Uploading..."):
                post.update({'title': title, 'excerpt': excerpt, 'meta_title': meta_title, 'meta_description': meta_desc, 'html_content': content})
                tags = ["Elite AI"]
                if uploaded_file: tags.append("Context Aware")
                result = publish_to_ghost(post, final_img, tags)
                if result.status_code in [200, 201]:
                    st.balloons()
                    st.success("Success! Draft created.")
                    st.markdown(f"[Open in Ghost Admin]({GHOST_API_URL}/ghost/#/posts)")
                else:
                    st.error(f"Error: {result.text}")

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
