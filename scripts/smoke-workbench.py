"""Build isolated disposable agents and verify the non-authenticated integration."""

from __future__ import annotations

import base64
import json
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.arisu_nodes.minimax_h3.agent_docker import ASSETS, DockerAgents

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="

PROBE = """
import base64, json, os, pathlib, subprocess, sys
sys.path.insert(0, '/opt/workbench')
import runner
agent = sys.argv[1]
runner.configuration(agent)
assert os.getuid() == 1000
assert not pathlib.Path('/var/run/docker.sock').exists()
for path in ('/inputs/pixel.png', '/skill/SKILL.md', '/work/result.md', '/opt/workbench/policy/codex.toml', '/etc/workbench-smoke'):
    try:
        with open(path, 'ab') as output: output.write(b'forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('writable protected mount')
requests = [
    {'id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'smoke','version':'1'}}},
    {'method':'notifications/initialized'},
    {'id':2,'method':'tools/list'},
    {'id':3,'method':'tools/call','params':{'name':'get_context','arguments':{}}},
    {'id':4,'method':'tools/call','params':{'name':'read_image','arguments':{'asset_id':'pixel'}}},
    {'id':5,'method':'tools/call','params':{'name':'read_image','arguments':{'asset_id':'../secret'}}},
    {'id':6,'method':'tools/call','params':{'name':'read_skill','arguments':{'path':'SKILL.md'}}},
    {'id':7,'method':'tools/call','params':{'name':'read_skill','arguments':{'path':'/auth/auth.json'}}},
]
wire = ''.join(json.dumps(dict(jsonrpc='2.0', **r)) + '\n' for r in requests)
completed = subprocess.run(['python','/opt/workbench/mcp_server.py'],input=wire,text=True,capture_output=True,timeout=10,check=True)
messages = [json.loads(line) for line in completed.stdout.splitlines()]
assert len(messages) == 7
assert messages[0]['result']['capabilities']['tools'] == {}
assert {t['name'] for t in messages[1]['result']['tools']} == {'get_context','read_image','read_skill'}
assert json.loads(messages[2]['result']['content'][0]['text'])['requirements'] == 'temporary fixture'
assert base64.b64decode(messages[3]['result']['content'][0]['data']) == pathlib.Path('/inputs/pixel.png').read_bytes()
assert messages[4]['result']['isError']
assert 'MiniMax' in messages[5]['result']['content'][0]['text']
assert messages[6]['result']['isError']
for tool in ('Bash','apply_patch','web_search','WebFetch','spawn_agent','unknown','mcp__workbench__read_skill'):
    wire = json.dumps({'hook_event_name':'PreToolUse','tool_name':tool})
    checked = subprocess.run(['python','/opt/workbench/policy.py'],input=wire,text=True,capture_output=True,timeout=5,check=True)
    verdict = json.loads(checked.stdout)['hookSpecificOutput']['permissionDecision']
    assert verdict == ('allow' if tool == 'mcp__workbench__read_skill' else 'deny')
capability = runner.restricted(agent)
if not capability['restricted']:
    try:
        runner.generate(agent, {'model':'test-no-account'})
    except ValueError:
        pass
    else:
        raise AssertionError('generation started without an enforced sandbox')
print(json.dumps({'python':sys.version.split()[0], 'mcp':'context/image/skill/refusal passed', 'tool_gate':'readers only', 'mounts':'read-only', **capability}))

""".replace(" + '\n'", " + '\\n'")


def main():
    """Keep all fixtures, accounts and owned Docker resources separate from the install."""
    logging.basicConfig(level=logging.ERROR)
    with tempfile.TemporaryDirectory(prefix="arisu-workbench-smoke-") as temporary:
        directory = Path(temporary)
        inputs = directory / "inputs"
        inputs.mkdir()
        original = base64.b64decode(PNG)
        (inputs / "pixel.png").write_bytes(original)
        (inputs / "context.json").write_text(
            json.dumps({"requirements": "temporary fixture", "assets": [{"id": "pixel", "file": "pixel.png", "mime": "image/png"}]})
        )
        agents = DockerAgents(directory / "user")
        original_log = agents.log

        def progress(text: Any):
            original_log(text)
            print("\n".join(str(text).splitlines()[-2:]), flush=True)

        agents.log = progress
        unavailable = []
        try:
            for agent in ("codex", "grok"):
                print("BUILD " + agent, flush=True)
                image = agents.image(agent)
                try:
                    agents.manage(agent, "build")
                except ValueError:
                    # An unsupported native sandbox must refuse promotion. Still
                    # exercise the candidate's fixed readers and container mounts.
                    image = agents.namespace + "-" + agent + ":candidate"
                    if not agents.owned("image", image):
                        raise
                    details = agents.invoke(agent, "inspect", image=image)
                    if details.get("restricted"):
                        raise
                    unavailable.append(agent + ": " + details.get("restriction_error", "policy verification failed"))
                    print(json.dumps(details), flush=True)
                skill = ASSETS / "skills" / "with-ref"
                name = agents.namespace + "-smoke-" + agent
                result = agents.command(
                    [
                        *agents.run_args(agent, name),
                        "--mount",
                        "type=bind,src=" + str(inputs) + ",dst=/inputs,readonly",
                        "--mount",
                        "type=bind,src=" + str(skill) + ",dst=/skill,readonly",
                        "--entrypoint",
                        "python",
                        image,
                        "-c",
                        PROBE,
                        agent,
                    ],
                    timeout=90,
                )
                print(agent + " " + result, flush=True)
                assert (inputs / "pixel.png").read_bytes() == original
                agents.stream(
                    [*agents.run_args(agent, name), "--entrypoint", agent, image, "--version"],
                    time.monotonic() + 30,
                    threading.Event(),
                    name,
                )
                page = agents.read_logs()
                logs = list(page["lines"])
                while page["more"]:
                    page = agents.read_logs(page["session"], page["cursor"])
                    logs.extend(page["lines"])
                assert page["agent"] == agent and page["action"] == "build" and "build" in "\n".join(logs)
            print("PASS: native CLIs, MCP readers, tool gate, read-only mounts, fail-closed generation and session logs.", flush=True)
            print("Account checks not run: device login and authenticated generation require configured provider accounts.", flush=True)
            if unavailable:
                raise SystemExit("Native sandbox checks could not pass on this host: " + "; ".join(unavailable))
        finally:
            for agent in ("codex", "grok"):
                agents.manage(agent, "remove")
            agents.close()
            assert not agents.command(["ps", "-aq", "--filter", "label=org.arisu.workbench.instance=" + agents.namespace]).strip()
            print("CLEANUP: temporary provider images, containers and authentication volumes removed.", flush=True)


if __name__ == "__main__":
    main()
