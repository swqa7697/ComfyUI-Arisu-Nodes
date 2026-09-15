# Practical Tips Distilled from Production Guides

- H3 prompts are timelines with stated [Shot N] and cut times, not free-form descriptions.
- Always fill the full requested duration with observable change (action, camera, light, micro-motion). Empty seconds cause drift.
- Audio is generated in the same pass; write overall_soundscape and non_diegetic_music in full. Default non_diegetic_music to N/A.
- Spell every word that must be readable on screen; otherwise the model produces letter-shaped noise.
- Negative constraints (no subtitles, no watermarks, no soft dissolves, keep live-action texture) are free and high-leverage.
- When a reference image is present, let it carry visual description; keep the text focused on motion path and sound.
- Hard cuts preferred. Soft transitions only when the user asks.
- Camera language must use the official motion-type + amplitude + speed forms written as natural English inside the shot.
- LoRA trigger words: place at the very start of `integrated_multimodal_description` (lead with the trigger).
- H3 Motion Context is opt-in by `motion.present` in MCP. Continuation rules live in `motion-context.md`. Closing state = `motion.stills` + `motion.notes`.
