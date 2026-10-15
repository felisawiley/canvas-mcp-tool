# assignment-mcp

An MCP server that gives a Claude model a sense of coursework it doesn't
have on its own: what's assigned, what's due, and when the week is heavy —
pulled live from Canvas.

Built from the [CIS 7000](https://www.cis.upenn.edu/) "your-first-instrument"
starter (Computationally Assisted Metacognition, Penn, Fall 2026). The
reasoning for the stack is in [`docs/adr/`](docs/adr/). The Canvas choices
are [ADR-0005](docs/adr/0005-canvas-rest-api-and-academic-week.md),
[ADR-0006](docs/adr/0006-show-the-assignment-not-just-the-deadline.md), and
[ADR-0007](docs/adr/0007-render-runs-on-eastern-time.md).

## Tools

| Tool | What it does |
|---|---|
| `canvas()` | Active courses, their instructors, modules, and latest announcements. |
| `assignments(course?)` | Published assignments, optionally one course by name or code. Each line has the due date, points, how you submit, whether it's turned in, the Canvas link, and a short description. |
| `due_this_week()` | Assignments due in the current Monday–Sunday week, earliest first. The heading names the week. |
| `academic_week()` | What's due this week, which classes it comes from, what's coming next week, and which days or courses are unusually loaded. |

## Setup

1. Canvas → Account → Settings → **New access token**. Copy it.
2. Put it in a `.env` file in this folder (that file stays uncommitted):

```bash
CANVAS_API_TOKEN=paste-your-token
CANVAS_BASE_URL=https://canvas.upenn.edu
```

`CANVAS_BASE_URL` can be omitted when you are on Penn's Canvas.

## Run it locally

```bash
uv run server.py     # starts the server on port 8000
```

Connect it to the `claude` CLI:

```bash
claude mcp add --transport http assignment-mcp http://localhost:8000/mcp
```

Then ask Claude something like "what's due this week?" or "give me a
synthesis of my academic week."

Check the week boundary and the way a card is formatted without a token:

```bash
uv run python -m unittest test_server.py
```

## Connect to claude.ai (browser)

claude.ai calls from Anthropic's cloud, so it can't reach `localhost`
directly — you need a tunnel or a deployment.

**Tunnel (temporary, dies with your terminal):**

```bash
cloudflared tunnel --url http://localhost:8000
```

Add the printed `https://….trycloudflare.com/mcp` URL under claude.ai →
Settings → Connectors.

**Deploy to Render (permanent, free tier):**

1. [render.com](https://render.com) → Sign in with GitHub → **New +** →
   **Blueprint** → select this repo → **Apply**. (`render.yaml` handles the
   rest, including `TZ=America/New_York` so "this week" is a Penn week.)
2. Set `CANVAS_API_TOKEN` on the `assignment-mcp` service. Render does not
   store that value in git. If the service already exists, open it →
   **Environment** → add the variable.
3. Copy the resulting `https://….onrender.com` URL and point a claude.ai
   connector at `https://….onrender.com/mcp`.

Free tier note: the instance naps when idle, so the first call after a nap
takes ~30s.

## Project layout

- [`server.py`](server.py) — the four Canvas tools.
- [`test_server.py`](test_server.py) — the Monday week boundary, and what a formatted assignment contains.
- [`docs/adr/`](docs/adr/) — why this stack, why the assignments API, why Eastern time on Render.
- [`render.yaml`](render.yaml) — Render deployment config.

## License

MPL-2.0, with an additional grant covering work built from this template — see [LICENSE.txt](LICENSE.txt) and [TEMPLATE-GRANT.md](TEMPLATE-GRANT.md).
