# Extract Last Images

Keep the last `count` images of a batch, for example the ending frames of a decoded video for a
preview or as the next clip's first frame.

## Why

Getting "the last N frames" with stock nodes takes a frame-count node, a subtraction and a batch
split, and the chain breaks when the batch is shorter than expected. This node does the slice in one
step and caps `count` at the batch size.

## Inputs

| Parameter | Type  | Description                                                                 |
|-----------|-------|-----------------------------------------------------------------------------|
| `images`  | IMAGE | An image batch, for example the decoded frames of a video.                  |
| `count`   | INT   | How many images to keep from the end (default 1). More than the batch holds keeps the whole batch. |

## Outputs

| Output   | Type  | Description                                         |
|----------|-------|-----------------------------------------------------|
| `images` | IMAGE | The last `count` images, in their original order.   |

## Wiring

```
VAE Decode ─▶ Extract Last Images (count = 1) ─▶ Preview Image
```

## Notes

- The output is a copy, so downstream edits never touch the source batch.
- To pick an arbitrary range instead, use ComfyUI's **Get Image from Batch** (`batch_index`,
  `length`), which counts from the start.
