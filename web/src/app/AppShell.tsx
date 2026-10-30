import { useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { Chip } from '../components/Chip';
import { Icon, type IconName } from '../components/Icon';
import { formatShortDay } from '../lib/dates';
import { useAppData } from './AppDataContext';
import { useSelectedDay } from './SelectedDayContext';

// Versioned key: a later change of meaning gets a new key instead of misreading an old value.
export const DRAWER_STORAGE_KEY = 'askfootage:drawer-collapsed:v1';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(DRAWER_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(DRAWER_STORAGE_KEY, collapsed ? '1' : '0');
  } catch {
    // Storage blocked (private mode, policy): the drawer still works, it just is not remembered.
  }
}

interface NavEntry {
  to: string;
  label: string;
  /** Shown as the item's tooltip. */
  hint: string;
  icon: IconName;
}

// Order, names and hints as in the design reference.
const NAV: readonly NavEntry[] = [
  { to: '/', label: 'Find Footage', hint: 'Ask a question about your footage', icon: 'search' },
  { to: '/camera', label: 'Camera', hint: "Each day's recordings", icon: 'camera' },
  { to: '/zones', label: 'Zones', hint: 'Mark areas of the camera view', icon: 'zones' },
  { to: '/saved', label: 'Saved clips', hint: 'Clips you kept as evidence', icon: 'bookmark' },
];

const MAIN_ID = 'main-content';

function Topbar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { status } = useAppData();
  const { day } = useSelectedDay();
  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn"
        aria-label={collapsed ? 'Show menu names' : 'Hide menu names'}
        aria-expanded={!collapsed}
        aria-controls="app-drawer"
        onClick={onToggle}
      >
        <Icon name="menu" />
      </button>
      <Link to="/" className="topbar__brand">
        AskFootage
      </Link>
      <div className="topbar__date">
        {day ? <span>{formatShortDay(day)}</span> : null}
        {status?.demoMode ? <Chip>Demo data</Chip> : null}
      </div>
    </header>
  );
}

function Drawer({ collapsed }: { collapsed: boolean }) {
  return (
    <nav id="app-drawer" aria-label="Main" className={collapsed ? 'drawer drawer--collapsed' : 'drawer'}>
      <ul className="drawer__list">
        {NAV.map((entry) => (
          <li key={entry.to}>
            {/* NavLink sets aria-current="page" on the active item. */}
            <NavLink to={entry.to} end={entry.to === '/'} className="nav-item" title={entry.hint}>
              <Icon name={entry.icon} />
              {/* Collapsed: the name is hidden from sight but kept for screen readers. */}
              <span className={collapsed ? 'visually-hidden' : undefined}>{entry.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      {collapsed ? null : <p className="drawer__footer">Powered by Meta</p>}
    </nav>
  );
}

function ShellContent() {
  const { error, reload } = useAppData();
  if (error) {
    return (
      <div className="card notice stack" role="alert">
        <p>{error.message}</p>
        <p>
          <button type="button" className="btn" onClick={reload}>
            Try again
          </button>
        </p>
      </div>
    );
  }
  return <Outlet />;
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    writeCollapsed(next);
  }

  return (
    <div className="app">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <Topbar collapsed={collapsed} onToggle={toggle} />
      <div className="app__body">
        <Drawer collapsed={collapsed} />
        <main className="main" id={MAIN_ID} tabIndex={-1}>
          <div className="main__inner">
            <ShellContent />
          </div>
        </main>
      </div>
    </div>
  );
}
