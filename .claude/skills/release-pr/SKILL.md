---
name: release-pr
description: Open the `main <- release/X.Y.Z` release PR for ComfyUI-Arisu-Nodes — validates the release commit on the current branch's origin ref, writes a body from the CHANGELOG section and the diff, and opens it with gh. Use when the user says "release PR", "open the release", or "PR for the bump".
---

You are opening the release PR for ComfyUI-Arisu-Nodes: `main <- <current branch>`. Work only against `origin/*` refs — local branches may be stale. Never commit, push, checkout, or tag anything in this skill.

## Steps

### 1. Sync remote state

```bash
git fetch origin --prune
BRANCH=$(git rev-parse --abbrev-ref HEAD)
```

`BRANCH` is `main` or `HEAD` (detached) → **stop**: release PRs come from a release branch (`git switch -c release/X.Y.Z`, then `make bump-*` and `make release-commit`).

### 2. Validate the release commit

```bash
git log -1 --format='%s' origin/$BRANCH
```

The subject must match exactly (`RELEASE_SUBJECT_RE` in `scripts/release_common.py`):

```
^chore: bump version to \d+\.\d+\.\d+$
```

If `origin/$BRANCH` does not exist or the subject does not match, **stop** and tell the user the tip of `origin/$BRANCH` is not a release commit; they should run `make bump-patch|minor|major` then `make release-commit`.

### 3. Validate there is something to release

```bash
git rev-list --count origin/main..origin/$BRANCH
gh pr list --base main --head $BRANCH --state open --json number,url
```

- Count `0` → **stop**: `main` already contains this branch.
- An open PR already exists → **stop** and print its URL instead of opening a second one.

### 4. Gather the release contents

```bash
git show origin/main:pyproject.toml | grep -E '^version = '
git show origin/$BRANCH:pyproject.toml | grep -E '^version = '
git show origin/$BRANCH:CHANGELOG.md
git log origin/main..origin/$BRANCH --no-merges --format='%h %s'
git diff --stat origin/main origin/$BRANCH
git diff origin/main origin/$BRANCH -- pyproject.toml
git diff --name-status origin/main origin/$BRANCH -- __init__.py src/arisu_nodes/nodes.py web/docs
```

The `## [X.Y.Z] - YYYY-MM-DD` section of the branch's `CHANGELOG.md`, where `X.Y.Z` is the version from the release commit subject, is the source of truth for the Added / Changed / Fixed bullets. Commit subjects fill gaps only.

### 5. Write the body

Title = the release commit subject from step 2, verbatim.

Write the body to a scratch file (`--body-file`), following this template. Skip empty sections. Summarize in your own words for Highlights; copy the changelog bullets as they are.

```markdown
## Version

| | main | this branch |
|---|---|---|
| `arisu_nodes` | 0.1.0 | 0.2.0 |

## Highlights

2–4 sentences: what this release delivers for ComfyUI users and why it matters.

## Added
- …

## Changed
- …

## Fixed
- …

## Node changes
- New or changed node ids (from `__init__.py` / `src/arisu_nodes/nodes.py`) and their `web/docs/<node_id>/en.md` pages, or "none".
- Runtime dependency changes in `pyproject.toml` `dependencies` (each needs the human-only `uv pip install` into the ComfyUI venv per CLAUDE.md), or "none".

## Release checklist
- [ ] Merge this PR (CI must be green).
- [ ] `git switch main && git pull && make tag` — pushes `vX.Y.Z`, which triggers `publish_node.yml`.
- [ ] `REGISTRY_ACCESS_TOKEN` secret present; the publish run is green.
- [ ] Manual E2E in the live ComfyUI (human-only, see CLAUDE.md).

## Commits

<details><summary>N commits</summary>

- `abc1234` feat(nodes): …
- …

</details>
```

### 6. Open the PR

```bash
gh pr create --base main --head $BRANCH --title "<release commit subject>" --body-file <scratch-file>
```

Report the PR URL to the user, plus the version table and the release checklist inline so they can act without opening the PR.
