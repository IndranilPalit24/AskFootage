import { Link } from 'react-router-dom';
import { DEMO_PATH } from './content';

/**
 * "Try the demo": a link to Find Footage. Primary (accent) on white, or the plain white button on the
 * navy bands, where the accent would be 2.4:1 against the background.
 */
export function DemoLink({ onNavy = false }: { onNavy?: boolean }) {
  return (
    <Link to={DEMO_PATH} className={onNavy ? 'btn' : 'btn btn--primary'}>
      Try the demo
    </Link>
  );
}
