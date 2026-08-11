import os, sys, json, shutil
import slides as slide_engine
import tts

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(BASE, 'projects')
os.makedirs(PROJECTS, exist_ok=True)

src_pptx = r'c:\Users\Pratibha\Downloads\Artificial Intelligence (AI) is technology that enables machines and software to learn, think, analyze, and make decisions like humans..pptx'
pid = 'ai_guru_v5'
d = os.path.join(PROJECTS, pid)
os.makedirs(d, exist_ok=True)

src_dst = os.path.join(d, 'source.pptx')
shutil.copy(src_pptx, src_dst)

print("Rendering thumbnails and build states...")
thumbs_dir = os.path.join(d, 'thumbs')
thumbs = slide_engine.pptx_to_pngs(src_dst, thumbs_dir, dpi=60)
info = slide_engine.extract_slide_info(src_dst)
states, manifest = slide_engine.render_build_states(src_dst, os.path.join(d, 'build'), dpi=110)

print(f"Generated {len(states)} slides.")

scripts = [
    "Welcome to Artificial Intelligence for Enterprise. What is Artificial Intelligence? Artificial Intelligence, or AI, is technology that enables machines and software to learn, think, analyze, and make decisions like humans. AI helps people understand information, generate ideas, automate routine work, and make everyday tasks easier. Most importantly, instead of replacing people, AI empowers us to become more productive.",

    "Let's explore how Artificial Intelligence works. First, Data: AI learns from large amounts of information available across the internet. Second, Learning: algorithms identify patterns and improve over time. Third, Decision: AI predicts, recommends, or automates actions. Now, how do users need to work with AI? Step 1: Provide a Clear Prompt. Describe your question or task in simple and specific language. Step 2: AI Understands the Prompt. AI reads your input and analyzes it using trained models and patterns. Step 3: AI Processes the Information. It identifies relevant context, relationships, and knowledge to understand your request. Step 4: AI Generates a Response. Based on its analysis, AI creates a relevant answer, suggestion, or solution.",

    "Let's look at the Evolution of AI. We begin with Basic capabilities, such as meeting scheduling and automated summaries. Next is Intermediate AI, automating approvals for leave and finance. Finally, Advanced AI provides intelligent suggestions for complex decisions, like helping doctors detect diseases faster. In Business and Enterprise, AI allows us to automate customer support with chat assistants, analyze business data for useful insights, create smart reports and interactive dashboards, support hiring and HR tasks, and provide instant IT help and troubleshooting. It also automates repetitive business processes, predicts future trends, enables faster email drafting, and creates downloadable meeting recaps.",

    "There are several AI tools available today, each designed to support different types of work. ChatGPT excels at content creation and summarization. Copilot enhances productivity with seamless Microsoft integration. Gemini provides deep research and knowledge assistance. Claude delivers advanced document analysis and writing assistance. In real-world enterprise applications, Healthcare uses AI to detect diseases earlier and support faster diagnosis. IT Support resolves issues quickly and automates service requests. Finance detects fraud instantly and analyzes financial data. Manufacturing monitors equipment health and improves product quality. Together, these tools save time and effort, improve productivity, reduce manual work, and support better decision-making.",

    "To continue your AI journey, explore the AI Enterprise Portal on MoS GURU to discover AI tools, learning resources, and best practices, and stay updated with the latest AI initiatives and training. If you need help, request access to internal AI systems or schedule a team deep-dive training session. Contact us at MoS GURU."
]

proj = {
    'id': pid,
    'name': 'AI_Enterprise_Training_MoS_GURU',
    'voice': 'sofia',
    'subtitleStyle': 'minimal',
    'showSubtitles': True,
    'showKeywords': True,
    'showProgress': True,
    'cinematic': True,
    'highlightSweeps': True,
    'avatar': {'id': 'maya', 'x': 0.855, 'y': 0.80, 'size': 0.24, 'visible': True},
    'avatarOpts': {'energy': 0.75, 'smile': 0.6, 'gesture': 0.7, 'eye': 0.8},
    'presenter': {'mode': 'animated', 'shape': 'circle', 'zoom': 1.0, 'offsetY': 0.0, 'hasFootage': False},
    'width': 1920,
    'height': 1080,
    'fps': 30,
    'quality': 'balanced',
    'slides': []
}

for i in range(len(states)):
    inf = info[i] if i < len(info) else {'title': f'Slide {i+1}'}
    script = scripts[i] if i < len(scripts) else slide_engine.draft_script(inf)
    proj['slides'].append({
        'index': i,
        'title': inf.get('title') or f'Slide {i+1}',
        'script': script,
        'voice': None,
        'speed': 1.0,
        'pause': 0.3,
        'transition': 'auto',
        'n_states': len(states[i]),
        'est': tts.estimate_duration(script),
    })

with open(os.path.join(d, 'states.json'), 'w') as f:
    json.dump(states, f)
if manifest is not None:
    with open(os.path.join(d, 'manifest.json'), 'w') as f:
        json.dump(manifest, f)

with open(os.path.join(d, 'project.json'), 'w') as f:
    json.dump(proj, f, indent=1)

print("Project successfully created in projects/ai_guru_v5.")
