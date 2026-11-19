---
name: release-pr
description: Prepare a ComfyUI-Arisu-Nodes release PR into main from dev or a release branch. Open or resume the PR, verify and repair hosted CI, prepare the pack version and release notes, and verify the final pushed release. Use for release preparation or a PR for an existing bump.
---

# Prepare the pack's release PR

Run from the development checkout with Git and authenticated `gh`. Codex invokes
`$release-pr` and Claude Code invokes `/release-pr`. Read the
[repository rules](../../../AGENTS.md), [release targets](../../../Makefile) and
[PR workflow](../../../.github/workflows/build-pipeline.yml). A request to carry out
`release-pr` authorizes the workflow's scoped staging, commits and normal pushes,
including CI repairs. Preserve unrelated changes, including anything already staged.
Merge, tag, Registry publication and live-install E2E are subsequent maintainer actions.

## Open or resume the PR

1. Select the requested source. Otherwise use the current release branch for a prepared
   release, or `dev` for release preparation. The base is `main`. Verify that `gh`
   targets the repository at `origin` and inspect the worktree and index before writes.
2. Fetch and resolve the remote tips. Use their SHAs when inspecting the range.

   ```bash
   git fetch origin --prune
   base_sha=$(git rev-parse --verify 'refs/remotes/origin/main^{commit}')
   head_sha=$(git rev-parse --verify "refs/remotes/origin/${release_branch}^{commit}")
   git log "${base_sha}..${head_sha}" --no-merges --format='%h %s'
   git diff --stat "${base_sha}...${head_sha}"
   gh pr list --base main --head "$release_branch" --state open --json number,url,headRefOid
   ```

   A PR needs a pushed source distinct from `main` and a nonempty release range. Check the
   PR's head repository as well as its branch. Inspect the full diff, including node IDs,
   workflows, help pages, dependencies, lockfile and changelog. Read version metadata at
   both SHAs. Before a repair or bump, work from the selected source at its remote tip in
   a clean checkout. Isolate unrelated work when necessary. Inspect any local release
   commit left by a failed push before creating another commit.
3. Reuse the matching open PR and continue. For a new PR, use a provisional English
   title such as `chore(release): prepare Arisu Nodes release`, summarize the range,
   record both SHAs and identify pending checks. If already bumped, use the release
   subject and dated changelog section immediately. Follow the repository's PR template
   when present. Write the body with actual newlines in a disposable file at the
   session's scratch location. Recheck for an open PR before creation and after any
   ambiguous failure.

   ```bash
   gh pr create --base main --head "$release_branch" --title "$release_title" --body-file "$body_file"
   ```

## Verify hosted CI and repair failures

For a new bump, obtain green CI on the unbumped PR first. For an existing pushed bump,
verify the release metadata below and proceed directly to the final CI gate. Record which
snapshots actually ran. Use the same gate after every push, including a metadata-only bump.

```bash
gh pr view "$pr_number" --json url,state,headRefName,headRefOid,headRepositoryOwner,baseRefName,baseRefOid
gh pr checks "$pr_number" --json name,state,bucket,workflow,event,link
gh run view "$run_id" --json event,status,conclusion,attempt,jobs,url
```

Match the open PR, source/base SHAs and latest applicable PR run. A pull request run can
test a synthetic merge commit. Verify its parents against the reviewed tips when needed.
Require both **CI build** matrix jobs (Ubuntu, Python 3.10 and 3.13) to pass locked install,
tidy with a clean diff, lint, unit/web tests and build. The scheduled/manual ComfyUI lane
and tag-triggered publish workflow have separate triggers. Local checks or a previous
green head cannot satisfy the hosted gate.

- Monitor queued/running jobs in short waits. Inspect triggers, runner availability and
  permissions when checks are missing, skipped or cancelled. If the base moved, obtain a
  run that tests the new pair before claiming success.
- Read failed step logs (`gh run view "$run_id" --log-failed`). Identify independent
  causes and reproduce the smallest failing command with the runner's versions, locked
  dependencies and relevant inputs. Trace the expected behavior to the node contract,
  repository rules and existing regression. Fix product defects in shipped code. Correct
  a fixture or workflow only when independent evidence identifies that layer as faulty.
  Preserve valid assertions, timeouts, coverage and failure exits. Rerun a demonstrated
  transient runner failure and verify the result.
