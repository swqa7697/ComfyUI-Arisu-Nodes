FROM python:3.13-slim-trixie AS installer
ARG AGENT
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl bash \
    && rm -rf /var/lib/apt/lists/*
COPY install_agent.sh /opt/install_agent.sh
RUN sh /opt/install_agent.sh "$AGENT"

FROM python:3.13-slim-trixie
ARG AGENT
LABEL org.arisu.workbench="1"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/agent
ENV CODEX_HOME=/home/agent/.codex GROK_HOME=/home/agent/.grok
COPY --from=installer /opt/agent/ /opt/agent/
ENV PATH="/opt/agent/bin:/opt/agent/codex-home/packages/standalone/current/codex-path:/usr/local/bin:/usr/bin:/bin"
COPY runner.py mcp_server.py /opt/workbench/
RUN mkdir -p /home/agent/.codex /home/agent/.grok /work && chown -R 1000:1000 /home/agent /work
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python", "/opt/workbench/runner.py"]
