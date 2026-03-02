# CAO Frontend — Next.js Console

A Next.js web console for the **CLI Agent Orchestrator** (CAO) API.

## Web Console Features

- 登录认证：控制台密码登录、会话校验与退出登录。
- Dashboard（集团总览）：展示团队规模、成员规模、状态与任务概览。
- Agents（团队管理）：按团队查看在线状态与任务，并提供实时终端控制台（Web 内直接执行命令）。
- Organization（组织管理）：
   - 新建岗位类型（Profile 创建并安装）
   - 新建负责人、创建员工并加入团队
   - 团队成员退出、团队解散
   - 团队工作目录配置（仅 home 一级目录）：
      - 选择已有目录，或输入新目录名自动创建
      - 员工加入团队时自动继承团队工作目录并在该目录启动终端 Agent
- Tasks（任务管理）：
   - 按团队查看即时任务与定时任务
   - 新建/编辑定时任务，支持加载已有 flow 文件
   - 手动触发、启停、删除定时任务
   - 定时任务绑定到指定团队

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

2. Build frontend（构建完成后会自动删除旧静态资源并同步到 `cao-control-panel` 目录）：

   ```bash
   cd frontend
   npm install
   npm run build
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
| `npm run build` | Build static export to `out/` and auto-sync to `src/cli_agent_orchestrator/control_panel/static/` |
| `npm run start` | Start Next.js server mode (optional) |
| `npm run lint`  | Run ESLint                   |


## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
