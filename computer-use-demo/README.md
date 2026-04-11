# Scalable Backend for Anthropic Computer Use Agent Session Management

## Project overview

This project delivers a **production-oriented control plane** for Anthropic’s **Computer Use** capability. It **replaces the experimental single-user Streamlit interface** with a **FastAPI** application backed by **Docker-based session isolation**, so multiple operators can run independent desktop agents safely and concurrently.

The API orchestrates **one isolated “Computer Use” container per session**, exposes a **single WebSocket** for chat and agent telemetry, and persists **sessions and chat history** via **SQLAlchemy** (default **SQLite**; **PostgreSQL** optional for scaled deployments—see [Scaling beyond a single API process](#scaling-beyond-a-single-api-process)).

---

## Core architecture

### Backend: FastAPI

The service is built on **FastAPI** for **async-first** request handling, WebSocket upgrades, and static hosting of the bundled frontend. REST endpoints under `/api` manage sessions; WebSocket routes under `/api/sessions/{id}/ws` drive real-time interaction.

### Session orchestration: Docker SDK

Session lifecycle is implemented with the **Docker SDK** (`docker` Python package). When orchestration is enabled (`COMPUTER_USE_ORCHESTRATION`), each new session:

| Concern | Approach |
|--------|----------|
| **Isolation** | A dedicated container is started from the configured Computer Use image, so each user gets a separate OS desktop, browser, and tool runtime. |
| **Concurrency** | Independent containers avoid shared mutable state and **race conditions** that would arise from a single shared X/VNC stack serving multiple users. |
| **Port mapping** | Host ports are **allocated dynamically** from configured ranges (noVNC and in-container agent API) and recorded on the session record for the UI. |
| **Recovery** | On API restart, the service can **reconcile** in-use ports from running labeled containers so allocations stay consistent. |

API keys and optional **Anthropic-compatible base URLs** are injected into the container environment at start time (see [Environment variables](#environment-variables)).

### Real-time streaming: WebSockets

The chat path uses a **persistent WebSocket** from the browser to the FastAPI process. When a session has an associated in-container **agent HTTP/WebSocket** endpoint, the backend runs an **in-process relay** that:

- Forwards user messages to the container’s agent loop (Anthropic **sampling loop**).
- Streams **assistant output, tool use, progress, and screenshot-related payloads** back to all subscribers for that session.

This yields a **single bidirectional channel** for both user input and rich agent feedback—aligned with how the agent loop emits structured events rather than plain HTTP chunks alone.

**WebSocket vs SSE:** Use **`/api/sessions/{id}/ws` (WebSocket)** whenever you need **bidirectional** chat, agent relay traffic, and live tool/output streaming. Use **`GET /api/sessions/{id}/events` (SSE, `text/event-stream`)** for **server→client** snapshots only—today this streams **session status** from the database on an interval (plus comment heartbeats), without duplicating chat. It suits dashboards, status indicators, or integrations that only consume progress-style updates over a simple HTTP long poll. CORS uses the same allowed origins as the rest of the API.

### Persistence: SQLAlchemy + SQLite

**SQLAlchemy** models back **sessions** (status, ports, API endpoint choice, encrypted API key material when configured) and **messages**. The default database is a **SQLite** file (`computer_use_demo.db` beside the repo, or `/data/...` under Docker Compose when the volume is writable). Schema creation and lightweight migrations run on application startup.

### Scaling beyond a single API process

The control plane uses a **single `DATABASE_URL`** (see `.env.example`). **SQLite** is ideal for **local development** and single-process demos: it is a single file with **one writer at a time**, so running **multiple API worker processes** or **several API hosts** against the same file is a poor fit (locking, corruption risk, no shared HA story). For **production** or **horizontally scaled** FastAPI deployments, point **`DATABASE_URL` at PostgreSQL** (or another server-grade database supported by SQLAlchemy) so sessions and chat history live in a **networked, concurrent-safe** store.

**Session desktops already scale horizontally on the machine:** each user session is a **separate Docker container** with its own ports and resources; adding capacity is largely a matter of **host CPU/RAM** and **Docker**, independent of where the API’s relational state lives. The database choice mainly affects **API state** (metadata, messages, WebSocket/SSE adjacency to DB polling)—not the per-session VM containers themselves.

---

## Key features

- **Concurrent sessions** — Multiple sessions can be active at once; each maps to its own container and port pair.
- **Dynamic host port allocation** — **noVNC** (desktop in browser) and **agent API** ports are chosen from configurable ranges (`NOVNC_HOST_PORT_*`, `AGENT_API_HOST_PORT_*`) to avoid collisions.
- **Anthropic Global API and PackyAPI** — Session creation supports **global** Anthropic endpoints, **PackyAPI** (`https://www.packyapi.com`) for region-specific routing, or a **custom HTTPS base URL** where policy allows.
- **Live interaction log and desktop view** — The UI combines streamed agent activity with an embedded **noVNC** view tied to the session’s allocated desktop port.

---

## Prerequisites & installation

### Prerequisites

- **Docker** and **Docker Compose** (Compose V2).
- A built **Computer Use** desktop image tagged as expected by the API (default: `computer-use-demo:local`).
- For orchestration: access to the **Docker socket** from the API container (Compose file mounts `/var/run/docker.sock`).

### 1. Build the session image

The API does not build the desktop VM image for you. From this directory:

```bash
docker build . -t computer-use-demo:local
```

(`Dockerfile.api` builds only the FastAPI + frontend image used by Compose.)

### 2. Configure environment

Copy `.env.example` to `.env` in `computer-use-demo/` and set at least:

| Variable | Required | Description |
|----------|----------|-------------|
| `SESSION_API_KEY_FERNET_KEY` | **Yes** (orchestration) | Fernet key used to encrypt per-session API keys at rest. Generate once and keep stable. |
| `DATABASE_URL` | No | Defaults to local SQLite. Use a **PostgreSQL** URL (see `.env.example`) for multi-worker / multi-host production; Compose may use `sqlite:////data/...`. |
| `COMPUTER_USE_DOCKER_IMAGE` | No | Image for session containers (default `computer-use-demo:local`). |
| `COMPUTER_USE_ORCHESTRATION` | No | Enable Docker session spawning (default enabled in Compose). |

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Anthropic API keys** are supplied **per session through the UI** (not necessarily as a global `ANTHROPIC_API_KEY` on the API host), and are passed into the spawned container for that session.

### 3. Run with Docker Compose

```bash
docker compose up --build
```

Open **http://127.0.0.1:8000** for the web UI.

> **Security:** Mounting the Docker socket grants the API container powerful control over the host. Use only on **trusted machines** or hardened deployments.

### Local development (optional)

For iterative backend work without Compose, see the repository root `CLAUDE.md`: Python tooling (`ruff`, `pyright`, `pytest`) and patterns for running `uvicorn` against `backend_fastapi.main:app`.

---

## Technical decisions & trade-offs

### Docker isolation vs. multi-display Xvfb on one host

**Chosen: one container per session.**

- **Scalability** — Horizontal scaling is expressed in terms of containers and host resources, not fragile shared display numbering or a single X server bottleneck.
- **Security & blast radius** — Compromise or bad state in one desktop does not trivially affect another user’s session filesystem or process space.
- **Operational clarity** — Session boundaries match container boundaries; restarts and resource limits apply per customer/session.

A multi-display / single-Xvfb approach can reduce per-session overhead but couples failures, complicates cleanup, and is harder to reason about under load.

### WebSockets vs. SSE

**Chosen: WebSockets.**

- The client must send **arbitrary chat messages** and control-style payloads **at any time** while receiving **multiplexed events** (text, tool results, images). A single full-duplex connection maps naturally to that pattern.
- **Server-Sent Events** are excellent for **server→client** streams but are awkward for **symmetric** or high-frequency client→server messaging without extra HTTP requests.

SSE remains a good fit for **read-only** telemetry feeds; this product prioritized **one bidirectional channel** ready for future control messages without protocol churn.

---

## Reviewer instructions

The following collaborators have been invited to review this repository:

| GitHub user |
|-------------|
| lingjiekong |
| ghamry03 |
| goldmermaid |
| EnergentAI |

The codebase is linted (`ruff`), type-checked (`pyright`), and covered by automated tests (`pytest`) as described in `CLAUDE.md`.

---

## Additional references

- Anthropic **Computer Use** overview and safety considerations: [Claude documentation](https://docs.claude.com/) (Computer Use is a beta capability; assess risks before production use).
- Original upstream **Streamlit + single-container** quickstart patterns remain documented in the broader **claude-quickstarts** repository history and Anthropic-published guides for comparison.
