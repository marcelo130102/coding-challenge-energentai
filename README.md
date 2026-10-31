Author: Marcelo Surco

# Claude Quickstarts

## Homework submission (this repository)

Treat this **private** repository as the **single deliverable** for reviewers: architecture, how to run the service, and what the demo video must show.

| Requirement | Where it is addressed |
|-------------|----------------------|
| **Working implementation** | [`computer-use-demo/`](./computer-use-demo): **FastAPI** control plane, **one Docker container per session** (dynamically spawned per new session—no hard-coded “only 2 concurrent” architecture), **WebSocket** realtime relay, **SQLAlchemy** persistence (SQLite by default; optional PostgreSQL for scaled API). |
| **Detailed README** | This file (submission summary + video) and [`computer-use-demo/README.md`](./computer-use-demo/README.md) (technical deep dive). |

### Demo video (~5 minutes, with audio)

**Demo video URL:** [https://www.youtube.com/watch?v=hUWH4j2vaI4](https://www.youtube.com/watch?v=hUWH4j2vaI4)

Minimum script the video must cover:

1. **Repository and codebase overview** — Key folders, FastAPI backend location, embedded frontend.
2. **Service launch and endpoints** — How you start the stack (e.g. `docker compose up --build` from `computer-use-demo/`), UI URL (e.g. `http://127.0.0.1:8000`), and relevant API/WebSocket routes.
3. **Usage demonstrations**
   - **Usage case 1:** Start a new chat session → prompt **“Search the weather in Dubai”** → show Firefox opening, Google search, and a **realtime** streamed summary.
   - **Usage case 2 (concurrent sessions, strictly non-blocking):** While one task runs (e.g. **“Search the weather in Tokyo”**), submit **in parallel** from another session **“Search the weather in New York”**. Both must **make progress at the same time**; the second must **not** wait for the first (sequential queuing fails the requirement). **Visual verification:** two windows side-by-side (e.g. two browser tabs as User A / User B), **two separate** Firefox automation desktops, Tokyo and New York searches **simultaneously**, summaries in **realtime**. Architecture must **spawn a worker (container) per session** for new requests—not a fixed pool “for demo only.”
4. **Streamlit-like UI behavior** — Show **streaming** progress for intermediate steps while the task runs; after completion, show the UI **prompting for a new task**.

---

## Deliverable: scalable Computer Use backend (this fork)

This fork’s **coding challenge** work lives under **[`computer-use-demo/`](./computer-use-demo)**: a **FastAPI** control plane for Anthropic **Computer Use** with **Docker**-isolated session desktops, **WebSocket** chat and agent relay, optional **SSE** session-status streaming, **SQLAlchemy** persistence (SQLite by default; **PostgreSQL** optional for scaled API deployments), Fernet-encrypted per-session API keys when orchestration is enabled, and a small bundled **HTML/JS** frontend.

**Full documentation (architecture, setup, trade-offs): [computer-use-demo/README.md](./computer-use-demo/README.md)**

---

Claude Quickstarts is a collection of projects designed to help developers quickly get started with building  applications using the Claude API. Each quickstart provides a foundation that you can easily build upon and customize for your specific needs.

## Getting Started

To use these quickstarts, you'll need an Claude API key. If you don't have one yet, you can sign up for free at [console.anthropic.com](https://console.anthropic.com).

## Available Quickstarts

### Customer Support Agent

A customer support agent powered by Claude. This project demonstrates how to leverage Claude's natural language understanding and generation capabilities to create an AI-assisted customer support system with access to a knowledge base.

[Go to Customer Support Agent Quickstart](./customer-support-agent)

### Financial Data Analyst

A financial data analyst powered by Claude. This project demonstrates how to leverage Claude's capabilities with interactive data visualization to analyze financial data via chat.

[Go to Financial Data Analyst Quickstart](./financial-data-analyst)

### Computer Use Demo

An environment and tools that Claude can use to control a desktop computer. This project demonstrates how to leverage the computer use capabilities of Claude, including support for the latest `computer_use_20251124` tool version with zoom actions.

[Go to Computer Use Demo Quickstart](./computer-use-demo)

### Browser Tools API Demo

A complete reference implementation for browser automation powered by Claude. This project demonstrates how to leverage Claude's browser tools API for web interaction, including navigation, DOM inspection, and form manipulation using Playwright.

[Go to Browser Tools API Demo Quickstart](./browser-tools-api-demo)

### Autonomous Coding Agent

An autonomous coding agent powered by the Claude Agent SDK. This project demonstrates a two-agent pattern (initializer + coding agent) that can build complete applications over multiple sessions, with progress persisted via git and a feature list that the agent works through incrementally.

[Go to Autonomous Coding Agent Quickstart](./autonomous-coding)

## General Usage

Each quickstart project comes with its own README and setup instructions. Generally, you'll follow these steps:

1. Clone this repository
2. Navigate to the specific quickstart directory
3. Install the required dependencies
4. Set up your Claude API key as an environment variable
5. Run the quickstart application

## Explore Further

To deepen your understanding of working with Claude and the Claude API, check out these resources:

- [Claude API Documentation](https://docs.claude.com)
- [Claude Cookbooks](https://github.com/anthropics/claude-cookbooks) - A collection of code snippets and guides for common tasks
- [Claude API Fundamentals Course](https://github.com/anthropics/courses/tree/master/anthropic_api_fundamentals)

## Contributing

We welcome contributions to the Claude Quickstarts repository! If you have ideas for new quickstart projects or improvements to existing ones, please open an issue or submit a pull request.

## Community and Support

- Join our [Anthropic Discord community](https://www.anthropic.com/discord) for discussions and support
- Check out the [Anthropic support documentation](https://support.anthropic.com) for additional help

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
