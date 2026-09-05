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

Development uses [uv](https://docs.astral.sh/uv/) and GNU make. `make install` installs uv if it is missing and creates the project virtual environment with the dev tools; `make help` lists every target:

```bash
cd ComfyUI-Arisu-Nodes
make install   # .venv with pytest, ruff, and the formatters
make tidy      # format everything in place
make lint      # check only
make test      # unit lane
make build     # wheel + sdist into dist/
make bump-patch        # or bump-minor / bump-major: version, CHANGELOG, uv.lock
make release-commit    # commit + push the bump on a release branch
make tag               # on main: tag vX.Y.Z and push (publishes to the registry)
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

- `tests/unit/` needs nothing but the project venv. Run it with `make test`. This is what CI runs.
- `tests/comfyui/` imports the node pack the way ComfyUI does, so it needs ComfyUI's interpreter and source tree. Run it with `make test-comfyui ARGS="-v"`, which wraps `scripts/test-comfyui.sh`. The script reads `COMFYUI_PATH` (default `~/apps/comfyui`), runs pytest on that install's Python with an ephemeral pytest layered on top, and writes nothing into the install. A bare `uv run pytest` skips this lane.

- [build-pipeline.yml](.github/workflows/build-pipeline.yml) runs `make install LOCKED=1`, `make tidy` (failing if it changed anything), `make lint`, `make test`, and `make build` on Python 3.10 and 3.13 for every open PR.

## Publishing to Registry

If you wish to share this custom node with others in the community, you can publish it to the registry. We've already auto-populated some fields in `pyproject.toml` under `tool.comfy`, but please double-check that they are correct.

You need to make an account on https://registry.comfy.org and create an API key token.

- [ ] Go to the [registry](https://registry.comfy.org). Login and create a publisher id (everything after the `@` sign on your registry profile). 
- [ ] Add the publisher id into the pyproject.toml file.
- [ ] Create an api key on the Registry for publishing from Github. [Instructions](https://docs.comfy.org/registry/publishing#create-an-api-key-for-publishing).
- [ ] Add it to your Github Repository Secrets as `REGISTRY_ACCESS_TOKEN`.

The publish action runs when a `vX.Y.Z` tag is pushed. Releases go through a short branch-and-PR flow driven by the release scripts in `scripts/release_*.py`:

```bash
git switch -c release/0.2.0      # from an up-to-date main
make bump-minor                  # or bump-patch / bump-major: pyproject version, CHANGELOG roll, uv lock
make release-commit              # guarded commit "chore: bump version to 0.2.0" + push
# /release-pr in Claude Code opens the main <- release/0.2.0 PR; merge it
git switch main && git pull
make tag                         # CAPTCHA-confirmed annotated tag v0.2.0, pushed -> publish_node.yml
```

`make bump-*` refuses if `[Unreleased]` in `CHANGELOG.md` is empty, `make release-commit` refuses on `main` or when anything but `pyproject.toml`, `CHANGELOG.md`, and `uv.lock` changed, and `make tag` refuses unless you are on the latest `main` with an untagged HEAD. You can also run the Github action manually. Full instructions [here](https://docs.comfy.org/registry/publishing). Join our [discord](https://discord.com/invite/comfyorg) if you have any questions!

