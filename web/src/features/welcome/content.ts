// Static copy of the welcome page. Every claim here matches what the app and its API do today; the
// previews on the page are sample content and say so.
import type { IconName } from '../../components/Icon';

/** Where every "Try the demo" link goes: the Find Footage screen. */
export const DEMO_PATH = '/';

export const HEADLINE = 'Ask your footage. Get the clip and the proof.';

/** The question shown in the hero's ask box. */
export const HERO_QUESTION = 'Show me when a person carried a box';

/** The in-page links of the top bar, in page order. Each id is a section on the page. */
export const SECTION_LINKS = [
  { id: 'how', label: 'How it works' },
  { id: 'features', label: 'Features' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'cost', label: 'Cost' },
] as const;

export interface Feature {
  icon: IconName;
  title: string;
  text: string;
}

export const FEATURES: readonly Feature[] = [
  {
    icon: 'search',
    title: 'Plain-English search',
    text: 'Type a question such as "someone carrying a box". It is matched against the objects and movements found when the footage was indexed.',
  },
  {
    icon: 'proof',
    title: 'Proof with every clip',
    text: 'Each result shows its time range, an evidence frame with the matched object outlined, and the measured values behind the match.',
  },
  {
    icon: 'calendar',
    title: 'Daily footage library per camera',
    text: 'Recordings are kept per camera and per day, so you can see what was recorded and what is ready to search.',
  },
  {
    icon: 'zones',
    title: 'Zones',
    text: 'Draw an area on a still frame, such as a doorway, then ask what happened inside it or how long something stayed there.',
  },
  {
    icon: 'bookmark',
    title: 'Saved clips',
    text: 'Keep the clips you need as evidence and come back to them later.',
  },
  {
    icon: 'object',
    title: 'Any object you can name',
    text: 'Pick object types with a short phrase, with no labelling or training. Each new object type is indexed once before you ask about it.',
  },
];

export interface Integration {
  icon: IconName;
  title: string;
  text: string;
}

export const INTEGRATIONS: readonly Integration[] = [
  {
    icon: 'camera',
    title: 'IP cameras via RTSP',
    text: 'Add a camera with its stream address. Its password is checked once and never stored.',
  },
  {
    icon: 'upload',
    title: 'MP4 and MOV uploads',
    text: 'Upload MP4 recordings in the app. MOV files are accepted when footage is prepared for indexing.',
  },
  {
    icon: 'folder',
    title: 'Daily recording folders',
    text: 'Footage is organised by camera and by day, the way recorders already keep it.',
  },
];

export interface Scenario {
  title: string;
  question: string;
  result: string;
}

export const SCENARIOS: readonly Scenario[] = [
  {
    title: 'Warehouse loading dock',
    question: 'Show me when someone carried a box through the loading door.',
    result: 'Each clip with its time range, the box outlined, and how closely the person and the box moved together.',
  },
  {
    title: 'Retail shop floor',
    question: 'Show me when someone waited by the counter.',
    result: 'The moments a person stayed inside the counter zone you drew, with how long they stayed.',
  },
  {
    title: 'Office entrance',
    question: 'Show me when a person walked through the entrance.',
    result: 'Each crossing of the entrance zone, as a short clip with its time range.',
  },
];

export const SCENARIOS_NOTE = 'Illustrative examples, not customer testimonials.';

export const PRIVACY_POINTS: readonly string[] = [
  'AskFootage finds objects and movements, such as a person carrying a box. It never works out who someone is.',
  'The camera password is checked when you add a camera, and never stored.',
  'Indexing sends the prepared footage to a hosted video-analysis service. Later searches read the saved index instead of processing the footage again.',
  'Every result shows its evidence, so you can check a match yourself.',
];

// ---------- Cost ----------

/** Footage is indexed from a 5 frames per second copy. */
export const INDEX_FPS = 5;
/** About $0.20 per 1,000 frames, per object type, held in cents so the arithmetic stays exact. */
export const CENTS_PER_1000_FRAMES = 20;

/** The worked example: 30 minutes of footage, four object types (person, cardboard box, bag, crate). */
export const EXAMPLE_MINUTES = 30;
export const EXAMPLE_OBJECT_TYPES = 4;

export interface CostExample {
  frames: number;
  centsPerObjectType: number;
  totalCents: number;
}

export function costExample(minutes = EXAMPLE_MINUTES, objectTypes = EXAMPLE_OBJECT_TYPES): CostExample {
  const frames = minutes * 60 * INDEX_FPS;
  const centsPerObjectType = (frames * CENTS_PER_1000_FRAMES) / 1000;
  return { frames, centsPerObjectType, totalCents: centsPerObjectType * objectTypes };
}

const NUMBER = new Intl.NumberFormat('en-US');
const DOLLARS = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export function formatNumber(value: number): string {
  return NUMBER.format(value);
}

/** 180 -> "$1.80" */
export function formatCents(cents: number): string {
  return DOLLARS.format(cents / 100);
}
