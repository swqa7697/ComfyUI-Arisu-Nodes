# check=skip=InvalidDefaultArgInFrom

# Required: --build-arg AGENT=codex or --build-arg AGENT=grok.
ARG AGENT

FROM python:3.13-slim-trixie AS installer
ARG AGENT
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && bash --version
COPY agents/${AGENT}/install.sh /opt/install_agent.sh
RUN sh /opt/install_agent.sh

FROM python:3.13-slim-trixie AS runtime-common
LABEL org.arisu.workbench="1" org.arisu.workbench.policy="6"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/agent
COPY --from=installer /opt/agent/ /opt/agent/
ENV PATH="/opt/agent/bin:/usr/local/bin:/usr/bin:/bin"
COPY *.py instructions.txt /opt/workbench/
COPY agents/__init__.py /opt/workbench/agents/__init__.py
RUN mkdir -p /home/agent /auth /work && chown 1000:1000 /home/agent /auth
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python", "/opt/workbench/runner.py"]

FROM runtime-common AS runtime-codex
ENV CODEX_HOME=/home/agent/.codex
ENV PATH="/opt/agent/bin:/opt/agent/codex-home/packages/standalone/current/codex-path:/usr/local/bin:/usr/bin:/bin"
COPY agents/codex/*.py agents/codex/*.toml /opt/workbench/agents/codex/
COPY agents/codex/requirements.toml /etc/codex/requirements.toml

FROM runtime-common AS runtime-grok
ENV GROK_HOME=/home/agent/.grok
COPY agents/grok/*.py agents/grok/*.toml /opt/workbench/agents/grok/
COPY agents/grok/config.toml /etc/grok/requirements.toml

FROM runtime-${AGENT} AS runtime
