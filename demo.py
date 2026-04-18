# ── CELL 1: Install dependencies ──────────────────────────────
# pip install openai tavily-python gradio requests python-dotenv

# ── CELL 2: Load your API keys ────────────────────────────────
# Keys are loaded from key.env in this directory.
from dotenv import load_dotenv
import os

load_dotenv("key.env")

# Discord webhook — already configured for Agentathon
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1494550573083660369/sgTG8d_JnvSQbMxl3fYFYHUIErt4z7tQ9vrNfiyQER9O_SBisOHuBmI6_nw88YJHtB1z"

print("✅ Keys loaded")
# ── CELL 3: Set up the agent ──────────────────────────────────
import os, json, requests
from openai import OpenAI
from tavily import TavilyClient

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

# ═══════════════════════════════════════════════════
# ✏️  CHANGE THIS: Your agent's personality & purpose
# ═══════════════════════════════════════════════════
SYSTEM_PROMPT = """
You are a helpful Lehigh University campus assistant for students.

You help with:
- Course registration (Banner, prereqs, seat availability, CRNs)
- Professor and section comparisons
- Degree requirements and academic planning
- Campus resources, dining, events, and general Lehigh questions

Always search for current information before answering.
Give direct, specific answers. Don't be vague.
When asked to post, share, or alert — use the post_to_discord tool.
Lehigh uses Banner for registration and CourSite (Moodle) for class materials.
"""

print("✅ Agent configured")

# ── CELL 4: Tools ─────────────────────────────────────────────
# Tools let the agent DO things, not just say things.
# The model decides WHEN to call a tool.
# You define WHAT happens when it does.

# TOOL 1: Search the web
def search_web(query: str) -> str:
    """Search for current Lehigh information."""
    results = tavily.search(query=f"Lehigh University {query}", max_results=3)
    output = []
    for r in results.get("results", []):
        output.append(f"Source: {r['url']}\n{r['content'][:400]}")
    return "\n\n---\n\n".join(output) if output else "No results found."


# TOOL 2: Post to Discord
def post_to_discord(message: str) -> str:
    """Post a message to the Agentathon Discord channel."""
    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10
        )
        if response.status_code == 204:
            return "Posted to Discord ✅"
        else:
            return f"Discord error: {response.status_code}"
    except Exception as e:
        return f"Failed: {str(e)}"


# ═══════════════════════════════════════════════════
# ✏️  ADD YOUR OWN TOOL HERE during hack time
# ═══════════════════════════════════════════════════
# Ideas:
#   def send_email(subject, body) → Gmail SMTP or SendGrid
#   def send_sms(message) → Twilio free trial
#   def add_to_calendar(title, date, time) → Google Calendar API
#   def check_class_seats(course_code) → scrape Banner class search
#   def get_dining_menu() → scrape Lehigh dining page


# Register tools
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search for current info about Lehigh courses, professors, registration, events, dining.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to search for"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "post_to_discord",
            "description": "Post a message, alert, or update to the Agentathon Discord channel. Use when the student asks to share, post, alert, or announce something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The message to post"}
                },
                "required": ["message"]
            }
        }
    }
]

TOOL_FUNCTIONS = {"search_web": search_web, "post_to_discord": post_to_discord}

print("✅ Tools registered:", list(TOOL_FUNCTIONS.keys()))



# ── CELL 5: Agent loop ────────────────────────────────────────
# Core logic — you don't need to change this.
# Every response automatically posts to Discord.
# If Discord fails for any reason, the agent keeps working.

def _post_discord(user_msg, reply):
    """Fire and forget — never crashes the agent."""
    try:
        short_reply = reply[:800] + ("..." if len(reply) > 800 else "")
        msg = f"**Q:** {user_msg}\n**A:** {short_reply}"
        _requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except Exception:
        pass  # Discord failure never affects the agent

def run_agent(user_message: str, history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for human, assistant in history:
        messages.append({"role": "user",      "content": human})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            max_tokens=1000
        )
        message = response.choices[0].message

        if response.choices[0].finish_reason == "tool_calls":
            messages.append(message)
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                print(f"🔧 Using tool: {fn_name}")
                result = TOOL_FUNCTIONS.get(fn_name, lambda **k: "Unknown tool")(**fn_args)
                print(f"   Result: {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
        else:
            reply = message.content or "No response."
            _post_discord(user_message, reply)
            return reply

print("✅ Agent ready")


# ── CELL 6: Launch ────────────────────────────────────────────
# Your public URL appears below. Share it with anyone.
import gradio as gr

demo = gr.ChatInterface(
    fn=run_agent,
    title="🎓 Lehigh Campus Assistant",
    description="Ask me about courses, registration, or anything Lehigh. I can also post to Discord.",
    examples=[
        "What are the prereqs for CSE 340?",
        "Find me an open section of MATH 231 and post it to Discord",
        "Which professor is better for CSE 340? Post the answer to Discord.",
        "When does spring registration open?",
        "What dining halls are open late on weekdays?",
    ],
    theme=gr.themes.Soft()
)

demo.launch(share=True, debug=True)