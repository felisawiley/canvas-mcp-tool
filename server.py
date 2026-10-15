"""assignment-mcp — a sense of coursework for a model that has none.

Ask your Claude "what's due this week?" without this connected: it can't
know, because Canvas isn't in its context window. This server hands it a
read-only view of Canvas — courses, assignments, due dates — through the
same REST API Canvas's own web UI calls. See docs/adr/ for the reasoning.
"""
import html as html_lib
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    "assignment-mcp",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
)

CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "https://canvas.upenn.edu").rstrip("/")
CANVAS_API_TOKEN = os.environ.get("CANVAS_API_TOKEN", "")

SUBMISSION_LABELS = {
    "online_upload": "file upload",
    "online_text_entry": "text entry",
    "online_quiz": "quiz",
    "online_url": "link",
    "media_recording": "media recording",
    "student_annotation": "annotation",
    "discussion_topic": "discussion",
    "on_paper": "on paper",
    "external_tool": "external tool",
    "wiki_page": "wiki page",
    "none": "no submission",
}


def _client() -> httpx.Client:
    if not CANVAS_API_TOKEN:
        raise RuntimeError(
            "Set CANVAS_API_TOKEN — Canvas → Account → Settings → "
            "+ New Access Token. Set CANVAS_BASE_URL too if you're not on "
            "Penn's Canvas (default: https://canvas.upenn.edu)."
        )
    return httpx.Client(
        base_url=f"{CANVAS_BASE_URL}/api/v1",
        headers={"Authorization": f"Bearer {CANVAS_API_TOKEN}"},
        timeout=20,
    )


def _call(fn):
    try:
        return fn()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            raise RuntimeError(
                "Canvas rejected CANVAS_API_TOKEN. Create a new token under "
                "Canvas → Account → Settings → New Access Token, and update "
                "the environment variable."
            ) from exc
        raise RuntimeError(f"Canvas returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach Canvas at {CANVAS_BASE_URL}.") from exc


def _get_all(client: httpx.Client, path: str, **params: Any) -> list[dict]:
    """GET `path`, following Canvas's Link-header pagination to the end."""
    items: list[dict] = []
    url: str | None = path
    query: dict[str, Any] | None = {**params, "per_page": 100}
    while url:
        resp = client.get(url, params=query)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list):
            items.extend(payload)
        url = resp.links.get("next", {}).get("url")
        query = None
    return items


def _active_courses(client: httpx.Client) -> list[dict]:
    return _get_all(
        client,
        "/courses",
        enrollment_state="active",
        **{"include[]": ["term", "teachers"]},
    )


def _resolve_courses(client: httpx.Client, course: str | None) -> list[dict]:
    courses = _active_courses(client)
    if course is None:
        return courses
    needle = course.strip().lower()
    matches = [
        c for c in courses
        if needle in (c.get("name") or "").lower()
        or needle in (c.get("course_code") or "").lower()
    ]
    if not matches:
        names = ", ".join(c["name"] for c in courses) or "(none)"
        raise ValueError(f"No active course matches {course!r}. Active courses: {names}")
    return matches


def _parse_due(due_at: str | None) -> datetime | None:
    if not due_at:
        return None
    return datetime.fromisoformat(due_at.replace("Z", "+00:00"))


def _plain(value: str | None, limit: int = 400) -> str:
    """Canvas descriptions are HTML. Keep the words, drop the markup."""
    if not value:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _course_label(course: dict) -> str:
    return (course.get("course_code") or course.get("name") or "course").strip()


def _course_assignments(client: httpx.Client, course: dict) -> list[dict]:
    raw = _get_all(
        client,
        f"/courses/{course['id']}/assignments",
        order_by="due_at",
        **{"include[]": "submission"},
    )
    label = _course_label(course)
    out = []
    for item in raw:
        if item.get("workflow_state") != "published":
            continue
        submission = item.get("submission") or {}
        out.append({
            "course": label,
            "name": item.get("name") or "Untitled",
            "due_at": _parse_due(item.get("due_at")),
            "points_possible": item.get("points_possible"),
            "html_url": item.get("html_url") or "",
            "description": _plain(item.get("description")),
            "submission_types": item.get("submission_types") or [],
            "submission": {
                "workflow_state": submission.get("workflow_state") or "",
                "missing": bool(submission.get("missing")),
                "late": bool(submission.get("late")),
            },
        })
    return out


