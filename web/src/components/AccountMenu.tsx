import { useNavigate } from 'react-router-dom';
import { clearDemoSession, useDemoSession } from '../features/signin/demoSession';
import { ActionMenu } from './ActionMenu';
import { Icon } from './Icon';

/**
 * The one account control in the top bar: "Demo session" with a menu holding "Sign out". It exists only while a
 * demo session does. It names no person and no role: the demo has no accounts.
 */
export function AccountMenu() {
  const active = useDemoSession();
  const navigate = useNavigate();
  if (!active) return null;

  function signOut() {
    clearDemoSession();
    // replace: the Back button must not return to an app page.
    navigate('/sign-in', { replace: true });
  }

  return (
    <ActionMenu
      label="Demo session"
      triggerClassName="btn account__trigger"
      trigger={
        <>
          <Icon name="session" size={16} />
          Demo session
          <Icon name="chevronDown" size={16} />
        </>
      }
      items={[{ label: 'Sign out', onSelect: signOut }]}
    />
  );
}
