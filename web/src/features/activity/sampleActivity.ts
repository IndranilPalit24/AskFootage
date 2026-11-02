// SAMPLE DATA. The app records no user activity: there is no log, no accounts and no endpoint for either.
// These rows exist only to show what a future Activity Log page could look like. They are invented, name no
// real person, camera or clip, and are never read from or written to the API.

export const ACTIVITY_ACTIONS = ['Searched footage', 'Opened clip', 'Saved clip', 'Updated zone', 'Added camera'] as const;
export type ActivityAction = (typeof ACTIVITY_ACTIONS)[number];

export interface SampleActivityEntry {
  id: string;
  /** Sample date, YYYY-MM-DD. */
  day: string;
  /** Sample time of day, HH:MM:SS. */
  time: string;
  user: string;
  action: ActivityAction;
  target: string;
  result: string;
}

export const SAMPLE_ACTIVITY_LOG: readonly SampleActivityEntry[] = [
  { id: 's01', day: '2026-10-30', time: '14:18:03', user: 'Sample user 1', action: 'Searched footage', target: 'All cameras', result: '1 result' },
  { id: 's02', day: '2026-10-30', time: '14:18:12', user: 'Sample user 1', action: 'Opened clip', target: 'Sample clip A', result: 'Success' },
  { id: 's03', day: '2026-10-30', time: '14:19:05', user: 'Sample user 1', action: 'Saved clip', target: 'Sample clip A', result: 'Success' },
  { id: 's04', day: '2026-10-30', time: '13:02:11', user: 'Sample user 2', action: 'Searched footage', target: 'Sample camera 2', result: '3 results' },
  { id: 's05', day: '2026-10-30', time: '11:04:28', user: 'Sample user 3', action: 'Opened clip', target: 'Sample clip B', result: 'Success' },
  { id: 's06', day: '2026-10-30', time: '11:05:14', user: 'Sample user 3', action: 'Saved clip', target: 'Sample clip B', result: 'Success' },
  { id: 's07', day: '2026-10-29', time: '09:47:01', user: 'Sample user 2', action: 'Updated zone', target: 'Sample camera 1 (Sample zone)', result: 'Success' },
  { id: 's08', day: '2026-10-29', time: '09:12:36', user: 'Sample user 4', action: 'Added camera', target: 'Sample camera 3', result: 'Success' },
  { id: 's09', day: '2026-10-29', time: '08:31:22', user: 'Sample user 4', action: 'Searched footage', target: 'All cameras', result: '12 results' },
  { id: 's10', day: '2026-10-29', time: '08:15:11', user: 'Sample user 2', action: 'Opened clip', target: 'Sample clip C', result: 'Success' },
];

export const ACTIVITY_BANNER = 'Proposed page for access and evidence traceability. Sample data, not recorded activity.';
