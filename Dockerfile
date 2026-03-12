FROM pyd4vinci/scrapling:latest

ARG CAO_UID=1000
ARG CAO_GID=1000

ENV PYTHONUNBUFFERED=1 \
    HOME=/home/cao \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=9889 \
    CONTROL_PANEL_HOST=0.0.0.0 \
    CONTROL_PANEL_PORT=8000 \
    CAO_SERVER_URL=http://127.0.0.1:9889 \
    CAO_TOOL_SPEC=/opt/cao \
    CAO_RUNTIME_DIR=/home/cao/.local/state/cli-agent-orchestrator/runtime \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_TRUSTED_HOST=pypi.org \
    NPM_CONFIG_PREFIX=/home/cao/.local \
    NPM_CONFIG_REGISTRY=https://registry.npmjs.org/ \
    PATH=/home/cao/.local/bin:/home/cao/.cargo/bin:/usr/local/bin:${PATH}

RUN set -e \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        tmux \
        unzip \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${CAO_GID}" cao \
    && useradd --uid "${CAO_UID}" --gid "${CAO_GID}" --create-home --shell /bin/bash cao \
    && chown -R cao:cao /opt/cao /home/cao

WORKDIR /opt/cao

COPY pyproject.toml README.md uv.lock /opt/cao/
COPY src /opt/cao/src
COPY extensions/openclaw-cao-tools /opt/cao/extensions/openclaw-cao-tools

COPY --chmod=755 scripts/install_services.sh /opt/cao/scripts/install_services.sh
COPY --chmod=755 scripts/start_services.sh /opt/cao/scripts/start_services.sh
COPY --chmod=755 scripts/stop_services.sh /opt/cao/scripts/stop_services.sh
COPY --chmod=755 scripts/install_and_start_services.sh /opt/cao/scripts/install_and_start_services.sh
COPY --chmod=755 scripts/docker_entrypoint.sh /opt/cao/scripts/docker_entrypoint.sh
COPY scripts/docker_healthcheck.py /opt/cao/scripts/docker_healthcheck.py

RUN python -m pip install --no-cache-dir /opt/cao \
    && chown -R cao:cao /opt/cao

USER cao

RUN CAO_SKIP_TOOL_INSTALL=1 /bin/bash /opt/cao/scripts/install_services.sh \
    && npm install -g @anthropic-ai/claude-code @openai/codex

EXPOSE 8000 9889

ENTRYPOINT []

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 CMD python /opt/cao/scripts/docker_healthcheck.py

CMD ["/bin/bash", "/opt/cao/scripts/docker_entrypoint.sh"]
