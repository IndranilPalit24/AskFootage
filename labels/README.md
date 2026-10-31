# Ground-truth labels

One JSON file per video, named after it (for example `labels/demo-1.json`). Frames are
frames of the prepared 5 fps copy, and both ends are inclusive. Score a file with:

    .venv\Scripts\python.exe -m askfootage.interfaces.cli.evaluate labels\demo-1.json

```json
{
  "video_id": "demo-1",
  "person": "person",
  "object": "cardboard box",
  "dwell_min_frames": 10,
  "zones": { "dock": [[400, 120], [600, 120], [600, 300], [400, 300]] },
  "relations": [
    { "kind": "carrying", "start_frame": 12, "end_frame": 58 },
    { "kind": "in_zone", "zone": "dock", "start_frame": 40, "end_frame": 75 },
    { "kind": "dwell", "zone": "dock", "start_frame": 50, "end_frame": 75 }
  ]
}
```

- `video_id` (required): the id the video was ingested under.
- `relations` (required, may be empty): `kind` is `carrying`, `in_zone` or `dwell`;
  `start_frame` and `end_frame` are whole numbers, end not before start. `in_zone` and
  `dwell` also name a `zone` that exists in `zones`.
- `zones`: name to polygon of at least 3 `[x, y]` points, in the pixel coordinates of the
  tracks. Optional if no relation uses a zone. By default points are PIXELS of the prepared
  video. Set `"zone_units": "fraction"` to give them as fractions (0 to 1) of the frame, the
  way saved zones are in the app; they are then scaled by the frame size the ingest recorded.
- `person`, `object`: the concepts used as the person and the carried object (defaults
  `person` and `cardboard box`). `dwell_min_frames`: shortest stay that counts as dwell
  (default 10).

Predictions follow the same rules as search: tracks are stitched, `in_zone` means entering
the zone from outside (a track first seen inside does not count), and neighbouring
intervals are merged. Frame numbers go up to 1,000,000. A video with no stored tracks is an
error, not a table of zeros.

Each relation is scored separately (`carrying`, `in_zone:dock`, ...) for precision,
recall, f1 and frame IoU, counted per frame, plus interval matches at an IoU of 0.5 by
default (`--iou`). Add `--json` for machine output.
