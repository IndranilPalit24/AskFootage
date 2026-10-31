-- AskFootage footage library: cameras, recordings, clips, zones, saved clips and the object
-- tracks found in each recording.
--
-- SqliteLibraryStore (store.py) applies this file once, in one transaction, to a new and
-- empty database. The PRAGMA user_version at the end records the schema version: a later
-- change adds a migration in store.py and bumps the number, and a database whose version
-- is newer than the code knows is refused rather than guessed at.
--
-- Version history
-- - 1: one camera, with a caller-chosen id such as 'loading-dock'.
-- - 2: the camera registry: ids CAM-001, CAM-002, ... given out by the store and never
--   reused, plus each camera's address, login name, status and details.
--   Demo data only: upgrading from v1 drops and recreates; the seed then refills it.
--   (store.py drops every v1 table and applies this file, in one transaction.)
-- - 3: object tracks (tracks, track_points) and recordings.status_note, the reason the last
--   indexing attempt failed. Demo data only: upgrading from v1 or v2 drops and recreates;
--   the seed then refills it, and every recording must be indexed again. (store.py drops
--   every old table and applies this file, in one transaction.)
--
-- Conventions
-- - Recording, clip, zone and saved-clip ids are chosen by the caller: 1 to 64 letters,
--   digits, '-' or '_'. Camera ids are 'CAM-' plus the camera's number, zero-padded to at
--   least 3 digits (CAM-001, CAM-999, CAM-1000); camera_sequence hands the numbers out.
-- - day is 'YYYY-MM-DD'. A time of day is whole seconds since camera-local midnight
--   (0 to 86399). Offsets inside a recording are whole seconds from its start.
-- - saved_at and created_at are UTC written as 'YYYY-MM-DDTHH:MM:SS.ffffffZ', so text order
--   is time order.
-- - Ordered children (evidence, key frames, zone points) keep a 0-based position.
-- - Deleting a camera removes its recordings and zones; deleting a recording removes its
--   clips and tracks; deleting a clip removes its evidence, key frames and saved-clip
--   entry; deleting a track removes its points.
-- - Track times are frame numbers on the recording's constant-frame-rate working copy
--   (askfootage/domain/timebase.py turns them into seconds), never stored floats.
-- - No identity of any kind (ADR 0008): labels are neutral object words such as 'person'.
-- - No password of any kind: a camera's stream password is checked by the API and dropped.
--   cameras.username is the camera's stream login (such as 'viewer'), not a person.
-- - Every table is STRICT: a value that does not fit the column's type is refused.
-- - A CHECK passes when its expression is NULL, so checks use IS where NULL could appear.

-- The last camera number handed out. Exactly one row, and its number only ever goes up,
-- so a number is never handed out twice, even after the newest camera is deleted. The
-- triggers below keep it in step with every insert into cameras, whoever writes it.
CREATE TABLE camera_sequence (
    only_row    INTEGER NOT NULL PRIMARY KEY CHECK (only_row = 1),
    last_number INTEGER NOT NULL CHECK (last_number >= 0)
) STRICT;

INSERT INTO camera_sequence (only_row, last_number) VALUES (1, 0);

CREATE TRIGGER camera_sequence_never_goes_back
BEFORE UPDATE ON camera_sequence
WHEN NEW.last_number < OLD.last_number OR NEW.only_row IS NOT OLD.only_row
BEGIN
    SELECT RAISE(ABORT, 'camera_sequence only counts up');
END;

CREATE TRIGGER camera_sequence_is_kept
BEFORE DELETE ON camera_sequence
BEGIN
    SELECT RAISE(ABORT, 'camera_sequence is never deleted');
END;

CREATE TABLE cameras (
    id         TEXT    NOT NULL PRIMARY KEY,
    -- The number inside id. UNIQUE, and its index serves list_cameras in number order
    -- (CAM-1000 after CAM-999, which text order would get wrong).
    number     INTEGER NOT NULL UNIQUE CHECK (number >= 1),
    name       TEXT    NOT NULL
               CHECK (trim(name, char(32, 9, 10, 11, 12, 13)) <> '' AND length(name) <= 80),
    ip         TEXT    NOT NULL  -- IPv4 address or host name
               CHECK (trim(ip, char(32, 9, 10, 11, 12, 13)) <> '' AND length(ip) <= 253),
    username   TEXT    NOT NULL CHECK (length(username) BETWEEN 1 AND 64),
    status     TEXT    NOT NULL CHECK (status IN ('online', 'standby', 'offline')),
    location   TEXT    CHECK (location IS NULL
                              OR (trim(location, char(32, 9, 10, 11, 12, 13)) <> ''
                                  AND length(location) <= 80)),
    department TEXT    CHECK (department IS NULL
                              OR (trim(department, char(32, 9, 10, 11, 12, 13)) <> ''
                                  AND length(department) <= 80)),
    created_at TEXT    NOT NULL
               CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
                      AND date(created_at) IS substr(created_at, 1, 10)),
    -- One spelling per number: CAM-001, never CAM-1 or CAM-0001.
    CHECK (id = 'CAM-' || printf('%03d', number))
) STRICT;

