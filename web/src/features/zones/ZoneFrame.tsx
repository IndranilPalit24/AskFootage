import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { Point, Zone } from '../../api/generated/types';
import { labelPosition, normalisedPoint, nudge, percent, svgPoints } from './geometry';

const STEP = 0.01;
const BIG_STEP = 0.05;
const CENTRE: Point = [0.5, 0.5];

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

interface ZoneFrameProps {
  zones: Zone[];
  /** e.g. "Loading dock · still frame" */
  caption: string;
  drawing: boolean;
  /** The zone being drawn, in click order. */
  draft: Point[];
  onAddPoint: (point: Point) => void;
  /** id of the text that explains how to draw (mouse and keyboard). */
  instructionsId: string;
}

/**
 * The still-frame placeholder with an SVG overlay (viewBox 0 0 1 1, stretched to the frame) that shows the
 * saved zones and the zone being drawn. While drawing, a click adds a point; so does Enter, at a cursor the
 * arrow keys move, so drawing works without a mouse.
 */
export function ZoneFrame({ zones, caption, drawing, draft, onAddPoint, instructionsId }: ZoneFrameProps) {
  const [cursor, setCursor] = useState<Point | null>(null);

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    // Measured against the frame itself (not whichever child was hit), so this equals offsetX / width.
    const rect = event.currentTarget.getBoundingClientRect();
    const point = normalisedPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    if (point) onAddPoint(point);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const arrow = ARROWS[event.key];
    if (arrow) {
      event.preventDefault();
      const step = event.shiftKey ? BIG_STEP : STEP;
      setCursor((current) => nudge(current ?? CENTRE, arrow[0] * step, arrow[1] * step));
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const point = cursor ?? CENTRE;
      setCursor(point);
      onAddPoint(point);
    }
  }

  const zoneNames = zones.map((zone) => zone.name).join(', ');
  const frameLabel = drawing
    ? `Drawing area, ${draft.length === 1 ? '1 point' : `${draft.length} points`} placed`
    : `${caption}${zones.length > 0 ? ` with zones: ${zoneNames}` : ', no zones yet'}`;

  return (
    <div
      className={drawing ? 'frame frame--drawing' : 'frame'}
      data-testid="zone-frame"
      role={drawing ? 'application' : 'img'}
      aria-label={frameLabel}
      aria-describedby={drawing ? instructionsId : undefined}
      tabIndex={drawing ? 0 : undefined}
      onClick={drawing ? handleClick : undefined}
      onKeyDown={drawing ? handleKeyDown : undefined}
    >
      <span className="frame__caption" aria-hidden="true">
        {caption}
      </span>
      <svg className="frame__overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        {zones.map((zone) => (
          <polygon
            key={zone.id}
            className="frame__zone"
            points={svgPoints(zone.points)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {draft.length >= 3 ? (
          <polygon className="frame__draft" points={svgPoints(draft)} vectorEffect="non-scaling-stroke" />
        ) : null}
        {draft.length === 2 ? (
          <polyline className="frame__draft frame__draft--open" points={svgPoints(draft)} vectorEffect="non-scaling-stroke" />
        ) : null}
      </svg>
      {zones.map((zone) => {
        const [x, y] = labelPosition(zone.points);
        return (
          <span key={zone.id} className="frame__label" style={{ left: percent(x), top: percent(y) }} aria-hidden="true">
            {zone.name}
          </span>
        );
      })}
      {draft.map(([x, y], index) => (
        <span
          key={`${index}-${x}-${y}`}
          className="frame__point"
          data-testid="draft-point"
          style={{ left: percent(x), top: percent(y) }}
          aria-hidden="true"
        />
      ))}
      {drawing && cursor ? (
        <span className="frame__cursor" style={{ left: percent(cursor[0]), top: percent(cursor[1]) }} aria-hidden="true" />
      ) : null}
    </div>
  );
}
