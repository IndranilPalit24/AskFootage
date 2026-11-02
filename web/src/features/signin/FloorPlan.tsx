/**
 * An abstract factory floor plan, drawn as thin lines: outer wall with a notch and door swings, racking, a central
 * production line with machine blocks and a robot arm, a conveyor loop, a dashed travel path, small rooms and a
 * staircase. Decoration only: no labels, no people, no footage, no real place, so it is hidden from assistive technology.
 */

/** A rack: an outlined block with evenly spaced shelf lines across it. */
function Rack({ x, y, w, h, vertical = false, lines = 8 }: { x: number; y: number; w: number; h: number; vertical?: boolean; lines?: number }) {
  const steps = Array.from({ length: lines - 1 }, (_, index) => (index + 1) / lines);
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} />
      {steps.map((step) =>
        vertical ? (
          <path key={step} d={`M${x + w * step} ${y}V${y + h}`} />
        ) : (
          <path key={step} d={`M${x} ${y + h * step}H${x + w}`} />
        ),
      )}
    </g>
  );
}

export function FloorPlan() {
  const wall = 'var(--color-text)';
  const blue = 'var(--color-plan-blue)';
  return (
    <svg className="signin__plan" viewBox="0 0 520 420" fill="none" aria-hidden="true" focusable="false">
      {/* Outer wall: a notch at the top left, a door gap on the right and one at the bottom, each with its swing. */}
      <g stroke={wall} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 44H92V12H512V222M512 262V404H462M440 404H6V44" />
        <path d="M512 222a26 26 0 0 0-22 18" strokeWidth="1" />
        <path d="M440 404v-18" strokeWidth="1" />
        <path d="M518 316h10v-24h-10" strokeWidth="1" />
        <path d="M118 8h26v8h-26z" strokeWidth="1" />
      </g>

      {/* Racking: top left, down the right edge, a pair by the lower aisle. */}
      <g stroke={wall} strokeWidth="1" strokeLinejoin="round">
        <Rack x={470} y={22} w={36} h={118} lines={14} />
        <Rack x={470} y={286} w={36} h={110} lines={14} />
        <Rack x={26} y={64} w={46} h={58} vertical lines={7} />
        <Rack x={252} y={314} w={50} h={46} vertical lines={6} />
        <rect x="150" y="14" width="30" height="32" />
        <rect x="372" y="14" width="30" height="32" />
      </g>

      {/* Central production line: a long bench, machine blocks and a robot arm. */}
      <g stroke={wall} strokeWidth="1.25" strokeLinejoin="round">
        <rect x="112" y="76" width="168" height="40" />
        <rect x="124" y="84" width="22" height="24" />
        <rect x="154" y="84" width="12" height="24" />
        <rect x="170" y="84" width="12" height="24" />
        <rect x="186" y="84" width="12" height="24" />
        <rect x="262" y="48" width="38" height="32" />
        <circle cx="281" cy="64" r="8" />
        <path d="M281 56v-8M281 72v10M273 64h-8M289 64h8" strokeWidth="1" />
        <rect x="150" y="256" width="150" height="44" />
        <rect x="162" y="266" width="22" height="24" />
        <circle cx="173" cy="278" r="6" />
        <rect x="196" y="264" width="10" height="28" />
        <rect x="212" y="264" width="10" height="28" />
        <rect x="232" y="262" width="52" height="32" />
        <circle cx="258" cy="278" r="9" />
        <path d="M258 269v-9M267 278h8" strokeWidth="1" />
      </g>

      {/* Machine cell by the left wall. */}
      <g stroke={wall} strokeWidth="1" strokeLinejoin="round">
        <rect x="44" y="222" width="50" height="16" />
        <rect x="70" y="208" width="28" height="44" />
        <circle cx="84" cy="230" r="7" />
        <rect x="6" y="236" width="26" height="40" />
      </g>

      {/* Conveyor loop on the right: two rails with rungs, and a pallet at its foot. */}
      <g stroke={blue} strokeWidth="1.25" strokeLinejoin="round">
        <rect x="364" y="86" width="40" height="190" rx="3" />
        <path d="M372 94V268M396 94V268" />
        <path d="M372 108H396M372 120H396M372 132H396M372 144H396M372 156H396M372 168H396M372 180H396M372 192H396M372 204H396M372 216H396M372 228H396M372 240H396M372 252H396" strokeWidth="0.75" />
        <rect x="370" y="286" width="28" height="30" />
        <path d="M370 296H398M370 306H398" strokeWidth="0.75" />
        <path d="M318 112c0 14 6 30 20 30h22" />
        <path d="M318 112V150c0 14 8 22 22 22" strokeWidth="0.75" />
      </g>

      {/* Travel path: dashed, looping the central line, with arrowheads. */}
      <g stroke={blue} strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">
        <path d="M244 38H312a24 24 0 0 1 24 24V306a24 24 0 0 1-24 24H134a24 24 0 0 1-24-24V292" strokeDasharray="5 5" />
        <path d="M110 292C110 270 88 262 70 262" strokeDasharray="5 5" />
        <path d="M244 38H170a8 8 0 0 0-8 8v6" strokeDasharray="5 5" />
        <path d="M252 33l-9 5 9 5" />
        <path d="M268 70l7-5-1 9z" strokeWidth="0.75" />
        <path d="M105 285l5 9 5-9" />
        <path d="M455 408l-9-6v12z" strokeWidth="0.75" />
      </g>

      {/* Small rooms, bottom left: a vehicle in the first, a desk cluster in the second. */}
      <g stroke={wall} strokeWidth="1.5" strokeLinejoin="round">
        <path d="M6 330H92V404" />
        <path d="M104 330H202V404M104 330V404" />
        <path d="M202 330h24v74" strokeWidth="1" />
      </g>
      <g stroke={wall} strokeWidth="1" strokeLinejoin="round">
        <rect x="34" y="350" width="30" height="40" rx="5" />
        <rect x="40" y="358" width="18" height="12" />
        <path d="M30 356h4M30 384h4M64 356h4M64 384h4" strokeWidth="2" />
        <rect x="116" y="346" width="26" height="18" />
        <rect x="150" y="342" width="26" height="22" />
        <rect x="156" y="372" width="20" height="14" />
        <circle cx="126" cy="384" r="7" />
        <circle cx="140" cy="376" r="5" />
        <path d="M164 342v-6h8v6" />
      </g>

      {/* Staircase between the rooms and the floor. */}
      <g stroke={wall} strokeWidth="1" strokeLinejoin="round">
        <rect x="208" y="330" width="34" height="68" />
        <path d="M208 340H242M208 350H242M208 360H242M208 370H242M208 380H242" />
        <path d="M208 398H266V382H242" />
      </g>
      <path d="M180 330a18 18 0 0 0 18 18" stroke={blue} strokeWidth="1" />
    </svg>
  );
}
