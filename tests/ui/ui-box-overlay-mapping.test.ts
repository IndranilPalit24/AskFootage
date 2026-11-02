// The pure mapping from stored boxes (source pixels) to the rectangles drawn over the player.
import { describe, expect, it } from 'vitest';
import type { RecordingBoxes } from '../../web/src/api/generated/types';
import { boxesAt, containRect, frameAt, pointAt } from '../../web/src/features/player/boxOverlay';
import example from '../../contract/examples/recording-boxes.json';

/** clip2: the contract example. At frame 5 (1.0 s at 5 fps) the person and the cardboard box are in view. */
const clip2 = example as unknown as RecordingBoxes;
const VIDEO = { width: 1920, height: 1080 };

function objectBox(boxes: ReturnType<typeof boxesAt>) {
  return boxes.find((box) => box.role === 'object');
}

describe('frameAt', () => {
  it('is the nearest frame number: seconds times fps, rounded', () => {
    expect(frameAt(1, 5)).toBe(5);
    expect(frameAt(0.6, 5)).toBe(3); // 3.0000000000000004
    expect(frameAt(0.49, 5)).toBe(2);
    expect(frameAt(0.5, 5)).toBe(3);
  });
});

describe('containRect', () => {
  it('fills the element when the aspect ratios match', () => {
    expect(containRect({ width: 960, height: 540 }, VIDEO)).toEqual({ left: 0, top: 0, width: 960, height: 540 });
  });
  it('letterboxes (bars above and below) in a taller element', () => {
    expect(containRect({ width: 960, height: 720 }, VIDEO)).toEqual({ left: 0, top: 90, width: 960, height: 540 });
  });
  it('pillarboxes (bars on the sides) in a wider element', () => {
    expect(containRect({ width: 1280, height: 540 }, VIDEO)).toEqual({ left: 160, top: 0, width: 960, height: 540 });
  });
});

describe('boxesAt, converting the stored clip2 box to player coordinates', () => {
  // Stored object box: x 800..1000, y 500..700. Stored person box: x 700..1100, y 200..1000. Both at frame 5.
  it('is the identity at the native size', () => {
    const boxes = boxesAt(clip2, 1, { width: 1920, height: 1080 }, VIDEO);
    expect(objectBox(boxes)).toEqual({ trackId: 0, label: 'cardboard box', role: 'object', left: 800, top: 500, width: 200, height: 200 });
  });

  it('scales to a half-size player', () => {
    const boxes = boxesAt(clip2, 1, { width: 960, height: 540 }, VIDEO);
    expect(boxes).toEqual([
      { trackId: 0, label: 'person', role: 'person', left: 350, top: 100, width: 200, height: 400 },
      { trackId: 0, label: 'cardboard box', role: 'object', left: 400, top: 250, width: 100, height: 100 },
    ]);
  });

  it('offsets by the top bar when the player is taller than the picture (letterbox)', () => {
    const boxes = boxesAt(clip2, 1, { width: 960, height: 720 }, VIDEO);
    expect(objectBox(boxes)).toMatchObject({ left: 400, top: 340, width: 100, height: 100 });
  });

  it('offsets by the side bar when the player is wider than the picture (pillarbox)', () => {
    const boxes = boxesAt(clip2, 1, { width: 1280, height: 540 }, VIDEO);
    expect(objectBox(boxes)).toMatchObject({ left: 560, top: 250, width: 100, height: 100 });
  });

  it('scales up in a full-screen sized player', () => {
    const boxes = boxesAt(clip2, 1, { width: 3840, height: 2160 }, VIDEO);
    expect(objectBox(boxes)).toMatchObject({ left: 1600, top: 1000, width: 400, height: 400 });
  });

  it('uses the video element size, not the stored frame size, to place the picture', () => {
    // A 960x540 file analysed at 1920x1080: same aspect ratio, so the same boxes.
    const boxes = boxesAt(clip2, 1, { width: 960, height: 540 }, { width: 960, height: 540 });
    expect(objectBox(boxes)).toMatchObject({ left: 400, top: 250, width: 100, height: 100 });
    // A different aspect ratio (4:3 picture in a 16:9 player) leaves side bars: 720 wide at left 120.
    const narrow = boxesAt(clip2, 1, { width: 960, height: 540 }, { width: 1440, height: 1080 });
    expect(objectBox(narrow)).toMatchObject({ left: 420, top: 250, width: 75, height: 100 });
  });

  it('falls back to the stored frame size while the video size is not known yet', () => {
    const unknown = boxesAt(clip2, 1, { width: 960, height: 540 }, { width: 0, height: 0 });
    expect(objectBox(unknown)).toMatchObject({ left: 400, top: 250 });
    expect(objectBox(boxesAt(clip2, 1, { width: 960, height: 540 }))).toMatchObject({ left: 400, top: 250 });
  });

  it('draws nothing in a player with no size', () => {
    expect(boxesAt(clip2, 1, { width: 0, height: 0 }, VIDEO)).toEqual([]);
  });
});