-- A camera name is unique ignoring case (str.casefold). lower() folds ASCII only, so the
-- store checks the casefolded names inside its write transaction; this index refuses an
-- ASCII-case repeat from any writer.
CREATE UNIQUE INDEX cameras_name_unique ON cameras (lower(name));

-- A new camera must take a number above every number handed out so far...
CREATE TRIGGER cameras_number_is_new
BEFORE INSERT ON cameras
WHEN NEW.number <= (SELECT last_number FROM camera_sequence WHERE only_row = 1)
BEGIN
    SELECT RAISE(ABORT, 'camera number already handed out');
END;

-- ...and then becomes the last one handed out.
CREATE TRIGGER cameras_number_is_counted
AFTER INSERT ON cameras
BEGIN
    UPDATE camera_sequence SET last_number = NEW.number WHERE only_row = 1;
END;

-- A camera's id and number never change: other rows and the UI refer to them.
CREATE TRIGGER cameras_id_is_fixed
BEFORE UPDATE OF id, number ON cameras
WHEN NEW.id IS NOT OLD.id OR NEW.number IS NOT OLD.number
BEGIN
    SELECT RAISE(ABORT, 'a camera id never changes');
END;

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
    -- Why the last indexing attempt failed, shown to the user; NULL when there is nothing
    -- to say. Never blank, at most 300 characters (STATUS_NOTE_MAX).
    status_note    TEXT
                   CHECK (status_note IS NULL
                          OR (trim(status_note, char(32, 9, 10, 11, 12, 13)) <> ''
                              AND length(status_note) <= 300)),
    -- The key clips point at, so a clip's copied camera and day always match its recording.
    UNIQUE (id, camera_id, day)
) STRICT;

-- One camera: list_recordings and summarise_days (one day or a range of days, by start);
-- camera_counts; and the cascade when a camera is deleted.
CREATE INDEX recordings_by_camera_day ON recordings (camera_id, day, start_time, id);
-- Every camera: list_recordings (by start, then camera number, then id) and summarise_days.
-- Camera ids are written one way per number (see cameras), so ordering them by length and
-- then text is number order: CAM-999 before CAM-1000.
CREATE INDEX recordings_by_day ON recordings (day, start_time, length(camera_id), camera_id, id);

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
-- list_clips for one camera: one day, by start time.
CREATE INDEX clips_by_camera_day ON clips (camera_id, day, start_time, id);
-- list_clips for every camera: one day, by start time.
CREATE INDEX clips_by_day ON clips (day, start_time, id);

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

-- One object followed through one recording, found for one concept (an object noun such
-- as 'person'). track_id is perception's own number for it, unique per recording and label;
-- id is this table's row number, which track_points refer to. A track always has at least
-- one point: a CHECK cannot count rows, so the store writes a track and its points in one
-- transaction, and tracks_for joins to the points, so a pointless row could never be read.
CREATE TABLE tracks (
    id           INTEGER NOT NULL PRIMARY KEY,
    recording_id TEXT    NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    -- A neutral object noun, never an identity (ADR 0008): trimmed, 1 to 40 characters.
    label        TEXT    NOT NULL
                 CHECK (label <> ''
                        AND label = trim(label, char(32, 9, 10, 11, 12, 13))
                        AND length(label) <= 40),
    track_id     INTEGER NOT NULL CHECK (track_id >= 0),
    -- Its index serves tracks_for (one recording and label, by track_id), the replace in
    -- save_tracks, delete_video, and the cascade when a recording is deleted.
    UNIQUE (recording_id, label, track_id)
) STRICT;

-- One box per frame of a track; a track may skip frames. A box is in source-frame pixels
-- with its origin top-left, finite (SQLite stores NaN as NULL, which NOT NULL refuses, and
-- abs(inf) is not below 9e999, which SQLite reads as infinity) and never inverted.
-- WITHOUT ROWID: the rows are stored in (track_row, frame) order, so a track's points are
-- read in frame order straight from the primary key, with no separate index.
CREATE TABLE track_points (
    track_row INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    frame     INTEGER NOT NULL CHECK (frame >= 0),
    x1        REAL    NOT NULL CHECK (abs(x1) < 9e999),
    y1        REAL    NOT NULL CHECK (abs(y1) < 9e999),
    x2        REAL    NOT NULL CHECK (abs(x2) < 9e999),
    y2        REAL    NOT NULL CHECK (abs(y2) < 9e999),
    CHECK (x1 <= x2 AND y1 <= y2),
    PRIMARY KEY (track_row, frame)
) STRICT, WITHOUT ROWID;

PRAGMA user_version = 3;
