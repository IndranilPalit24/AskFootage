// The /sign-in page, the demo session and the route guard. AskFootage has no authentication: the session is a
// UI-only flag, and "sso" is copy only.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NETWORK_ERROR_MESSAGE } from '../../web/src/api/errors';
import { MockApiClient } from '../../web/src/api/mockClient';
import { App } from '../../web/src/app/App';
import packageJson from '../../web/package.json';
import { AUTH_MODE, AUTH_MODES } from '../../web/src/features/signin/authMode';
import { DEMO_DISABLED_HINT, DEMO_INFO, SIGN_IN_COPY, SSO_COPY } from '../../web/src/features/signin/copy';
import { clearDemoSession, hasDemoSession, startDemoSession } from '../../web/src/features/signin/demoSession';
import { SignInContent } from '../../web/src/features/signin/SignInScreen';
import signInCss from '../../web/src/styles/signin.css?raw';
import authModeSource from '../../web/src/features/signin/authMode.ts?raw';
import screenSource from '../../web/src/features/signin/SignInScreen.tsx?raw';
import { renderApp } from './ui-test-utils';

afterEach(() => vi.unstubAllEnvs());

/** A made-up code for these tests only: the mock client accepts a code only when a test hands it one. */
const TEST_CODE = '246810';

/** The signed-out page at a path, on a mock client that accepts TEST_CODE. */
function signedOut(path = '/sign-in') {
  return renderApp(path, new MockApiClient({ demoCodes: [TEST_CODE] }), { session: false });
}