- Verify the fix against the original failure, then run `make tidy`, `make lint test`
  and `make build`, plus the owning lane where relevant. Respect the live-install
  boundary. Review the diff and `git diff --check`, stage only reviewed paths, commit
  with the project's English commit style and push the selected branch without force.
  On an uncertain push, compare local and remote SHAs before retrying. Use a normal fix
  commit for CI repairs.
- Confirm the new PR head and repeat the gate. Continue while a viable diagnosis or
  repair remains. For a concrete external blocker, report the PR/run link, failed step,
  evidence and outstanding action. Once green, fetch both tips again and use the verified
  range, including repairs, for the release notes and version decision.

## Prepare or verify the release metadata

Use the single `arisu_nodes` version in `pyproject.toml`. Compare the final behavior with
`origin/main` and the previous published release if they differ. Honor a requested version.
Otherwise recommend a patch for compatible fixes, minor for added capabilities, or major
for incompatible changes to a shipped contract. Explain the choice using the diff.

- For a fresh bump, inspect `[Unreleased]` and its coverage of shipped user-visible
  changes. The [bump helper](../../../scripts/release_bump.py) requires an entry and
  clean release files. Resolve any genuine missing notes before running the selected
  `make bump-patch`, `make bump-minor` or `make bump-major`. It updates
  `pyproject.toml`, rolls the heading to `## [X.Y.Z] - YYYY-MM-DD`, opens an empty
  `[Unreleased]` and refreshes `uv.lock`. If release notes need their own pre-bump
  commit, verify hosted CI on that head too.
- If release files are already prepared locally or pushed, inspect the complete diff
  and reuse the matching version. Check that it advances the base, agrees with the lock
  and dated notes, and that the release commit has the exact subject
  `release arisu_nodes: X.Y.Z`. Locate that commit in the PR range if a later CI repair
  is at the tip. Resolve inconsistent or partial metadata before proceeding.
- Review the three-file diff including lockfile churn, run `git diff --check` and the
  repository's tidy, lint/test and build sequence on the prepared tree. Attribute local
  results to that tree and hosted results to their actual SHAs.
- Present the version and rationale, release-file diff, proposed title/body, source/base
  SHAs, validation and push destination. If the version choice still needs the user's
  decision, obtain confirmation of the concrete bump here. Reuse an already approved
  version and scope. Workflow Git actions are covered by the original PR request.
- Recheck the branch, fetched tips and reviewed files before running
  `make release-commit YES=1`. The [commit helper](../../../scripts/release_commit.py)
  accepts only the three release files and commits and pushes the selected branch.
  After a push failure, verify the existing local commit and retry just the outstanding
  normal push if the remote still permits it. Skip the helper for an already pushed bump.

## Update the same PR and finish

Fetch and verify the release subject, files and source SHA on origin. Use the exact
release subject as the final PR title. Write the final English body from the remote diff:

- Version table for `arisu_nodes` on `main` and the release branch, followed by the rationale.
- Highlights for ComfyUI users and the populated sections from the dated changelog.
- Affected node IDs and help pages, workflow compatibility and runtime dependency changes.
  Identify any human-only live environment steps from AGENTS.md.
- Actual local checks, pre-bump CI when observed, final CI links, tested SHAs and any
  repair or outstanding verification. Include the non-merge commit list in collapsed details.
- Maintainer checklist for a green merge, manual live ComfyUI E2E, and `make tag` on
  up-to-date `main`. Pushing `vX.Y.Z` triggers `publish_node.yml`, which needs
  `REGISTRY_ACCESS_TOKEN`. Mark publication complete only when independently observed.

Update with `gh pr edit "$pr_number" --title "$release_title" --body-file "$body_file"`
and remove the disposable file after use. Verify the final hosted gate on the current
head/base. Carry the selected version through any repairs, refresh release notes if
behavior changes, and update the same PR with the successful run links. Report the URL,
version change, release commit and final head SHAs, checks and remaining maintainer steps.
