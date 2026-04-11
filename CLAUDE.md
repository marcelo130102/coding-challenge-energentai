# Claude Quickstarts Development Guide

## Legal

- When changes are made to files that have a copyright notice add them to that subdirectory's CHANGELOG.md file.

## Computer-Use Demo

### Setup & Development

- **Setup environment**: `./setup.sh`
- **Build Docker (desktop VM image)**: `docker build . -t computer-use-demo:local` (from `computer-use-demo/`)
- **Run FastAPI + browser UI (orchestrator)**: `uvicorn backend_fastapi.main:app --reload --host 127.0.0.1 --port 8000` from `computer-use-demo/` — API keys are entered in the UI per session (not via host env).
- **Docker Compose (same orchestrator in a container)**: set `SESSION_API_KEY_FERNET_KEY` in `.env` (see `.env.example`), then `docker compose up --build` from `computer-use-demo/` after building the VM image (see `docker-compose.yml`; Docker socket required to spawn session containers).
- **Run the desktop VM image alone (no FastAPI orchestrator)**: `docker run -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -v $(pwd)/computer_use_demo:/home/computeruse/computer_use_demo/ -v $HOME/.anthropic:/home/computeruse/.anthropic -p 5900:5900 -p 8501:8501 -p 6080:6080 -p 8080:8080 -it computer-use-demo:local` — here you **do** pass `ANTHROPIC_API_KEY` into the container so the in-VM agent (`agent_service`) can read it from the environment; there is no web form in this mode.

### Testing & Code Quality

- **Lint**: `ruff check .`
- **Format**: `ruff format .`
- **Typecheck**: `pyright`
- **Run tests**: `pytest`
- **Run single test**: `pytest tests/path_to_test.py::test_name -v`

### Code Style

- **Python**: snake_case for functions/variables, PascalCase for classes
- **Imports**: Use isort with combine-as-imports
- **Error handling**: Use custom ToolError for tool errors
- **Types**: Add type annotations for all parameters and returns
- **Classes**: Use dataclasses and abstract base classes

## Customer Support Agent

### Setup & Development

- **Install dependencies**: `npm install`
- **Run dev server**: `npm run dev` (full UI)
- **UI variants**: `npm run dev:left` (left sidebar), `npm run dev:right` (right sidebar), `npm run dev:chat` (chat only)
- **Lint**: `npm run lint`
- **Build**: `npm run build` (full UI), see package.json for variants

### Code Style

- **TypeScript**: Strict mode with proper interfaces
- **Components**: Function components with React hooks
- **Formatting**: Follow ESLint Next.js configuration
- **UI components**: Use shadcn/ui components library

## Financial Data Analyst

### Setup & Development

- **Install dependencies**: `npm install`
- **Run dev server**: `npm run dev`
- **Lint**: `npm run lint`
- **Build**: `npm run build`

### Code Style

- **TypeScript**: Strict mode with proper type definitions
- **Components**: Function components with type annotations
- **Visualization**: Use Recharts library for data visualization
- **State management**: React hooks for state