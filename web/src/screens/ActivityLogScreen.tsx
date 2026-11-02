import { useMemo, useState } from 'react';
import { Icon } from '../components/Icon';
import { ACTIVITY_ACTIONS, ACTIVITY_BANNER, SAMPLE_ACTIVITY_LOG } from '../features/activity/sampleActivity';
import { usePageTitle } from '../hooks/usePageTitle';
import { formatFullDay } from '../lib/dates';

const ALL = '';
const USERS = [...new Set(SAMPLE_ACTIVITY_LOG.map((entry) => entry.user))].toSorted();

/**
 * PROPOSED page. The app records no activity, so every row comes from SAMPLE_ACTIVITY_LOG and the banner says
 * so. The banner takes no props and has no close button: it cannot be hidden.
 */
export function ActivityLogScreen() {
  usePageTitle('Activity Log (sample data)');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [user, setUser] = useState(ALL);
  const [action, setAction] = useState(ALL);

  const rows = useMemo(
    () =>
      SAMPLE_ACTIVITY_LOG.filter(
        (entry) =>
          (from === '' || entry.day >= from) &&
          (to === '' || entry.day <= to) &&
          (user === ALL || entry.user === user) &&
          (action === ALL || entry.action === action),
      ),
    [from, to, user, action],
  );

  return (
    <div className="screen--wide">
      <div className="page-head">
        <h1>Activity Log</h1>
      </div>
      <p className="banner" role="note" data-testid="activity-banner">
        {ACTIVITY_BANNER}
      </p>
      <form className="filters" aria-label="Filter the sample log" onSubmit={(event) => event.preventDefault()}>
        <div className="filters__range">
          <label className="visually-hidden" htmlFor="activity-from">
            From date
          </label>
          <input id="activity-from" type="date" className="input" value={from} onChange={(event) => setFrom(event.target.value)} />
          <Icon name="arrowRight" size={16} />
          <label className="visually-hidden" htmlFor="activity-to">
            To date
          </label>
          <input id="activity-to" type="date" className="input" value={to} onChange={(event) => setTo(event.target.value)} />
        </div>
        <label className="visually-hidden" htmlFor="activity-user">
          User
        </label>
        <select id="activity-user" className="select" value={user} onChange={(event) => setUser(event.target.value)}>
          <option value={ALL}>All users</option>
          {USERS.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <label className="visually-hidden" htmlFor="activity-action">
          Action
        </label>
        <select id="activity-action" className="select" value={action} onChange={(event) => setAction(event.target.value)}>
          <option value={ALL}>All actions</option>
          {ACTIVITY_ACTIONS.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <div className="filters__export">
          <button type="button" className="btn" disabled aria-describedby="export-note">
            Export log
          </button>
          <span id="export-note" className="muted small">
            Proposed
          </span>
        </div>
      </form>
      <div className="table-wrap">
        <table className="table table--activity">
          <caption className="visually-hidden">Sample activity, not recorded</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">User</th>
              <th scope="col">Action</th>
              <th scope="col">Camera / clip</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((entry) => (
              <tr key={entry.id}>
                <td className="num">
                  {formatFullDay(entry.day)}, {entry.time}
                </td>
                <td>{entry.user}</td>
                <td>{entry.action}</td>
                <td>{entry.target}</td>
                <td>{entry.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? <p className="muted">No sample entries match these filters.</p> : null}
    </div>
  );
}
