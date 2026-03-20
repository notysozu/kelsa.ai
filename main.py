"""
AI Internship & Career Advisor backend.

Runs with Hindsight when available, and falls back to a lightweight
local JSON memory store so the app still works in a plain local setup.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

try:
    from hindsight_client import Hindsight  # type: ignore
except ImportError:
    Hindsight = None


BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
MEMORY_FILE = BASE_DIR / "memory_store.json"
USERS_FILE = BASE_DIR / "users.json"

HINDSIGHT_BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "hsk_538ca0b5afd27305ff5bfcf1b9fccd26_af2d4435b1d25c5a")
HINDSIGHT_ENABLED = os.getenv("HINDSIGHT_ENABLED", "").lower() in {"1", "true", "yes"}
SESSION_COOKIE_NAME = "kelsa_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-change-me")
BANK_ID = "career-advisor-bank"


class SkillInput(BaseModel):
    name: str
    level: str
    notes: Optional[str] = ""


class ProjectInput(BaseModel):
    title: str
    description: str
    tech_stack: str
    url: Optional[str] = ""


class ApplicationInput(BaseModel):
    company: str
    role: str
    status: str
    date_applied: str
    notes: Optional[str] = ""


class ResumeInput(BaseModel):
    resume_text: str
    target_role: Optional[str] = ""


class ChatInput(BaseModel):
    message: str


class UserCreateInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class StoredUser(BaseModel):
    id: str
    name: str
    email: EmailStr
    hashed_password: str
    created_at: str


class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr
    created_at: str


class LocalUserStore:
    """Simple JSON-backed user store for local development."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"users": []}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"users": []}

        if not isinstance(data, dict):
            return {"users": []}

        users = data.get("users", [])
        return {"users": users if isinstance(users, list) else []}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def list_users(self) -> list[StoredUser]:
        return [StoredUser(**item) for item in self.data.get("users", [])]

    def get_by_email(self, email: str) -> Optional[StoredUser]:
        normalized_email = email.strip().lower()
        for user in self.list_users():
            if user.email.lower() == normalized_email:
                return user
        return None

    def get_by_id(self, user_id: str) -> Optional[StoredUser]:
        for user in self.list_users():
            if user.id == user_id:
                return user
        return None

    def create_user(self, *, name: str, email: str, hashed_password: str) -> StoredUser:
        user = StoredUser(
            id=str(uuid.uuid4()),
            name=name.strip(),
            email=email.strip().lower(),
            hashed_password=hashed_password,
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        self.data.setdefault("users", []).append(user.model_dump())
        self._save()
        return user


class LocalMemoryStore:
    """Tiny JSON-backed fallback used when Hindsight is unavailable."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {
                "skills": [],
                "projects": [],
                "applications": [],
                "resume": [],
                "chat": [],
            }

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {
                "skills": [],
                "projects": [],
                "applications": [],
                "resume": [],
                "chat": [],
            }

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def add(self, kind: str, payload: dict[str, Any], user_id: Optional[str] = None) -> None:
        self.data.setdefault(kind, []).append(
            {
                **payload,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        self._save()

    def list(self, kind: str, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        items = self.data.get(kind, [])
        if user_id is None:
            return items
        return [item for item in items if item.get("user_id") == user_id]

    def latest(self, kind: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        items = self.list(kind, user_id=user_id)
        return items[-1] if items else None


user_store = LocalUserStore(USERS_FILE)
local_store = LocalMemoryStore(MEMORY_FILE)
client = None
use_hindsight = False

if HINDSIGHT_ENABLED and Hindsight is not None:
    try:
        client = Hindsight(
            base_url=HINDSIGHT_BASE_URL,
            **({"api_key": HINDSIGHT_API_KEY} if HINDSIGHT_API_KEY else {}),
        )
        use_hindsight = True
    except Exception:
        client = None
        use_hindsight = False


app = FastAPI(title="AI Career Advisor")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
session_serializer = URLSafeSerializer(SESSION_SECRET, salt="kelsa-session")


@app.on_event("startup")
async def startup() -> None:
    if not INDEX_FILE.exists():
        raise RuntimeError(f"Missing frontend file: {INDEX_FILE}")

    if not use_hindsight or client is None:
        print("Using local JSON memory store.")
        return

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
            disposition={"skepticism": 2, "literalism": 2, "empathy": 4},
        )
        print(f"Bank '{BANK_ID}' ready.")
    except Exception as exc:
        print(f"Falling back to local store because Hindsight init failed: {exc}")


def retain(content: str, context: str, tags: Optional[List[str]] = None, doc_id: Optional[str] = None) -> None:
    item = {
        "content": content,
        "context": context,
        "tags": tags or ["user:default"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if doc_id:
        item["document_id"] = doc_id

    if use_hindsight and client is not None:
        try:
            client.retain(bank_id=BANK_ID, items=[item])
            return
        except Exception:
            pass


def to_public_user(user: StoredUser) -> UserPublic:
    return UserPublic(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
    )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_session_token(user_id: str) -> str:
    return session_serializer.dumps({"user_id": user_id})


def read_session_token(token: str) -> Optional[str]:
    try:
        payload = session_serializer.loads(token)
    except BadSignature:
        return None

    user_id = payload.get("user_id")
    return user_id if isinstance(user_id, str) else None


def set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME)


def get_current_user(session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> StoredUser:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user_id = read_session_token(session_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session.",
        )

    user = user_store.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for session.",
        )

    return user


def get_user_tag(user: StoredUser) -> str:
    return f"user:{user.id}"


def recall(user: StoredUser, query: str, types: Optional[List[str]] = None) -> List[dict[str, str]]:
    if use_hindsight and client is not None:
        try:
            kwargs = dict(
                bank_id=BANK_ID,
                query=query,
                tags=[get_user_tag(user)],
                tags_match="any_strict",
                budget="mid",
            )
            if types:
                kwargs["types"] = types
            results = client.recall(**kwargs)
            output = results.results if hasattr(results, "results") else results
            return [
                {"text": item.text, "type": getattr(item, "type", "fact")}
                for item in output
            ]
        except Exception:
            pass

    snippets: list[dict[str, str]] = []
    for kind in ("skills", "projects", "applications", "resume", "chat"):
        for item in local_store.list(kind, user_id=user.id):
            text = item.get("content") or item.get("summary") or json.dumps(item)
            snippets.append({"text": text, "type": kind})
    return snippets[-10:]


def _local_skills_summary(user: StoredUser) -> str:
    skills = local_store.list("skills", user_id=user.id)
    if not skills:
        return "No skills logged yet."
    return "\n".join(
        f"- {item['name']}: {item['level']}" + (f" ({item['notes']})" if item.get("notes") else "")
        for item in skills
    )


def _local_projects_summary(user: StoredUser) -> str:
    projects = local_store.list("projects", user_id=user.id)
    if not projects:
        return "No projects logged yet."
    return "\n".join(
        f"- {item['title']}: {item['description']} Tech stack: {item['tech_stack']}."
        + (f" URL: {item['url']}" if item.get("url") else "")
        for item in projects
    )


def _local_applications_summary(user: StoredUser) -> str:
    applications = local_store.list("applications", user_id=user.id)
    if not applications:
        return "No internship applications logged yet."
    return "\n".join(
        f"- {item['role']} at {item['company']}: {item['status']} (applied {item['date_applied']})"
        + (f". Notes: {item['notes']}" if item.get("notes") else "")
        for item in applications
    )


def _local_resume_analysis(user: StoredUser) -> str:
    resume = local_store.latest("resume", user_id=user.id)
    skills = local_store.list("skills", user_id=user.id)
    projects = local_store.list("projects", user_id=user.id)

    if not resume:
        return "Upload a resume first so I can analyze it."

    target_role = resume.get("target_role") or "your target role"
    strengths = ", ".join(skill["name"] for skill in skills[:5]) or "the experience already listed on the resume"
    project_gap = "Add one measurable, portfolio-quality project tied to the role you want." if not projects else "Make sure each listed project has outcomes and metrics."

    return (
        f"Target role: {target_role}\n"
        f"Strengths: Your current profile highlights {strengths}.\n"
        "Skill gaps: Add more measurable evidence, impact metrics, and role-specific keywords.\n"
        f"Projects: {project_gap}\n"
        "Resume improvements: tighten bullet points, lead with outcomes, and align the summary with the target role."
    )


def _local_dashboard_summary(user: StoredUser) -> str:
    skills = local_store.list("skills", user_id=user.id)
    projects = local_store.list("projects", user_id=user.id)
    applications = local_store.list("applications", user_id=user.id)

    top_skills = ", ".join(item["name"] for item in skills[:3]) or "No skills logged yet"
    top_projects = ", ".join(item["title"] for item in projects[:2]) or "No projects logged yet"
    active_apps = ", ".join(
        f"{item['company']} ({item['status']})" for item in applications[:3]
    ) or "No applications tracked yet"

    focus = "Log your skills, strongest projects, and current internship applications to unlock better advice."
    if skills or projects or applications:
        focus = "Turn your strongest skills into role-specific projects and keep your application tracker up to date."

    return (
        f"- Top skills: {top_skills}\n"
        f"- Notable projects: {top_projects}\n"
        f"- Application pipeline: {active_apps}\n"
        f"- Next focus: {focus}"
    )


def _local_chat_response(user: StoredUser, message: str) -> str:
    skills = local_store.list("skills", user_id=user.id)
    projects = local_store.list("projects", user_id=user.id)
    applications = local_store.list("applications", user_id=user.id)

    context_bits = []
    if skills:
        context_bits.append("skills: " + ", ".join(item["name"] for item in skills[:5]))
    if projects:
        context_bits.append("projects: " + ", ".join(item["title"] for item in projects[:3]))
    if applications:
        context_bits.append(
            "applications: " + ", ".join(f"{item['company']} ({item['status']})" for item in applications[:3])
        )

    context = "; ".join(context_bits) if context_bits else "no saved history yet"
    return (
        f"You asked: {message}\n"
        f"Current context: {context}.\n"
        "Best next step: focus on measurable project outcomes, target roles that match your strongest skills, "
        "and keep tracking application progress so future advice can get sharper."
    )


def reflect(user: StoredUser, query: str) -> str:
    if use_hindsight and client is not None:
        try:
            result = client.reflect(bank_id=BANK_ID, query=query)
            return result.text if hasattr(result, "text") else str(result)
        except Exception:
            pass

    lowered = query.lower()
    if "career dashboard summary" in lowered:
        return _local_dashboard_summary(user)
    if "skills" in lowered and "proficiency" in lowered:
        return _local_skills_summary(user)
    if "projects" in lowered and "built" in lowered:
        return _local_projects_summary(user)
    if "internship applications" in lowered or "application pipeline" in lowered:
        return _local_applications_summary(user)
    if "analyze their resume" in lowered:
        return _local_resume_analysis(user)
    if "the user asked:" in lowered:
        return _local_chat_response(user, query)
    return "Memory is available, but no detailed reflection is available for that query in local mode yet."


@app.get("/")
def root() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(user_input: UserCreateInput, response: Response) -> dict[str, Any]:
    existing_user = user_store.get_by_email(str(user_input.email))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    created_user = user_store.create_user(
        name=user_input.name,
        email=str(user_input.email),
        hashed_password=hash_password(user_input.password),
    )
    set_session_cookie(response, created_user.id)
    return {
        "message": "Account created successfully.",
        "user": to_public_user(created_user).model_dump(),
    }


@app.post("/api/auth/login")
def login(user_input: UserLoginInput, response: Response) -> dict[str, Any]:
    user = user_store.get_by_email(str(user_input.email))
    if user is None or not verify_password(user_input.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    set_session_cookie(response, user.id)
    return {
        "message": "Logged in successfully.",
        "user": to_public_user(user).model_dump(),
    }


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"message": "Logged out successfully."}


@app.get("/api/auth/me")
def current_user(current_user: StoredUser = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": to_public_user(current_user).model_dump()}


@app.post("/api/skills/add")
def add_skill(skill: SkillInput, current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    content = (
        f"Skill added: {skill.name} at {skill.level} level."
        + (f" Notes: {skill.notes}" if skill.notes else "")
    )
    retain(
        content=content,
        context=f"User logged a skill: {skill.name}",
        tags=[get_user_tag(current_user), "topic:skills"],
        doc_id=f"{current_user.id}-skill-{skill.name.lower().replace(' ', '-')}",
    )
    local_store.add(
        "skills",
        {"name": skill.name, "level": skill.level, "notes": skill.notes, "content": content},
        user_id=current_user.id,
    )
    return {"status": "saved", "message": f"Skill '{skill.name}' remembered!"}


@app.get("/api/skills/summary")
def skills_summary(current_user: StoredUser = Depends(get_current_user)) -> dict[str, Any]:
    memories = recall(
        current_user,
        "What skills has the user learned and at what level?",
        types=["observation", "world", "experience"],
    )
    answer = reflect(
        current_user,
        "List all the skills this user has learned, with their proficiency levels. Format as a structured summary."
    )
    return {"memories": memories, "summary": answer}


@app.post("/api/projects/add")
def add_project(project: ProjectInput, current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    content = (
        f"Project built: '{project.title}'. "
        f"Description: {project.description}. "
        f"Tech stack used: {project.tech_stack}."
        + (f" URL: {project.url}" if project.url else "")
    )
    retain(
        content=content,
        context=f"User added a project to their portfolio: {project.title}",
        tags=[get_user_tag(current_user), "topic:projects"],
        doc_id=f"{current_user.id}-project-{project.title.lower().replace(' ', '-')[:40]}",
    )
    local_store.add(
        "projects",
        {
            "title": project.title,
            "description": project.description,
            "tech_stack": project.tech_stack,
            "url": project.url,
            "content": content,
        },
        user_id=current_user.id,
    )
    return {"status": "saved", "message": f"Project '{project.title}' added to your portfolio memory!"}


@app.get("/api/projects/summary")
def projects_summary(current_user: StoredUser = Depends(get_current_user)) -> dict[str, Any]:
    memories = recall(current_user, "What projects has the user built?", types=["observation", "world", "experience"])
    answer = reflect(
        current_user,
        "Summarize all projects this user has built. For each project, mention the title, "
        "what it does, and the tech stack used."
    )
    return {"memories": memories, "summary": answer}


@app.post("/api/applications/add")
def add_application(app_input: ApplicationInput, current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    content = (
        f"Internship application: {app_input.role} at {app_input.company}. "
        f"Status: {app_input.status}. Applied on: {app_input.date_applied}."
        + (f" Notes: {app_input.notes}" if app_input.notes else "")
    )
    retain(
        content=content,
        context=f"User logged an internship application to {app_input.company}",
        tags=[get_user_tag(current_user), "topic:applications"],
        doc_id=f"{current_user.id}-app-{app_input.company.lower().replace(' ', '-')}-{app_input.role.lower().replace(' ', '-')[:20]}",
    )
    local_store.add(
        "applications",
        {
            "company": app_input.company,
            "role": app_input.role,
            "status": app_input.status,
            "date_applied": app_input.date_applied,
            "notes": app_input.notes,
            "content": content,
        },
        user_id=current_user.id,
    )
    return {"status": "saved", "message": f"Application to {app_input.company} tracked!"}


@app.get("/api/applications/summary")
def applications_summary(current_user: StoredUser = Depends(get_current_user)) -> dict[str, Any]:
    memories = recall(
        current_user,
        "What internships has the user applied to and what are the statuses?",
        types=["observation", "world", "experience"],
    )
    answer = reflect(
        current_user,
        "Give a full summary of all internship applications this user has made. "
        "Include company, role, status, and any patterns you notice (e.g. which stages they keep reaching, "
        "which types of roles they target). Be honest about patterns."
    )
    return {"memories": memories, "summary": answer}


@app.post("/api/resume/analyze")
def analyze_resume(resume: ResumeInput, current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    content = (
        f"User's resume/profile:\n{resume.resume_text}"
        + (f"\nTarget role: {resume.target_role}" if resume.target_role else "")
    )
    retain(
        content=content,
        context="User submitted their resume for analysis",
        tags=[get_user_tag(current_user), "topic:resume"],
        doc_id=f"{current_user.id}-resume-latest",
    )
    local_store.add(
        "resume",
        {
            "resume_text": resume.resume_text,
            "target_role": resume.target_role,
            "content": content,
        },
        user_id=current_user.id,
    )

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

    return {"analysis": reflect(current_user, query)}


@app.post("/api/chat")
def chat(chat_input: ChatInput, current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    content = f"User asked: {chat_input.message}"
    retain(
        content=content,
        context="Career advisor chat interaction",
        tags=[get_user_tag(current_user), "topic:chat"],
    )
    local_store.add("chat", {"message": chat_input.message, "content": content}, user_id=current_user.id)

    answer = reflect(
        current_user,
        f"The user asked: '{chat_input.message}'. "
        "Answer as a knowledgeable career advisor who knows this user's full history — "
        "their skills, projects, applications, and goals. Be specific and personal, not generic."
    )
    return {"response": answer}


@app.get("/api/dashboard")
def dashboard(current_user: StoredUser = Depends(get_current_user)) -> dict[str, str]:
    answer = reflect(
        current_user,
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

    uvicorn.run("main:app", host="0.0.0.0", port=8090, reload=True)
