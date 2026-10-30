import { Link } from 'react-router-dom';

export function NotFoundScreen() {
  return (
    <div className="stack">
      <h1>Page not found</h1>
      <p className="muted">There is nothing at this address.</p>
      <p>
        <Link to="/">Go to Find Footage</Link>
      </p>
    </div>
  );
}
