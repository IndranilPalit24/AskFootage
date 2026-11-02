import { Link } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
import { usePageTitle } from '../hooks/usePageTitle';

export function NotFoundScreen() {
  usePageTitle('Page not found');
  return (
    <EmptyState
      headingLevel={1}
      title="Page not found"
      action={
        <Link to="/" className="btn btn--primary">
          Go to Find Footage
        </Link>
      }
    >
      There is nothing at this address. Check the link, or start from Find Footage and ask about a day.
    </EmptyState>
  );
}
