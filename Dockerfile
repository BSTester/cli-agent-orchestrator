FROM pyd4vinci/scrapling:latest

ARG CAO_REPO_REF=main

ENV PYTHONUNBUFFERED=1 \
    CAO_REPO_REF=${CAO_REPO_REF} \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=9889 \
    CONTROL_PANEL_HOST=0.0.0.0 \
    CONTROL_PANEL_PORT=8000 \
    CAO_SERVER_URL=http://127.0.0.1:9889 \
    CAO_CONSOLE_PASSWORD=admin

WORKDIR /opt/cao

RUN python - <<'PY'
import os
from pathlib import Path
from urllib.request import urlopen

repo_ref = os.environ["CAO_REPO_REF"]
base_url = f"https://raw.githubusercontent.com/BSTester/cli-agent-orchestrator/{repo_ref}/scripts"
script_dir = Path("/opt/cao/scripts")
script_dir.mkdir(parents=True, exist_ok=True)

for name in ("install_services.sh", "start_services.sh", "stop_services.sh", "install_and_start_services.sh"):
    content = urlopen(f"{base_url}/{name}").read().decode("utf-8")
    path = script_dir / name
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
PY

EXPOSE 8000 9889

ENTRYPOINT []

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 CMD python -c "from urllib.request import urlopen; [urlopen(url, timeout=5).close() for url in ('http://127.0.0.1:9889/health', 'http://127.0.0.1:8000/health')]"

CMD ["/bin/bash", "-lc", "/opt/cao/scripts/install_and_start_services.sh && exec tail -F /opt/cao/.runtime/logs/cao-server.log /opt/cao/.runtime/logs/cao-control-panel.log"]
