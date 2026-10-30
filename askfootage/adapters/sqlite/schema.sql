-- AskFootage footage library: cameras, recordings, clips, zones and saved clips.
--
-- SqliteLibraryStore (store.py) applies this file once, in one transaction, to a new and
-- empty database. The PRAGMA user_version at the end records the schema version: a later
-- change adds a migration in store.py and bumps the number, and a database whose version
-- is newer than the code knows is refused rather than guessed at.
--
-- Conventions
-- - Ids are chosen by the caller: 1 to 64 letters, digits, '-' or '_'.
-- - day is 'YYYY-MM-DD'. A time of day is whole seconds since camera-local midnight
--   (0 to 86399). Offsets inside a recording are whole seconds from its start.
-- - saved_at is UTC written as 'YYYY-MM-DDTHH:MM:SS.ffffffZ', so text order is time order.
-- - Ordered children (evidence, key frames, zone points) keep a 0-based position.
-- - Deleting a camera removes its recordings and zones; deleting a recording removes its
--   clips; deleting a clip removes its evidence, key frames and saved-clip entry.
-- - No identity of any kind (ADR 0008): labels are neutral object words such as 'person'.
-- - Every table is STRICT: a value that does not fit the column's type is refused.
-- - A CHECK passes when its expression is NULL, so checks use IS where NULL could appear.

CREATE TABLE cameras (
    id   TEXT NOT NULL PRIMARY KEY
         CHECK (length(id) BETWEEN 1 AND 64 AND id NOT GLOB '*[^A-Za-z0-9_-]*'),
    name TEXT NOT NULL
         CHECK (trim(name, char(32, 9, 10, 11, 12, 13)) <> '')
) STRICT;

CREATE TABLE recordings (
    id             TEXT    NOT NULL PRIMARY KEY
                   CHECK (length(id) BETWEEN 1 AND 64 AND id NOT GLOB '*[^A-Za-z0-9_-]*'),
    camera_id      TEXT    NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
    day            TEXT    NOT NULL
                   CHECK (day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                          AND date(day) IS day),
    start_time     INTEGER NOT NULL CHECK (start_time BETWEEN 0 AND 86399),
    length_seconds INTEGER NOT NULL CHECK (length_seconds >= 0),
    status         TEXT    NOT NULL
                   CHECK (status IN ('waiting', 'preparing', 'indexing', 'ready')),
    -- The key clips point at, so a clip's copied camera and day always match its recording.
    UNIQUE (id, camera_id, day)
) STRICT;

-- list_recordings and summarise_days: one camera, one day or a range of days, by start.
CREATE INDEX recordings_by_camera_day ON recordings (camera_id, day, start_time, id);

CREATE TABLE clips (
    id            TEXT    NOT NULL PRIMARY KEY
                  CHECK (length(id) BETWEEN 1 AND 64 AND id NOT GLOB '*[^A-Za-z0-9_-]*'),
    recording_id  TEXT    NOT NULL,
    camera_id     TEXT    NOT NULL,  -- the recording's camera, copied for list_clips
    day           TEXT    NOT NULL,  -- the recording's day (checked there)
    start_time    INTEGER NOT NULL CHECK (start_time BETWEEN 0 AND 86399),
    start_seconds INTEGER NOT NULL CHECK (start_seconds >= 0),
    end_seconds   INTEGER NOT NULL CHECK (end_seconds > start_seconds),
    label         TEXT    NOT NULL CHECK (trim(label, char(32, 9, 10, 11, 12, 13)) <> ''),
    zone          TEXT,              -- zone name shown with the clip; not a link to zones
    why_matched   TEXT    NOT NULL,
    thumbnail_url TEXT,
    FOREIGN KEY (recording_id, camera_id, day)
        REFERENCES recordings (id, camera_id, day) ON DELETE CASCADE
) STRICT;

-- Clips of one recording in time order; also serves the cascade from recordings.
CREATE INDEX clips_by_recording ON clips (recording_id, start_seconds);
-- list_clips: one camera, one day, by start time.
CREATE INDEX clips_by_camera_day ON clips (camera_id, day, start_time, id);

CREATE TABLE clip_evidence (
    clip_id  TEXT    NOT NULL REFERENCES clips (id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    kind     TEXT    NOT NULL CHECK (kind IN ('carrying', 'in_zone', 'dwell')),
    text     TEXT    NOT NULL CHECK (trim(text, char(32, 9, 10, 11, 12, 13)) <> ''),
    PRIMARY KEY (clip_id, position)
) STRICT;

CREATE TABLE clip_key_frames (
    clip_id    TEXT    NOT NULL REFERENCES clips (id) ON DELETE CASCADE,
    position   INTEGER NOT NULL CHECK (position >= 0),
    at_seconds INTEGER NOT NULL CHECK (at_seconds >= 0),
    image_url  TEXT,
    PRIMARY KEY (clip_id, position)
) STRICT;

CREATE TABLE zones (
    id        TEXT NOT NULL PRIMARY KEY
              CHECK (length(id) BETWEEN 1 AND 64 AND id NOT GLOB '*[^A-Za-z0-9_-]*'),
    camera_id TEXT NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
    name      TEXT NOT NULL
              CHECK (trim(name, char(32, 9, 10, 11, 12, 13)) <> '' AND length(name) <= 60)
) STRICT;

-- A zone name is unique per camera ignoring case (str.casefold). NOCASE folds ASCII only,
-- so the store checks the casefolded names inside its write transaction; this index refuses
-- an exact repeat from any writer, and serves list_zones for one camera, by name.
CREATE UNIQUE INDEX zones_name_per_camera ON zones (camera_id, name);
-- list_zones for every camera, by name.
CREATE INDEX zones_by_name ON zones (name, id);

-- A zone needs at least 3 points. A CHECK sees one row at a time, so the store enforces
-- that inside the same transaction that writes the points.
CREATE TABLE zone_points (
    zone_id  TEXT    NOT NULL REFERENCES zones (id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    x        REAL    NOT NULL CHECK (x BETWEEN 0 AND 1),
    y        REAL    NOT NULL CHECK (y BETWEEN 0 AND 1),
    PRIMARY KEY (zone_id, position)
) STRICT;

CREATE TABLE saved_clips (
    id       TEXT NOT NULL PRIMARY KEY
             CHECK (length(id) BETWEEN 1 AND 64 AND id NOT GLOB '*[^A-Za-z0-9_-]*'),
    -- UNIQUE: a clip can be saved at most once (and finds its saved entry fast).
    clip_id  TEXT NOT NULL UNIQUE REFERENCES clips (id) ON DELETE CASCADE,
    note     TEXT NOT NULL CHECK (length(note) <= 500),
    saved_at TEXT NOT NULL
             CHECK (saved_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
                    AND date(saved_at) IS substr(saved_at, 1, 10))
) STRICT;

-- list_saved_clips: newest first, then id.
CREATE INDEX saved_clips_by_saved_at ON saved_clips (saved_at DESC, id);

PRAGMA user_version = 1;
