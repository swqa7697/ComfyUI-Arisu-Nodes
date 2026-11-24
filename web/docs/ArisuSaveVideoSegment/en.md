# Save Video Segment

Save one rendered segment as a playable MP4 and publish it as a **take**: a video file with a small record
beside it, and its sound kept a second time as uncompressed audio. **Assemble Video** and Director Workbench
find takes through those records, so the saver and the assembly node need no wire between them.

## Why

**Save Video** writes a file and nothing else. To cut several renders into one film, an editor needs
to know what each file really contains: how many frames were delivered after the overlap was trimmed,
at what frame rate, and where the sound ends. This node measures the saved video and records it. It also
keeps the trimmed waveform as PCM, so the final film can encode its soundtrack once from a
continuous waveform, with no gap or shift at the joins.

## Inputs

| Parameter         | Type   | Description                                                                                                                                                                                                                     |
|-------------------|--------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `video`           | VIDEO  | The segment to save: its picture, frame rate and optional sound. Connect it after **Create Video**. The saver treats what arrives as the delivered segment.                                                                    |
| `project_prefix`  | STRING | The project directory under ComfyUI's output directory, such as `motion_context/fixed`. Can be linked from **Path Builder**. Blank uses `arisu_video`.                                          |
| `clip_name`       | STRING | The file's basename inside the project's `videos` directory (default `clip`).                                                                                                                                                   |
| `codec`           | COMBO  | `h264`, `h265` or `av1`.                                                                                                                                                                                                         |
| `crf`             | INT    | Quality on the selected encoder's own scale; lower is better and larger. The widget shows the range.                                                                                                                            |

| Codec | CRF range | Suggested start |
|-------|-----------|-----------------|
| H.264 | 0–51      | 18              |
| H.265 | 0–51      | 20              |
| AV1   | 0–63      | 24              |

Changing the codec moves an untouched suggested value to the new codec's suggestion. A value you chose is kept,
lowered only if it lies past the new range. The numbers are not comparable between codecs.

## Outputs

| Output  | Type  | Description                 |
|---------|-------|-----------------------------|
| `video` | VIDEO | The input video, unchanged. |

The node shows the saved file as a video preview, like **Save Video**.

## Files

With project `P` and `clip_name` `h3_clip`:

```
output/P/videos/
├── h3_clip_00007_.mp4
└── h3_clip_00007_.arisu/
    ├── take.json
    └── audio.wav
```

- The MP4 carries the picture and, with sound, an AAC track.
- `take.json` is the take record: the take's ID, the delivered frame count, frame rate, size, codec and colour
  information, and for sound the sample rate, channel layout and valid sample count. It is written last; a take
  without it is not listed.
- `audio.wav` exists when the segment has sound: the trimmed waveform as floating-point PCM at its own sample rate
  and channel layout.

Every run creates a new take with the next counter. An earlier take is never overwritten, so several candidates of
the same segment stay available for comparison.

## Wiring

```
Motion Context Trim ─▶ Create Video ─▶ Save Video Segment
Path Builder ─▶ (project_prefix)
```

Set `project_prefix` to `P` and `clip_name` to `h3_clip` to save under `P/videos/h3_clip_00001_.mp4`.
Set **Create Video**'s `codec` to `none` so the frames reach this node unencoded.

## Notes

- Files are written only under ComfyUI's output directory. Absolute paths and `..` are refused; Unicode, spaces and
  nested project directories are fine. `%year%`, `%width%` and the other save placeholders are expanded.
- Trim the Motion Context overlap before **Create Video**, from both picture and sound. The saver does not trim: the
  frames it receives are the frames an assembly uses.
- Director Workbench selects the take directory automatically. With a project it saves each take under
  `P/director/<take id>/`, together with that take's latent. Without a project it uses `arisu_director/<take id>/`.
- A cancelled or failed save leaves no partial take behind.
- The MP4 carries the prompt and workflow like **Save Video**, unless ComfyUI runs with `--disable-metadata`.
