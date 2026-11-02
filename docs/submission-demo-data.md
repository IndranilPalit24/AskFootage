# Submission text: demo data

This build includes a generated demo dataset: 18 cameras, 61 zones and about 1,400 recordings over seven days, with mixed statuses. It is produced by a deterministic generator (`askfootage/adapters/sqlite/volume_seed.py`) and marked in the database with `origin = 'demo_volume'`. It stands in for the size of a real site and is not a real facility or real activity.

Only the two supplied clips (`clip1`, `clip2`) have video, stored object tracks, relation proofs and evidence snapshots. Search returns only those clips. Generated recordings have no video, and the app says so ("Footage not included in this demo build"). No saved clips, search matches, proofs, tracks or activity history are generated.

The data can be listed, added or removed with `python -m askfootage.interfaces.cli.volume --status | --add | --remove`.