/** Opens the code entry from the SSO button, types a code and submits. */
function enterCode(code: string) {
  fireEvent.click(screen.getByRole('button', { name: 'Continue with company SSO' }));
  fireEvent.change(screen.getByLabelText('Demo access code'), { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
}

describe('AUTH_MODE', () => {
  it('is "demo", and "sso" exists only as copy', () => {
    expect(AUTH_MODES).toEqual(['demo', 'sso']);
    expect(AUTH_MODE).toBe('demo');
  });

  it('cannot be switched at runtime: not from the address, storage or the environment', () => {
    expect(authModeSource).not.toMatch(/import\.meta|localStorage|sessionStorage|location|URLSearchParams|process\.env/);
    expect(screenSource).not.toMatch(/useSearchParams|URLSearchParams|localStorage|import\.meta/);
    vi.stubEnv('VITE_AUTH_MODE', 'sso');
    window.localStorage.setItem('authMode', 'sso');
    window.sessionStorage.setItem('authMode', 'sso');
    signedOut('/sign-in?mode=sso&authMode=sso');
    expect(screen.queryByText(SSO_COPY.mfa)).toBeNull();
    expect(screen.queryByText(/Need access\./)).toBeNull();
    expect(screen.getByText(DEMO_INFO.mfa)).toBeTruthy();
    window.sessionStorage.removeItem('authMode');
  });
});

describe('/sign-in in demo mode', () => {
  it('renders every specified string, one h1 and the landmarks', () => {
    signedOut();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
    for (const text of [
      'Use your organization account to continue.',
      'Find the moment.',
      'Review the evidence.',
      'Secure access to recorded footage for your operations team.',
      'or',
      DEMO_INFO.mfa,
      'Contact your factory administrator',
      'AskFootage',
      'Continue with Microsoft',
      'Continue with company SSO',
    ]) {
      expect(screen.getAllByText(text, { exact: true }).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'About AskFootage' })).toBeTruthy();
    expect(screen.getByRole('contentinfo')).toBeTruthy();
    expect(document.title).toBe('Sign in · AskFootage');
  });

  it('shows the two demo lines exactly, with a cobalt link to /security and no email', () => {
    signedOut();
    // CHANGED on purpose (was: the long "Enter the demo access code..." note, and the sso lines hidden).
    expect(screen.getByText('Multi Factor Authentication is managed by your organization')).toBeTruthy();
    const link = screen.getByRole('link', { name: 'Contact your factory administrator' });
    expect(link.getAttribute('href')).toBe('/security');
    expect(link.textContent).toBe('Contact your factory administrator');
    expect(link.parentElement!.textContent).toBe('Need Access? Contact your factory administrator');
    expect(document.body.textContent).not.toMatch(/@|Enter the demo access code you were given/);
    expect(screen.queryByText(SSO_COPY.mfa)).toBeNull();
  });

  it('the Microsoft button is disabled and explained by a hidden description; clicking it does nothing', () => {
    signedOut();
    const note = screen.getByText(DEMO_DISABLED_HINT);
    expect(note.classList.contains('visually-hidden')).toBe(true);
    const button = screen.getByRole('button', { name: 'Continue with Microsoft' });
    expect(button.getAttribute('aria-disabled')).toBe('true');
    expect(button.getAttribute('aria-describedby')).toBe(note.id);
    fireEvent.click(button);
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
    expect(screen.queryByLabelText('Demo access code')).toBeNull();
    expect(hasDemoSession()).toBe(false);
  });

  it('there is no demo-continue button anywhere', () => {
    signedOut();
    expect(screen.queryByText(/continue to demo/i)).toBeNull();
    expect(Object.values(SIGN_IN_COPY).join(' ')).not.toMatch(/continue to demo/i);
  });

  it('the SSO button is enabled and opens a labelled 6-digit code entry; Escape and Cancel go back', async () => {
    signedOut();
    const sso = screen.getByRole('button', { name: 'Continue with company SSO' });
    expect(sso.getAttribute('aria-disabled')).toBeNull();
    fireEvent.click(sso);
    const input = screen.getByLabelText('Demo access code') as HTMLInputElement;
    expect(input.type).toBe('text');
    expect(input.getAttribute('inputmode')).toBe('numeric');
    expect(input.getAttribute('autocomplete')).toBe('one-time-code');
    expect(input.maxLength).toBe(6);
    expect(document.activeElement).toBe(input);
    expect(document.querySelector('[type="password"]')).toBeNull();
    // Digits only, at most 6.
    fireEvent.change(input, { target: { value: '12ab34567890' } });
    expect(input.value).toBe('123456');
    // Escape returns to the buttons, with focus back on the SSO button.
    fireEvent.keyDown(input, { key: 'Escape' });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Continue with company SSO' })));
    expect(screen.queryByLabelText('Demo access code')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Continue with company SSO' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('Demo access code')).toBeNull();
    expect(screen.getByRole('button', { name: 'Continue with Microsoft' })).toBeTruthy();
  });

  it('a right code creates the session and lands on Find Footage', async () => {
    signedOut();
    expect(hasDemoSession()).toBe(false);
    enterCode(TEST_CODE);
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(hasDemoSession()).toBe(true);
    expect(window.sessionStorage.length).toBe(1);
    // Only the flag is stored, never the code.
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(TEST_CODE);
    expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
  });

  it('a wrong code shows a calm error, empties the field and makes no session', async () => {
    signedOut();
    enterCode('135790');
    expect((await screen.findByRole('alert')).textContent).toBe('That code is not valid.');
    expect((screen.getByLabelText('Demo access code') as HTMLInputElement).value).toBe('');
    expect(document.activeElement).toBe(screen.getByLabelText('Demo access code'));
    expect(hasDemoSession()).toBe(false);
  });

  it('too few digits is caught before asking the server', async () => {
    const client = new MockApiClient({ demoCodes: [TEST_CODE] });
    const spy = vi.spyOn(client, 'checkDemoCode');
    renderApp('/sign-in', client, { session: false });
    enterCode('123');
    expect((await screen.findByRole('alert')).textContent).toBe('Enter all 6 digits.');
    expect(spy).not.toHaveBeenCalled();
  });

  it('too many attempts and a network failure each get their own calm message', async () => {
    for (const [error, message] of [
      [new ApiError(429, 'too_many_attempts', 'Too many attempts.'), 'Too many attempts. Wait a minute, then try again.'],
      [new ApiError(0, 'network_error', NETWORK_ERROR_MESSAGE), 'Could not check the code. Try again.'],
    ] as const) {
      const client = new MockApiClient();
      vi.spyOn(client, 'checkDemoCode').mockRejectedValue(error);
      const { unmount } = renderApp('/sign-in', client, { session: false });
      enterCode('123456');
      expect((await screen.findByRole('alert')).textContent).toBe(message);
      expect(hasDemoSession()).toBe(false);
      unmount();
    }
  });

  it('the code is never logged', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) => vi.spyOn(console, name).mockImplementation(() => undefined));
    signedOut();
    enterCode('135790');
    await screen.findByRole('alert');
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain('135790');
    vi.restoreAllMocks();
  });

  it('the buttons are 56px tall (also on a phone), above the 48px minimum', () => {
    expect(signInCss).toMatch(/\.signin__btn \{[^}]*min-height: 56px/);
    expect(signInCss).toMatch(/\.signin__btn \{\s*min-height: 56px/);
  });

  it('has no password, e-mail or other field, no image, and shows no footage, camera or user details', () => {
    const { container } = signedOut();
    expect(container.querySelector('input, textarea, select, form, img, video')).toBeNull();
    expect(container.querySelector('[type="password"]')).toBeNull();
    expect(screen.queryByText(/password|e-?mail|username|CAM-\d/i)).toBeNull();
  });

  it('draws the floor plan as hidden decoration with no text, and carries no third-party logo or model name', () => {
    const { container } = signedOut();
    const plan = container.querySelector('svg.signin__plan')!;
    expect(plan.getAttribute('aria-hidden')).toBe('true');
    expect(plan.textContent).toBe('');
    expect(container.innerHTML).not.toMatch(/<image|href="http|<title|logo/i);
    expect(container.querySelectorAll('svg:not([aria-hidden="true"])')).toHaveLength(0);
    expect(container.textContent).not.toMatch(/claude|gpt|gemini|openai|anthropic|\bmeta\b|\bsam\b|microsoft logo/i);
    // The Microsoft button carries a neutral line icon, drawn in one colour.
    const icon = screen.getByRole('button', { name: 'Continue with Microsoft' }).querySelector('svg')!;
    expect(icon.innerHTML).not.toMatch(/#[0-9a-f]{3,6}|rgb/i);
  });

  it('the version comes from package.json; Privacy and Security are real links to public pages', () => {
    signedOut();
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText(`v${packageJson.version}`)).toBeTruthy();
    expect(within(footer).getByRole('link', { name: 'Privacy' }).getAttribute('href')).toBe('/privacy');
    expect(within(footer).getByRole('link', { name: 'Security' }).getAttribute('href')).toBe('/security');
    expect(screenSource).not.toMatch(/['"]1\.0\.0['"]|v1\.0/);
  });

  it('tab order: skip link, Microsoft (disabled but reachable), SSO, the administrator link, Privacy, Security', () => {
    const { container } = signedOut();
    const order = [...container.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')]
      .filter((element) => element.tabIndex >= 0)
      .map((element) => element.textContent?.trim());
    expect(order).toEqual(['Skip to content', 'Continue with Microsoft', 'Continue with company SSO', 'Contact your factory administrator', 'Privacy', 'Security']);
  });

  it('works from the keyboard: real buttons, and Enter in the field submits the form', async () => {
    signedOut();
    const sso = screen.getByRole('button', { name: 'Continue with company SSO' });
    sso.focus();
    expect(document.activeElement).toBe(sso);
    expect(sso.getAttribute('type')).toBe('button');
    fireEvent.click(sso); // the browser turns Enter and Space on a button into this click
    const input = screen.getByLabelText('Demo access code');
    fireEvent.change(input, { target: { value: TEST_CODE } });
    fireEvent.submit(input.closest('form')!); // Enter in the field
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
  });
});

describe('the "sso" copy (never reached by the running app)', () => {
  it('shows the multi-factor and access lines, and no code entry or note', () => {
    render(
      <MemoryRouter>
        <SignInContent mode="sso" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Multi-factor authentication is managed by your organization.')).toBeTruthy();
    expect(screen.getByText(SSO_COPY.accessLink).textContent).toBe('Contact your factory administrator.');
    expect(screen.getByText(SSO_COPY.accessLink).parentElement!.textContent).toBe('Need access? Contact your factory administrator.');
    expect(screen.queryByText(DEMO_DISABLED_HINT)).toBeNull();
    for (const name of [SIGN_IN_COPY.microsoftButton, SIGN_IN_COPY.ssoButton]) {
      expect(screen.getByRole('button', { name }).getAttribute('type')).toBe('button');
    }
  });
});

describe('the route guard', () => {
  it('app routes without a session redirect to /sign-in', async () => {
    for (const path of ['/', '/cameras', '/zones', '/saved', '/activity', '/clip/clip-1029-104215', '/nowhere']) {
      const { unmount } = signedOut(path);
      expect(await screen.findByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
      unmount();
    }
  });

  it('with a session, /sign-in goes to Find Footage', async () => {
    renderApp('/sign-in');
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
  });

  it('a direct link to an app route works after the demo starts, and returns to that path', async () => {
    signedOut('/cameras');
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
    enterCode(TEST_CODE);
    expect(await screen.findByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
  });

  it('/welcome, /privacy and /security stay public', async () => {
    for (const [path, heading] of [
      ['/privacy', 'Privacy'],
      ['/security', 'Security'],
    ] as const) {
      const { unmount } = signedOut(path);
      expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeTruthy();
      expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
      unmount();
    }
    signedOut('/welcome');
    expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
    expect(document.querySelector('.welcome')).toBeTruthy();
  });

  it('clearing the session sends an open app page back to /sign-in', async () => {
    renderApp('/cameras');
    expect(await screen.findByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    clearDemoSession();
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
  });

  it('an outside address cannot be used as the return path', async () => {
    clearDemoSession();
    render(
      <MemoryRouter initialEntries={[{ pathname: '/sign-in', state: { from: '//evil.example/x' } }]}>
        <App client={new MockApiClient({ demoCodes: [TEST_CODE] })} />
      </MemoryRouter>,
    );
    enterCode(TEST_CODE);
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
  });
});

describe('the demo session', () => {
  it('lives in sessionStorage, is cleared by clearDemoSession, and is not security', () => {
    clearDemoSession();
    expect(hasDemoSession()).toBe(false);
    startDemoSession();
    expect(hasDemoSession()).toBe(true);
    expect(window.sessionStorage.length).toBe(1);
    clearDemoSession();
    expect(hasDemoSession()).toBe(false);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('a storage that throws does not crash: an in-memory flag takes over', async () => {
    clearDemoSession();
    const broken = () => {
      throw new Error('storage blocked');
    };
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(broken);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(broken);
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(broken);
    try {
      expect(hasDemoSession()).toBe(false);
      startDemoSession();
      expect(hasDemoSession()).toBe(true);
      clearDemoSession();
      expect(hasDemoSession()).toBe(false);
      signedOut();
      expect(screen.getByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
      enterCode(TEST_CODE);
      await waitFor(() => expect(hasDemoSession()).toBe(true));
    } finally {
      vi.restoreAllMocks();
    }
  });
});
