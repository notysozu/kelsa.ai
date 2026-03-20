"""
AI Internship & Career Advisor — Backend
Powered by Hindsight memory for persistent, learning agent behavior.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import json
from datetime import datetime

from hindsight_client import Hindsight

# ─────────────────────────────────────────
# CONFIG — set your Hindsight Cloud details
# ─────────────────────────────────────────
HINDSIGHT_BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
HINDSIGHT_API_KEY  = os.getenv("HINDSIGHT_API_KEY", "")   # set for Cloud
BANK_ID            = "career-advisor-bank"

# ─────────────────────────────────────────
# Hindsight client
# ─────────────────────────────────────────
client = Hindsight(
    base_url=HINDSIGHT_BASE_URL,
    **({"api_key": HINDSIGHT_API_KEY} if HINDSIGHT_API_KEY else {})
)

app = FastAPI(title="AI Career Advisor")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ─────────────────────────────────────────
# Initialise the memory bank on startup
# ─────────────────────────────────────────
@app.on_event("startup")
async def startup():
    try:
        client.create_bank(
            bank_id=BANK_ID,
            name="Career Advisor",
            mission=(
                "You are a personalized AI career advisor for students and early-career professionals. "
                "Extract: skills learned with proficiency levels, projects built with tech stacks, "
                "internship applications (company, role, status, date), interview outcomes, "
                "certifications earned, goals stated by the user, feedback received on resume/profile. "
                "Ignore: greetings, filler phrases, unrelated small talk."
            ),
            disposition={"skepticism": 2, "literalism": 2, "empathy": 4}
        )
        print(f"✅ Bank '{BANK_ID}' ready.")
    except Exception as e:
        # Bank may already exist — that's fine
        print(f"Bank init note: {e}")


# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────
class SkillInput(BaseModel):
    name: str
    level: str           # beginner / intermediate / advanced
    notes: Optional[str] = ""

class ProjectInput(BaseModel):
    title: str
    description: str
    tech_stack: str
    url: Optional[str] = ""

class ApplicationInput(BaseModel):
    company: str
    role: str
    status: str          # applied / interviewing / offered / rejected
    date_applied: str
    notes: Optional[str] = ""

class ResumeInput(BaseModel):
    resume_text: str
    target_role: Optional[str] = ""

class ChatInput(BaseModel):
    message: str


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def retain(content: str, context: str, tags: List[str] = None, doc_id: str = None):
    """Retain a memory with proper tagging and context."""
    item = {
        "content": content,
        "context": context,
        "tags": tags or ["user:default"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if doc_id:
        item["document_id"] = doc_id
    client.retain(bank_id=BANK_ID, items=[item])


def recall(query: str, types: List[str] = None) -> List[dict]:
    """Recall relevant memories for a query."""
    kwargs = dict(
        bank_id=BANK_ID,
        query=query,
        tags=["user:default"],
        tags_match="any_strict",
        budget="mid",
    )
    if types:
        kwargs["types"] = types
    results = client.recall(**kwargs)
    return [{"text": r.text, "type": getattr(r, "type", "fact")} for r in (results.results if hasattr(results, "results") else results)]


def reflect(query: str) -> str:
    """Let Hindsight reason over memory and return a synthesized answer."""
    result = client.reflect(bank_id=BANK_ID, query=query)
    return result.text if hasattr(result, "text") else str(result)


# ─────────────────────────────────────────
# ROUTES — Serve frontend
# ─────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("static/index.html")


# ─────────────────────────────────────────
# ROUTE — Skills Tracker
# ─────────────────────────────────────────
@app.post("/api/skills/add")
def add_skill(skill: SkillInput):
    content = (
        f"Skill added: {skill.name} at {skill.level} level."
        + (f" Notes: {skill.notes}" if skill.notes else "")
    )
    retain(
        content=content,
        context=f"User logged a skill: {skill.name}",
        tags=["user:default", "topic:skills"],
        doc_id=f"skill-{skill.name.lower().replace(' ', '-')}"
    )
    return {"status": "saved", "message": f"Skill '{skill.name}' remembered!"}


@app.get("/api/skills/summary")
def skills_summary():
    memories = recall("What skills has the user learned and at what level?", types=["observation", "world", "experience"])
    answer = reflect("List all the skills this user has learned, with their proficiency levels. Format as a structured summary.")
    return {"memories": memories, "summary": answer}


# ─────────────────────────────────────────
# ROUTE — Project Portfolio
# ─────────────────────────────────────────
@app.post("/api/projects/add")
def add_project(project: ProjectInput):
    content = (
        f"Project built: '{project.title}'. "
        f"Description: {project.description}. "
        f"Tech stack used: {project.tech_stack}."
        + (f" URL: {project.url}" if project.url else "")
    )
    retain(
        content=content,
        context=f"User added a project to their portfolio: {project.title}",
        tags=["user:default", "topic:projects"],
        doc_id=f"project-{project.title.lower().replace(' ', '-')[:40]}"
    )
    return {"status": "saved", "message": f"Project '{project.title}' added to your portfolio memory!"}


@app.get("/api/projects/summary")
def projects_summary():
    memories = recall("What projects has the user built?", types=["observation", "world", "experience"])
    answer = reflect(
        "Summarize all projects this user has built. For each project, mention the title, "
        "what it does, and the tech stack used."
    )
    return {"memories": memories, "summary": answer}


# ─────────────────────────────────────────
# ROUTE — Internship Application Tracker
# ─────────────────────────────────────────
@app.post("/api/applications/add")
def add_application(app_input: ApplicationInput):
    content = (
        f"Internship application: {app_input.role} at {app_input.company}. "
        f"Status: {app_input.status}. Applied on: {app_input.date_applied}."
        + (f" Notes: {app_input.notes}" if app_input.notes else "")
    )
    retain(
        content=content,
        context=f"User logged an internship application to {app_input.company}",
        tags=["user:default", "topic:applications"],
        doc_id=f"app-{app_input.company.lower().replace(' ', '-')}-{app_input.role.lower().replace(' ', '-')[:20]}"
    )
    return {"status": "saved", "message": f"Application to {app_input.company} tracked!"}


@app.get("/api/applications/summary")
def applications_summary():
    memories = recall("What internships has the user applied to and what are the statuses?", types=["observation", "world", "experience"])
    answer = reflect(
        "Give a full summary of all internship applications this user has made. "
        "Include company, role, status, and any patterns you notice (e.g. which stages they keep reaching, "
        "which types of roles they target). Be honest about patterns."
    )
    return {"memories": memories, "summary": answer}


# ─────────────────────────────────────────
# ROUTE — Resume / Skill Gap Analysis
# ─────────────────────────────────────────
@app.post("/api/resume/analyze")
def analyze_resume(resume: ResumeInput):
    # First retain the resume text as context
    retain(
        content=f"User's resume/profile:\n{resume.resume_text}" + (f"\nTarget role: {resume.target_role}" if resume.target_role else ""),
        context="User submitted their resume for analysis",
        tags=["user:default", "topic:resume"],
        doc_id="resume-latest"
    )

    # Build the analysis query
    target_clause = f"The user is targeting: {resume.target_role}. " if resume.target_role else ""
    query = (
        f"{target_clause}"
        "Based on everything you know about this user — their skills, projects, and applications — "
        "analyze their resume and identify: "
        "1) Strengths that align well with their targets. "
        "2) Skill gaps they need to fill. "
        "3) Projects they should build to strengthen their profile. "
        "4) Specific recommendations to improve their resume. "
        "Be direct and specific, not generic."
    )

    analysis = reflect(query)
    return {"analysis": analysis}


# ─────────────────────────────────────────
# ROUTE — AI Chat (memory-aware advisor)
# ─────────────────────────────────────────
@app.post("/api/chat")
def chat(chat_input: ChatInput):
    # Retain the user's message as context
    retain(
        content=f"User asked: {chat_input.message}",
        context="Career advisor chat interaction",
        tags=["user:default", "topic:chat"],
    )

    # Reflect with full memory context
    answer = reflect(
        f"The user asked: '{chat_input.message}'. "
        "Answer as a knowledgeable career advisor who knows this user's full history — "
        "their skills, projects, applications, and goals. Be specific and personal, not generic."
    )
    return {"response": answer}


# ─────────────────────────────────────────
# ROUTE — Dashboard overview
# ─────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard():
    answer = reflect(
        "Give a concise career dashboard summary for this user. Cover: "
        "1) Top skills they have. "
        "2) Notable projects. "
        "3) Current application pipeline status. "
        "4) The single most important thing they should focus on next. "
        "Keep it brief — 4 short bullet points max."
    )
    return {"summary": answer}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