def _all_assignments(client: httpx.Client, course: str | None = None) -> list[dict]:
    assignments = []
    for item in _resolve_courses(client, course):
        assignments.extend(_course_assignments(client, item))
    distant_future = datetime.max.replace(tzinfo=timezone.utc)
    assignments.sort(key=lambda a: a["due_at"] or distant_future)
    return assignments


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 through the following Monday 00:00, local time.

    Render sets TZ=America/New_York (ADR-0007). A machine without that
    variable uses its own zone (ADR-0005).
    """
    local_now = now.astimezone()
    monday = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday, monday + timedelta(days=7)


def _week_heading(start: datetime, end: datetime) -> str:
    sunday = end - timedelta(seconds=1)
    tz = start.strftime("%Z") or "local"
    return f"{start:%a %b %-d} – {sunday:%a %b %-d} ({tz})"


def _status_label(submission: dict) -> str:
    state = submission.get("workflow_state") or ""
    label = {
        "submitted": "submitted",
        "graded": "graded",
        "pending_review": "pending review",
        "excused": "excused",
    }.get(state, "")
    notes = []
    if label:
        notes.append(label)
    if submission.get("missing"):
        notes.append("missing")
    elif submission.get("late"):
        notes.append("late")
    return ", ".join(notes)


def _kind_label(types: list[str]) -> str:
    labels = [
        SUBMISSION_LABELS.get(kind, kind.replace("_", " "))
        for kind in types
        if kind and kind != "none"
    ]
    return ", ".join(labels)


def _format_assignment(a: dict, *, detailed: bool = False) -> str:
    due = a["due_at"]
    when = due.astimezone().strftime("%a %b %-d, %-I:%M %p") if due else "no due date"
    points = a.get("points_possible")
    pts = f" ({points:g} pts)" if points is not None else ""
    line = f"- [{a['course']}] {a['name']} — due {when}{pts}"
    extras = []
    if detailed:
        kinds = _kind_label(a.get("submission_types") or [])
        if kinds:
            extras.append(kinds)
    status = _status_label(a.get("submission") or {})
    if status:
        extras.append(status)
    if extras:
        line += " · " + " · ".join(extras)
    url = a.get("html_url") or ""
    if url:
        line += f"\n  {url}"
    if detailed and a.get("description"):
        line += f"\n  {a['description']}"
    return line


@mcp.tool()
def canvas() -> str:
    """Active courses, their instructors, modules, and latest announcements."""
    def fetch() -> str:
        with _client() as client:
            courses = _active_courses(client)
            if not courses:
                return "No active courses."
            context_codes = [f"course_{c['id']}" for c in courses]
            announcements = _get_all(
                client,
                "/announcements",
                **{"context_codes[]": context_codes},
                active_only="true",
            )
            by_course: dict[int, list[dict]] = defaultdict(list)
            for ann in announcements:
                cid = int(ann["context_code"].removeprefix("course_"))
                by_course[cid].append(ann)

            blocks = []
            for course in courses:
                teachers = ", ".join(
                    teacher["display_name"] for teacher in course.get("teachers", [])
                ) or "unknown instructor"
                term = course.get("term", {}).get("name", "")
                modules = _get_all(client, f"/courses/{course['id']}/modules")
                module_lines = "\n".join(
                    f"  - {module['name']} ({'published' if module.get('published') else 'unpublished'})"
                    for module in modules[:10]
                ) or "  (none)"
                latest = sorted(
                    by_course.get(course["id"], []),
                    key=lambda ann: ann.get("posted_at") or "",
                    reverse=True,
                )[:2]
                ann_lines = "\n".join(f"  - {ann['title']}" for ann in latest) or "  (none)"
                blocks.append(
                    f"{course['name']} [{term}] — taught by {teachers}\n"
                    f" Modules:\n{module_lines}\n"
                    f" Recent announcements:\n{ann_lines}"
                )
            return "\n\n".join(blocks)

    return _call(fetch)


@mcp.tool()
def assignments(course: str | None = None) -> str:
    """Published assignments, with how to submit, whether it's turned in, and a short description.

    Pass a course name or code to limit the list to one class.
    """
    def fetch() -> str:
        with _client() as client:
            items = _all_assignments(client, course)
        if not items:
            return f"No active assignments{f' for {course}' if course else ''}."
        return "\n".join(_format_assignment(item, detailed=True) for item in items)

    return _call(fetch)


@mcp.tool()
def due_this_week() -> str:
    """Assignments due in the current Monday–Sunday academic week, earliest first."""
    def fetch() -> str:
        now = datetime.now(timezone.utc)
        start, end = _week_bounds(now)
        heading = _week_heading(start, end)
        with _client() as client:
            items = [
                item for item in _all_assignments(client)
                if item["due_at"] and start <= item["due_at"] < end
            ]
        if not items:
            return f"Nothing due the week of {heading}."
        body = "\n".join(_format_assignment(item) for item in items)
        return f"Week of {heading}:\n{body}"

    return _call(fetch)


@mcp.tool()
def academic_week() -> str:
    """What's due this week, which classes it comes from, what's next, and where the week is heavy."""
    def fetch() -> str:
        now = datetime.now(timezone.utc)
        start, end = _week_bounds(now)
        next_start, next_end = end, end + timedelta(days=7)
        with _client() as client:
            all_items = _all_assignments(client)
        this_week = [item for item in all_items if item["due_at"] and start <= item["due_at"] < end]
        next_week = [
            item for item in all_items if item["due_at"] and next_start <= item["due_at"] < next_end
        ]

        lines = [f"This week ({_week_heading(start, end)}):"]
        lines.append(
            "\n".join(_format_assignment(item) for item in this_week) if this_week else "  Nothing due."
        )

        heavy_days = [
            day.strftime("%A %b %-d")
            for day, count in Counter(item["due_at"].astimezone().date() for item in this_week).items()
            if count >= 2
        ]
        heavy_courses = [
            course
            for course, count in Counter(item["course"] for item in this_week).items()
            if count >= 2
        ]
        if heavy_days or heavy_courses:
            lines.append("\nUnusually heavy:")
            for day in heavy_days:
                lines.append(f"  - {day} has multiple assignments due")
            for course in heavy_courses:
                count = sum(1 for item in this_week if item["course"] == course)
                lines.append(f"  - {course} has {count} due this week")
        elif len(this_week) > len(next_week) + 1:
            lines.append(
                f"\nThis week ({len(this_week)} due) is heavier than next week ({len(next_week)} due)."
            )

        lines.append(f"\nComing next week ({_week_heading(next_start, next_end)}):")
        lines.append(
            "\n".join(_format_assignment(item) for item in next_week) if next_week else "  Nothing posted yet."
        )
        return "\n".join(lines)

    return _call(fetch)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
