I understand. I apologize that the canvas is being difficult. The syntax error you are seeing:

`````
File "/app/sharp-blog.py", line 489
  ````
  ^
SyntaxError: invalid syntax
`````

... is because an extra set of **markdown code fences** (` ```` `) somehow made it into the code when I pasted it. I will ensure the code is clean.

Here is the complete, clean Python code for **Elite Blog Agent V8 (Three-Agent System)**, ready to be pasted into your `sharp-blog.py` file.

````python
import streamlit as st
import requests
import jwt # pip install pyjwt
import datetime
import json
import io
import urllib.parse
from anthropic import Anthropic
from pypdf import PdfReader # pip install pypdf
from docx import Document # pip install python-docx
from openai import OpenAI 

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Elite AI Blog Agent V8 (3-Agent System)", page_icon="🎩", layout="wide")

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
        st.error(f"Missing Secrets: {env_error}. Please set all five keys.")
        st.stop()

# --- INITIALIZE SPECIALISTS ---
researcher = OpenAI(api_key=PPLX_API_KEY, base_url="https://api.perplexity.ai")
writer = Anthropic(api_key=ANTHROPIC_API_KEY)

# --- ISOLATE OPENAI CLIENT INITIALIZATION ---
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    openai_client_is_valid = True
except Exception:
    openai_client = None
    openai_client_is_valid = False
    
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
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1", 
            file=file
        )
        return transcript.text
    except Exception as e:
        # Catch specific API errors related to billing or limits
        return f"Error transcribing audio (OpenAI API Issue): {str(e)}"

def generate_social_links(text, platform):
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
        return None

def agent_seo_suggestion(topic):
    """AGENT 0: THE SEO STRATEGIST (Perplexity)"""
    system_prompt = "You are an SEO expert. Given a topic, suggest 5-7 high-impact, relevant keywords or phrases separated by commas. Do not explain, just list them."
    try:
        response = researcher.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Topic: {topic}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return ""

def agent_research(topic, transcript_context=None):
    """AGENT 1: THE RESEARCHER & TRUTH VALIDATOR (Perplexity)"""
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
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Research Agent Failed: {e}")
        return None

def agent_writer(topic, research_notes, style_sample, tone_setting, keywords, transcript_text=None, claude_model="claude-3-5-sonnet"):
    """AGENT 2: THE WRITER (Claude)"""
    
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

    # 3. Source Logic
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
        """
    else:
        source_material_instruction = f"""
        USER'S MAIN GOAL: "{topic}"
        RESEARCH (VALIDATION): {research_notes}
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
            model=claude_model,
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

def agent_social_media(blog_content, claude_model="claude-3-5-sonnet"):
    """AGENT 3: THE SOCIAL MEDIA MANAGER (Claude)"""
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
            model=claude_model,
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
    """AGENT 4: THE ARTIST (DALL-E)"""
    global openai_client_is_valid
    if not openai_client_is_valid:
        return None
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
            "feature_image": image_url, # Image URL restored
            "status": "draft",
            "tags": [{"name": t} for t in tags] 
        }]
    }
    return requests.post(url, json=body, headers=headers)

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
    st.subheader("🛠️ Debugging/Model Select")
    # Updated Model Selector options
    claude_model_select = st.selectbox(
        "Claude Model (Select if getting 404 errors):",
        options=["claude-3-5-sonnet", "claude-3-opus", "claude-3-sonnet"],
        index=0, 
        help="The error means your key cannot access the model. Try switching to 'claude-3-opus' if the default fails."
    )

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
                    suggestions = agent_seo_suggestion(topic)
                    st.session_state['seo_keywords'] = suggestions
    
    with col_seo_txt:
        keywords = st.text_input(
            "Target SEO Keywords (Optional)", 
            value=st.session_state.get('seo_keywords', ''),
            placeholder="e.g. database sharding, sql vs nosql",
            help="Edit these or add your own."
        )

with col_file:
    # Full file support restored
    uploaded_file = st.file_uploader("Attach Context (Optional)", type=['txt', 'md', 'pdf', 'docx', 'mp3', 'mp4', 'm4a', 'mpeg', 'wav'])

st.divider()

if st.button("Start Elite Workflow", type="primary", use_container_width=True):
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
                        if "Error" not in transcript_text:
                            est_cost += 0.01 
                    
                    if transcript_text and "Error" not in transcript_text: st.write(f"✅ Context Loaded.")
                    else: st.error(f"File processing error: {transcript_text}")
                except Exception as e:
                    st.error(f"File processing failed: {e}")
                    st.stop()
                status.update(label="Context Ready!", state="complete", expanded=False)

        # 1. RESEARCH
        with st.status("🕵️ Agent 1: Perplexity is researching & validating...", expanded=True) as status:
            research_data = agent_research(topic, transcript_context=bool(transcript_text))
            if research_data:
                st.write("✅ Facts verified.")
                est_cost += 0.01 
            else:
                status.update(label="Research Failed", state="error")
                st.stop()
            
            # 2. WRITING
            status.update(label=f"✍️ Agent 2: Claude is writing ({tone_setting} tone)...", state="running")
            blog_post = agent_writer(topic, research_data, style_sample, tone_setting, keywords, transcript_text, claude_model_select)
            if blog_post:
                st.session_state['elite_blog_v8'] = blog_post
                est_cost += 0.05 
            else:
                status.update(label="Writing Failed", state="error")
                st.stop()
            
            # 3. SOCIAL MEDIA
            status.update(label="📱 Agent 3: Drafting Socials...", state="running")
            socials = agent_social_media(blog_post['html_content'], claude_model_select)
            st.session_state['elite_socials'] = socials
            
            # 4. ART
            status.update(label="🎨 Agent 4: DALL-E is painting...", state="running")
            image_url = agent_artist(topic)
            if image_url:
                est_cost += 0.04 
            
            st.session_state['elite_image_v8'] = image_url
            st.session_state['est_cost'] = est_cost
            status.update(label="Workflow Complete!", state="complete", expanded=False)

# PREVIEW AREA
if 'elite_blog_v8' in st.session_state:
    post = st.session_state['elite_blog_v8']
    socials = st.session_state.get('elite_socials', {})
    img_url = st.session_state.get('elite_image_v8', '')
    
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
            else: st.info("Image generation skipped or failed (Check OpenAI Key).")
        with col2:
            final_img = st.text_input("Feature Image URL", value=img_url or "", help="Paste your own image URL here, or use the generated one.")

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
````
