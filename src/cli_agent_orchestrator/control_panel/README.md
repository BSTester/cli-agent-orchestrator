# CAO Control Panel

FastAPI interface layer that acts as a middleware between the frontend control panel and the CAO server.

## Architecture

```
Frontend (static files) → Control Panel (FastAPI) → CAO Server (FastAPI)
         served by               port 8000                port 9889
      control-panel
```

The control panel serves as a single service that:
- Hosts the built frontend static files
- Serves local control-panel APIs (`/auth/*`, `/console/*`)
- Proxies backend APIs to CAO server (`/api/*`)

This three-tier architecture provides:
- **Decoupling**: Frontend and backend can evolve independently
- **Security**: Additional layer for authentication/authorization (future)
- **Monitoring**: Central point for logging and metrics (future)
- **Flexibility**: Easy to add business logic without touching core CAO server

## Running the Control Panel

Start the control panel server:

```bash
cao-control-panel
```

Or with development tools:

```bash
uv run cao-control-panel
```

The server will start on `http://localhost:8000` by default.

## Configuration

The control panel reads configuration from environment variables:

- `CONTROL_PANEL_HOST`: Host to bind to (default: `localhost`)
- `CONTROL_PANEL_PORT`: Port to listen on (default: `8000`)
- `CAO_SERVER_URL`: URL of the CAO server to proxy to (default: `http://localhost:9889`)

## API Endpoints

Control panel local endpoints:

- `GET /health` - Health check (includes CAO server status)
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` - Auth endpoints
- `GET|POST ... /console/*` - Control panel management endpoints

Proxy endpoint:

- `GET|POST|PUT|PATCH|DELETE /api/{path:path}` - Proxy to CAO server

Static frontend:

- `GET /` and other frontend routes (`/dashboard`, `/organization`, etc.) are served from `control_panel/static`.

## Build frontend static files

From repo root:

```bash
cd frontend
npm install
npm run build
cd ..
rm -rf src/cli_agent_orchestrator/control_panel/static
mkdir -p src/cli_agent_orchestrator/control_panel/static
cp -a frontend/out/. src/cli_agent_orchestrator/control_panel/static/
```

Then run:

```bash
uv run cao-control-panel
```

Open `http://localhost:8000` directly (no separate frontend service needed).

## Testing

Run the control panel tests:

```bash
pytest test/control_panel/ -v
```

## Development

The control panel is a lightweight FastAPI application that uses the `requests` library to communicate with the CAO server. All endpoints (except `/health`) are automatically proxied through the catch-all route handler.