describe('boxesAt, over time', () => {
  const player = { width: 960, height: 540 };

  it('draws nothing before the first or after the last detection', () => {
    expect(boxesAt(clip2, 0, player, VIDEO)).toEqual([]);
    expect(boxesAt(clip2, 0.6, player, VIDEO)).toEqual([]); // frame 3, two frames before 5
    expect(boxesAt(clip2, 1.4, player, VIDEO)).toEqual([]); // frame 7
    expect(boxesAt(clip2, 60, player, VIDEO)).toEqual([]);
  });

  it('allows the nearest detection one frame away, and no further', () => {
    expect(boxesAt(clip2, 0.8, player, VIDEO)).toHaveLength(2); // frame 4
    expect(boxesAt(clip2, 1.2, player, VIDEO)).toHaveLength(2); // frame 6
    expect(boxesAt(clip2, 0.69, player, VIDEO)).toEqual([]); // 3.45 rounds to frame 3
  });

  it('draws no box in a gap between detections (no extrapolation)', () => {
    const gappy: RecordingBoxes = {
      ...clip2,
      tracks: [
        {
          trackId: 3,
          label: 'cardboard box',
          role: 'object',
          points: [
            { frame: 5, x1: 800, y1: 500, x2: 1000, y2: 700 },
            { frame: 10, x1: 900, y1: 500, x2: 1100, y2: 700 },
          ],
        },
      ],
    };
    const at = (frame: number) => boxesAt(gappy, frame / 5, player, VIDEO);
    expect(at(5)).toHaveLength(1);
    expect(at(6)).toHaveLength(1); // one frame from 5
    expect(at(7)).toEqual([]);
    expect(at(8)).toEqual([]);
    expect(at(9)).toHaveLength(1); // one frame from 10
    expect(at(10)[0]).toMatchObject({ left: 450, top: 250 });
    expect(at(11)).toHaveLength(1);
    expect(at(12)).toEqual([]);
  });

  it('prefers the exact frame over a neighbour', () => {
    const points = [
      { frame: 4, x1: 1, y1: 1, x2: 2, y2: 2 },
      { frame: 5, x1: 3, y1: 3, x2: 4, y2: 4 },
      { frame: 6, x1: 5, y1: 5, x2: 6, y2: 6 },
    ];
    expect(pointAt(points, 5)).toBe(points[1]);
    expect(pointAt(points, 7)).toBe(points[2]);
    expect(pointAt(points, 8)).toBeNull();
    expect(pointAt([], 0)).toBeNull();
  });
});

describe('boxesAt, person and object rules', () => {
  const person = clip2.tracks[0]!;

  it('draws no box at all for a recording with only a person (clip1)', () => {
    const clip1: RecordingBoxes = { ...clip2, recordingId: 'clip1', tracks: [person] };
    expect(boxesAt(clip1, 1, { width: 960, height: 540 }, VIDEO)).toEqual([]);
  });

  it('draws nothing for a recording with no tracks', () => {
    expect(boxesAt({ ...clip2, tracks: [] }, 1, { width: 960, height: 540 }, VIDEO)).toEqual([]);
  });

  it('draws the person only while some object track exists, even when the object is out of view', () => {
    const personLate: RecordingBoxes = {
      ...clip2,
      tracks: [
        { ...person, points: [{ frame: 20, x1: 0, y1: 0, x2: 192, y2: 108 }] },
        clip2.tracks[1]!,
      ],
    };
    // At frame 20 the object is gone but the recording has an object track: the person is drawn.
    expect(boxesAt(personLate, 4, { width: 960, height: 540 }, VIDEO).map((box) => box.role)).toEqual(['person']);
  });
});
