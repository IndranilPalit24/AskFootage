// Zone geometry. Points are [x, y] fractions (0..1) of the frame's width and height, from the top-left.

import type { Point, Zone } from '../../api/generated/types';

export const MIN_ZONE_POINTS = 3;
export const MAX_ZONE_POINTS = 50;
export const ZONE_NAME_MAX = 60;

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Rounds to 4 decimals, the precision the contract's examples use. */
export function round4(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

/**
 * A position inside a box of width x height (for example offsetX, offsetY of a click on the frame) as a
 * normalised point, clamped to 0..1 and rounded to 4 decimals. Null when the box has no size.
 */
export function normalisedPoint(x: number, y: number, width: number, height: number): Point | null {
  if (!(width > 0) || !(height > 0)) return null;
  return [round4(clamp01(x / width)), round4(clamp01(y / height))];
}

/** Moves a point by (dx, dy), staying inside the frame. */
export function nudge(point: Point, dx: number, dy: number): Point {
  return [round4(clamp01(point[0] + dx)), round4(clamp01(point[1] + dy))];
}

/** The points attribute of an SVG polygon or polyline in the 0..1 viewBox. */
export function svgPoints(points: Point[]): string {
  return points.map(([x, y]) => `${x},${y}`).join(' ');
}

/** The average of the corners: where a zone's name label goes. */
export function labelPosition(points: Point[]): Point {
  if (points.length === 0) return [0.5, 0.5];
  let sumX = 0;
  let sumY = 0;
  for (const [x, y] of points) {
    sumX += x;
    sumY += y;
  }
  return [sumX / points.length, sumY / points.length];
}

/** "4 points", "1 point" */
export function pointsLabel(count: number): string {
  return count === 1 ? '1 point' : `${count} points`;
}

export function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(2)}%`;
}

export function sortZones(zones: Zone[]): Zone[] {
  return zones.toSorted((a, b) => a.name.localeCompare(b.name));
}
