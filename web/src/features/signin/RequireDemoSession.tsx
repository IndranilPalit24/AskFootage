import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useDemoSession } from './demoSession';

/**
 * The route guard: app routes need the demo session, otherwise the visitor is sent to /sign-in and brought back
 * to the page they asked for. A UI convenience only; the API behind these screens is not authenticated.
 */
export function RequireDemoSession() {
  const entered = useDemoSession();
  const location = useLocation();
  if (!entered) {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/sign-in" replace state={{ from }} />;
  }
  return <Outlet />;
}
