# assignment-mcp

Read-only Canvas tools for a Claude model: your active courses, your published assignments, and the current academic week.

The week runs Monday 00:00 through Sunday in the server's local timezone. On Render that timezone is `America/New_York`. Locally it is whatever timezone the machine is using.

## Tools

| Tool | What it returns |
|---|---|
| `canvas()` | Active courses, instructors, up to ten modules each, and the two latest announcements. |
| `assignments(course?)` | Every published assignment, earliest due date first. Pass a course name or code (`CIS 7000`) to limit it to one class. |
| `due_this_week()` | Assignments due this Monday–Sunday week. The first line names the week and the timezone. |
| `academic_week()` | This week, next week, and where the load is heavy: two or more due the same day, or two or more from the same course. |

`assignments()` includes how you turn the work in and a short plain-text description. The week tools stay shorter: course, name, due date, points, turn-in status, and the Canvas link. A line looks like this:

```text
- [CIS 7000] Reading response — due Sun Oct 18, 11:59 PM (10 pts) · text entry · submitted
  https://canvas.upenn.edu/courses/1/assignments/2
  Write 300 words.
```

Status is shown when it changes what you would do next (`submitted`, `graded`, `pending review`, `missing`, `late`). An assignment you have not turned in yet has no status word.

## Setup

1. In Canvas, open Account → Settings → **New access token**. Copy the token. It is a password for your courses: it goes in `.env` only, never in git or chat.
2. From this folder:

```bash
cp .env.example .env
```

3. Put the token in `.env`:

```bash
CANVAS_API_TOKEN=paste-your-token
CANVAS_BASE_URL=https://canvas.upenn.edu
```

Leave `CANVAS_BASE_URL` as is for Penn. Change it if the courses live on another Canvas.

## Run it locally

From this folder:

```bash
uv run server.py
```

The server listens on port 8000, or on `PORT` if that variable is set.

Connect it to the `claude` CLI:

```bash
claude mcp add --transport http assignment-mcp http://localhost:8000/mcp
```

Then ask Claude "what's due this week?" or "what do I still have to turn in for CIS 7000?"

The week boundary and the assignment line can be checked without a Canvas token:

```bash
uv run python -m unittest test_server.py
```

## Connect to claude.ai

claude.ai calls from Anthropic's cloud, so it cannot reach `localhost`. Use a tunnel or Render.

**Tunnel.** This lasts until you close the terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

In claude.ai, open Settings → Connectors and add the printed `https://….trycloudflare.com/mcp` URL.

**Render.** This stays up:

1. [render.com](https://render.com) → Sign in with GitHub → **New +** → **Blueprint** → select this repo → **Apply**. [`render.yaml`](render.yaml) creates the `assignment-mcp` service and sets `TZ=America/New_York`.
2. Open that service → **Environment** → add `CANVAS_API_TOKEN` with the token from Setup. Render does not read it from git. If the Blueprint already exists, add the variable there and save. Render redeploys the service.
3. Point the claude.ai connector at `https://<your-service>.onrender.com/mcp`.

On the free plan the instance sleeps when idle. The first call after a nap takes about 30 seconds.

## Project layout

- [`server.py`](server.py) — the four Canvas tools.
- [`.env.example`](.env.example) — the variable names, with no token in them.
- [`test_server.py`](test_server.py) — Monday week boundary, and what a formatted assignment contains.
- [`docs/adr/`](docs/adr/) — why these choices: the assignments API ([ADR-0005](docs/adr/0005-canvas-rest-api-and-academic-week.md)), what a line includes ([ADR-0006](docs/adr/0006-show-the-assignment-not-just-the-deadline.md)), and Eastern time on Render ([ADR-0007](docs/adr/0007-render-runs-on-eastern-time.md)).
- [`render.yaml`](render.yaml) — the Render service.

## License

MPL-2.0, plus the grant for work built from the course template. See [LICENSE.txt](LICENSE.txt), [TEMPLATE-GRANT.md](TEMPLATE-GRANT.md), and [NOTICE.txt](NOTICE.txt).
