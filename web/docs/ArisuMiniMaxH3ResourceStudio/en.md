# MiniMax H3 Resource Studio

Prepare optional first/last keyframes and image, video, and audio references for either MiniMax H3 Hybrid node. Connect **resources**, or enable **Advertise** in the root graph. Advertising replaces competing resource wires; turning it off restores empty sockets. Explicit connections work in subgraphs.

Choose an aspect ratio, or inherit it from an advertising Video Settings node. New keyframes receive a centered Auto-crop. Click a frame canvas to choose or replace its image; use the dedicated crop icon to edit its crop and Reset to use the full image. Changing the effective ratio reapplies Auto-crop to both frames, including muted frames. Reference images start uncropped and do not follow aspect changes. For both keyframes and image references, the crop dialog opens with the saved crop’s ratio selected, using Custom with width and height fields when no preset matches, or Free when uncropped.

Browse references opens at the final reference’s folder in the current list order, including muted cards, or the configured default location when the list is empty. It adds images immediately; videos and audio open a clip editor first. Apply commits the selection; Cancel changes nothing. Edit source-relative start/end times, snap to seconds or tenths (or use free precision), select a fixed duration, and loop or stop playback at the selection end. Videos include their soundtrack by default when one exists.

Drag the hover handle or use keyboard Move up/Move down to reorder references. Mute keeps edits while excluding a resource from execution. The colored image, video, and audio counters show active references only; keyframes and video soundtracks do not count. Limits: nine images, three videos, three standalone audios, and 256 stored cards. Additions beyond an active limit arrive muted.

Studio retains source descriptions, not resized assets. Hybrid reads originals, applies crops, and resizes for its consumer canvas. Video selections are sampled at 24 fps, capped to generation length, and aligned down to H3's 17k+5 frame grid: a five-second selection supplies 107 usable frames, while a five-second generation setting produces 124. Paired audio follows that effective video interval. An audio VAE is needed only for active emitted audio.

Playback tries the original first. Unsupported browser codecs can use an on-demand VP9/Opus proxy with original display dimensions. One conversion runs at a time; cache capacity is 2 GiB, conversion deadline ten minutes, and idle expiry thirty minutes. Proxies affect playback only.

Locations remain beneath input/output or administrator-configured roots. Reopening a saved workflow preserves selections; importing or duplicating requires reselection. A changed source fails visibly rather than mixing revisions. An empty bundle is valid; combining a bundle with individual resource inputs is rejected.
