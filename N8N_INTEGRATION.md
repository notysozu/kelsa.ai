# n8n Integration

This project exposes machine-to-machine endpoints for n8n so workflows can store user data and query the advisor without using browser login cookies.

## Auth

Set an automation key in your app environment:

```env
AUTOMATION_API_KEY=replace-with-a-shared-secret-for-n8n
```

Every n8n request must include:

```http
X-Automation-Key: your-shared-secret
Content-Type: application/json
```

## User resolution

n8n endpoints identify the target user by email.

The user must already exist in `kelsa.ai`.

If the email does not match an existing user, the API returns `404`.

## Endpoint: store structured memory

`POST /api/n8n/memory`

Supported `kind` values:

- `skills`
- `projects`
- `applications`
- `resume`
- `chat`

### Example: skill

```json
{
  "email": "user@example.com",
  "kind": "skills",
  "payload": {
    "name": "FastAPI",
    "level": "advanced",
    "notes": "Added from n8n"
  }
}
```

### Example: project

```json
{
  "email": "user@example.com",
  "kind": "projects",
  "payload": {
    "title": "AI Portfolio Tracker",
    "description": "Tracks projects and skills",
    "tech_stack": "FastAPI, HTML, JavaScript",
    "url": "https://github.com/example/repo"
  }
}
```

### Example: application

```json
{
  "email": "user@example.com",
  "kind": "applications",
  "payload": {
    "company": "Stripe",
    "role": "Backend Intern",
    "status": "applied",
    "date_applied": "2026-03-20",
    "notes": "Submitted through careers page"
  }
}
```

### Example: resume

```json
{
  "email": "user@example.com",
  "kind": "resume",
  "payload": {
    "resume_text": "Full resume text here",
    "target_role": "Backend Intern"
  }
}
```

### Example: chat memory

```json
{
  "email": "user@example.com",
  "kind": "chat",
  "payload": {
    "message": "I want to target data engineering roles."
  }
}
```

## Dedicated endpoint: application tracking

`POST /api/n8n/applications`

### Example

```json
{
  "email": "user@example.com",
  "company": "Stripe",
  "role": "Backend Intern",
  "status": "applied",
  "date_applied": "2026-03-20",
  "notes": "Submitted through careers page"
}
```

## Dedicated endpoint: resume analysis

`POST /api/n8n/resume-analysis`

### Example

```json
{
  "email": "user@example.com",
  "resume_text": "Full resume text here",
  "target_role": "Backend Intern"
}
```

## Endpoint: advisor prompt

`POST /api/n8n/advisor`

### Example

```json
{
  "email": "user@example.com",
  "message": "Given everything stored for this user, what should they focus on next?"
}
```

## Prompt templates for every n8n input path

These are practical prompt patterns you can drop into n8n when you build payloads for `kelsa.ai`.

### Skills memory prompt

Use when an upstream AI step extracts a skill from a transcript, form, CV, or interview note.

```text
Extract one concrete skill update for this user.
Return JSON with:
- name
- level
- notes

Only return valid JSON.
```

### Projects memory prompt

Use when turning free-form project notes into a structured project payload.

```text
Convert this project description into JSON for kelsa.ai.
Return:
- title
- description
- tech_stack
- url

If url is unknown, return an empty string.
Only return valid JSON.
```

### Applications memory prompt

Use when parsing job application updates from email, ATS exports, or manual notes.

```text
Extract a job application record for kelsa.ai.
Return JSON with:
- company
- role
- status
- date_applied
- notes

Use ISO date format YYYY-MM-DD when possible.
Only return valid JSON.
```

### Resume analysis prompt

Use when you want n8n to feed resume text directly into the dedicated analysis endpoint.

```text
Prepare a resume analysis request for kelsa.ai.
Return JSON with:
- resume_text
- target_role

Do not summarize or shorten the resume_text.
Only return valid JSON.
```

### Chat memory prompt

Use when storing a user preference or career intention as chat memory.

```text
Rewrite this note as a single first-person user message for memory storage.
Return JSON with:
- message

Keep it concise and faithful to the original meaning.
Only return valid JSON.
```

### Advisor prompt template

Use before calling `/api/n8n/advisor` when you want a strong synthesized answer from all stored user memory.

```text
Write a single advisor question for kelsa.ai using this goal:

"Given everything already stored for this user, provide the most useful next-step guidance."

Return JSON with:
- message

Keep the question specific and action-oriented.
Only return valid JSON.
```

## Example n8n payload wrappers

### Skills

```json
{
  "email": "user@example.com",
  "kind": "skills",
  "payload": {
    "name": "FastAPI",
    "level": "advanced",
    "notes": "Built authenticated multi-user API routes."
  }
}
```

### Projects

```json
{
  "email": "user@example.com",
  "kind": "projects",
  "payload": {
    "title": "kelsa.ai",
    "description": "Career copilot with per-user memory and advisor flows.",
    "tech_stack": "FastAPI, HTML, JavaScript",
    "url": "https://github.com/example/kelsa-ai"
  }
}
```

### Chat

```json
{
  "email": "user@example.com",
  "kind": "chat",
  "payload": {
    "message": "I want to focus on backend internships and improve my system design skills."
  }
}
```

## Behavior

### When Hindsight is enabled

- stored data is tagged per user
- recall and reflect use the user-specific Hindsight tag
- advisor responses are generated from Hindsight-scoped memory

### When Hindsight is disabled

- data is written to `memory_store.json`
- advisor responses use the local fallback logic

## Suggested n8n workflow pattern

1. Trigger from webhook, form, CRM event, or schedule.
2. Use an HTTP Request node to call `/api/n8n/memory` for general structured data.
3. Use `/api/n8n/applications` when the workflow is specifically logging internship applications.
4. Use `/api/n8n/resume-analysis` when the workflow needs a resume review result.
5. Use another HTTP Request node to call `/api/n8n/advisor` when you want a synthesized response.
6. Send the returned advisor response to Slack, email, Notion, or another downstream node.

## Common failure cases

- `401`: missing or wrong `X-Automation-Key`
- `404`: user email not found
- `400`: unsupported `kind`
- `422`: payload shape does not match the selected kind

## HTML app note

The browser UI does not call the n8n endpoints directly.

- `index.html` uses the normal browser-authenticated routes
- `n8n` uses the machine-authenticated `/api/n8n/...` routes

The HTML app now reads `/api/status` so it can show whether runtime memory is using Hindsight or the local JSON fallback.
