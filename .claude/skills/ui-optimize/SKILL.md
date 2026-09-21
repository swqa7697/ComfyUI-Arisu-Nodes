---
name: ui-optimize
description: Improve ComfyUI-Arisu-Nodes frontend appearance and usability through a repeated real-browser render, screenshot inspection, edit, and verification loop. Use for node UI polish, layout and interaction improvements, or screenshot-driven UX refinement in this repository.
---

# Optimize the ComfyUI frontend

Work from this development checkout. Claude Code invokes `/ui-optimize`; Codex invokes
`$ui-optimize` through the shared `.agents/skills/ui-optimize` symlink.

Read the repository's `AGENTS.md` / `CLAUDE.md` and the README's **Local browser inspection**
section. Use the existing browser lane rather than inventing a preview page or duplicating
extension markup. The goal is a visible, usable improvement in the real ComfyUI frontend.

## Establish the target and baseline

- Inspect the requested panel's shipped scripts, owning web regression, and browser journey.
  Start with the user's reported problem; if no panel is specified, inspect Resource Studio
  and Prompt Workbench and prioritize the clearest observed usability problems.
- Preserve the existing ComfyUI design language and default appearance. Do not add a theme
  matrix, adopt a new design system, or redesign unrelated panels without that scope.
- Run `make browser-install` once at the beginning of a new optimization task to refresh the
  latest stable frontend. Keep that installed version throughout the comparison loop; do not
  pin or downgrade it to make tests pass. Record the version from the generated diagnostics.
- Capture a fresh baseline using the relevant journey:

  ```bash
  make test-browser ARGS="-k resource_studio"
  make test-browser ARGS="-k prompt_workbench"
  ```

  Use `make test-browser` for both. The journeys cover 1440×900 and 1024×768 with Nodes 2.0
  disabled. `make inspect-browser` is optional for interactive exploration on a desktop;
  headless Chromium and saved PNGs are sufficient for the automated loop.
- Inspect the actual PNGs in `.misc/browser/results/{studio,workbench}-{1440,1024}/` with an
  available image-viewing tool. Read `diagnostics.json` and use `trace.zip` when an interaction
  or layout failure needs explanation. Do not claim visual inspection from DOM text alone.
- Before rerunning, copy the relevant baseline screenshots and diagnostics to a fresh
  `.misc/browser/reviews/<task>/before/` directory: scenario outputs are replaced on each run.
  Keep subsequent comparison copies under that same task directory, logs under
  `.misc/browser/logs/`, and temporary scripts under `.misc/browser/scratch/`. Create no files
  directly in `.misc/` and no tracked screenshot baselines or review reports. Use `/tmp` for
  unrelated disposable scratchpads. `.tmp/` is developer-managed; agents must not write there.

## Repeat: inspect → change → render → compare

1. Identify a small, concrete improvement from the baseline. State the problem and the
   observable result that would resolve it: for example, labels remain readable after a node
   resize, primary actions remain reachable, or dialog controls fit without horizontal clipping.
2. Check the states relevant to that problem: empty/populated content, long labels and text,
   loading/error/unavailable states, crop/clip or review/settings dialogs, and canvas zoom and
   node resizing. Judge hierarchy, spacing, alignment, text contrast, control density, focus,
   keyboard access, scrolling, and whether the next action is clear. Avoid decorative changes
   without a usability benefit.
3. Make a focused change in the shipped frontend. Preserve workflow values, undo behavior,
   selection provenance, path authorization, and async cancellation. Keep test-only helpers out
   of `web/`; do not alter server behavior merely to simplify a visual change.
4. Run the affected browser journey and relevant existing web regression. Reuse or extend the
   owning scenario according to the repository's test-growth ladder. For an uncovered UI,
   extend the real-frontend fixture/journey enough to exercise it before claiming improvement.
   Keep fixtures faithful to actual route and schema contracts, with synthetic data only.
5. Open the new screenshots at both viewport sizes and compare the same state with the saved
   baseline. Verify interactions through real browser mouse/keyboard input, not only programmatic
   state changes. Check that the intended improvement occurred without displaced controls,
   clipped content, broken media, lost focus, or new console errors. Preserve useful comparison
   screenshots under `.misc/browser/reviews/<task>/` before the next run.
6. Keep the change only if the evidence supports it. Otherwise revise or undo that batch while
   preserving unrelated user work. Continue until the requested problems are resolved and the
   affected states remain usable; stop speculative polishing once those criteria are met.

A green test does not prove good appearance. A screenshot does not prove an interaction works.
Use both. Do not weaken layout assertions, hide errors, shrink the viewport coverage, or remove
controls merely to obtain a green run. Distinguish a frontend compatibility failure or incorrect
fixture from a defect in the shipped UI. Do not add diagnostic exceptions to conceal failures.

## Finish with evidence

Run `make tidy`, then `make lint test`, the full `make test-browser`, `make test-count`, and
`make build`. Run `make test-comfyui` when schema, Python integration, or frontend imports change,
and before requesting a manual live-install E2E, as required by the project rules. After any
final rendering change, inspect freshly regenerated screenshots again. Update user-facing help
or README only when behavior or usage changes; document user-visible changes under Unreleased.

Report the visible improvements, links to representative before/after PNGs, checks run, frontend
version, and remaining limitations. If browser setup or image viewing is unavailable, complete
independent work and report that visual verification is blocked; do not substitute mock renders
or claim the UI is verified. Do not loop on the same environmental failure without new evidence.

The browser host uses fake APIs: it does not establish live backend, model, or agent correctness.
Keep the live ComfyUI install untouched; never restart it, run generation against a real account,
or use it as an asset/output destination. This skill does not authorize commits or pushes.
