# ComfyUI-Arisu-Nodes

A package of useful nodes optimizing user experience.

> [!NOTE]
> This projected was created with a [cookiecutter](https://github.com/Comfy-Org/cookiecutter-comfy-extension) template. It helps you start writing custom nodes without worrying about the Python setup.

## Quickstart

1. Install [ComfyUI](https://docs.comfy.org/get_started).
1. Install [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager)
1. Look up this extension in ComfyUI-Manager. If you are installing manually, clone this repository under `ComfyUI/custom_nodes`.
1. Restart ComfyUI.

# Features

- A list of features

## Develop

Development uses [uv](https://docs.astral.sh/uv/). To create the project virtual environment with the dev tools, do:

```bash
cd ComfyUI-Arisu-Nodes
uv sync
```

For VS Code, copy [.vscode/settings.example.jsonc](.vscode/settings.example.jsonc) to `.vscode/settings.json` and set the ComfyUI paths in it.

## Publish to Github

Install Github Desktop or follow these [instructions](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent) for ssh.

1. Create a Github repository that matches the directory name. 
2. Push the files to Git
```
git add .
git commit -m "project scaffolding"
git push
``` 

## Writing custom nodes

Nodes use the V3 API (`comfy_entrypoint` + `io.Schema`). An example custom node is located in [nodes.py](src/arisu_nodes/nodes.py), with its ComfyUI-free logic in [core.py](src/arisu_nodes/core.py). To learn more, read the [docs](https://docs.comfy.org/custom-nodes/overview).


## Tests

Two pytest lanes live under `tests/`, both configured in `pyproject.toml`:

- `tests/unit/` needs nothing but the project venv. Run it with `uv run pytest`. This is what CI runs.
- `tests/comfyui/` imports the node pack the way ComfyUI does, so it needs ComfyUI's interpreter and source tree. Run it with `./scripts/test-comfyui.sh`. The script reads `COMFYUI_PATH` (default `~/apps/comfyui`), runs pytest on that install's Python with an ephemeral pytest layered on top, and writes nothing into the install. A bare `uv run pytest` skips this lane.

- [build-pipeline.yml](.github/workflows/build-pipeline.yml) will run pytest and linter on any open PRs
- [validate.yml](.github/workflows/validate.yml) will run [node-diff](https://github.com/Comfy-Org/node-diff) to check for breaking changes

## Publishing to Registry

If you wish to share this custom node with others in the community, you can publish it to the registry. We've already auto-populated some fields in `pyproject.toml` under `tool.comfy`, but please double-check that they are correct.

You need to make an account on https://registry.comfy.org and create an API key token.

- [ ] Go to the [registry](https://registry.comfy.org). Login and create a publisher id (everything after the `@` sign on your registry profile). 
- [ ] Add the publisher id into the pyproject.toml file.
- [ ] Create an api key on the Registry for publishing from Github. [Instructions](https://docs.comfy.org/registry/publishing#create-an-api-key-for-publishing).
- [ ] Add it to your Github Repository Secrets as `REGISTRY_ACCESS_TOKEN`.

A Github action will run on every git push. You can also run the Github action manually. Full instructions [here](https://docs.comfy.org/registry/publishing). Join our [discord](https://discord.com/invite/comfyorg) if you have any questions!

