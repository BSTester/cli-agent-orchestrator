# CAO Frontend — Next.js Console

A Next.js web console for the **CLI Agent Orchestrator** (CAO) API.

## Architecture

```
Browser (React UI)
   │
   │  HTTP /console/*, /auth/*, /api/*
   ▼
cao-control-panel (port 8000)    ← FastAPI interface layer + static frontend host
    │  Proxy layer
    │  HTTP *
    ▼
cao-server (port 9889)           ← FastAPI backend
```

The frontend is built as static files and hosted directly by `cao-control-panel`.
`cao-control-panel` handles `/console/*` and `/auth/*` locally, and proxies
`/api/*` to `cao-server`.

## Getting Started

1. Start the `cao-server` backend (from the repo root):

   ```bash
   uv run cao-server
   ```

2. Build and deploy static frontend files into `cao-control-panel` package dir:

   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   rm -rf src/cli_agent_orchestrator/control_panel/static
   mkdir -p src/cli_agent_orchestrator/control_panel/static
   cp -a frontend/out/. src/cli_agent_orchestrator/control_panel/static/
   ```

3. Start the `cao-control-panel` interface layer (from the repo root):

   ```bash
   uv run cao-control-panel
   ```

4. Open [http://localhost:8000](http://localhost:8000) in your browser.

## Frontend-only development

Run the frontend dev server separately when you need hot reload:

   ```bash
   cd frontend
   npm run dev
   ```

Then open [http://localhost:3000](http://localhost:3000). It will call
`http://localhost:8000` by default in local development.

## Configuration

| Environment variable     | Default                 | Description                       |
| ------------------------ | ----------------------- | --------------------------------- |
| `NEXT_PUBLIC_CAO_CONTROL_PANEL_URL` | auto-detect (`http://localhost:8000` in local dev) | Control panel base URL used by browser API calls |

Set `NEXT_PUBLIC_CAO_CONTROL_PANEL_URL` to override the default control panel address:

```bash
NEXT_PUBLIC_CAO_CONTROL_PANEL_URL=http://my-control-panel:8000 npm run dev
```

## Scripts

| Command         | Description                  |
| --------------- | ---------------------------- |
| `npm run dev`   | Start development server     |
| `npm run build` | Build static export to `out/` |
| `npm run start` | Start Next.js server mode (optional) |
| `npm run lint`  | Run ESLint                   |


## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
