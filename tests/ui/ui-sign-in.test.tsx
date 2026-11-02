// The /sign-in page. AskFootage has no authentication: the page never starts a session, and "sso" is copy only.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import packageJson from '../../web/package.json';
import { MockApiClient } from '../../web/src/api/mockClient';
import { App } from '../../web/src/app/App';
import { MemoryRouter } from 'react-router-dom';
import { AUTH_MODE, AUTH_MODES } from '../../web/src/features/signin/authMode';
import { DEMO_NOTE, SIGN_IN_COPY, SSO_COPY } from '../../web/src/features/signin/copy';
import { SignInContent, SignInScreen } from '../../web/src/features/signin/SignInScreen';
import authModeSource from '../../web/src/features/signin/authMode.ts?raw';
import screenSource from '../../web/src/features/signin/SignInScreen.tsx?raw';
import { renderApp } from './ui-test-utils';

afterEach(() => vi.unstubAllEnvs());

function openSignIn(path = '/sign-in') {
  return renderApp(path);
}

describe('AUTH_MODE', () => {
  it('is "demo", and "sso" exists only as copy', () => {
    expect(AUTH_MODES).toEqual(['demo', 'sso']);
    expect(AUTH_MODE).toBe('demo');
  });

  it('cannot be switched at runtime: not from the address, storage or the environment', () => {
    // The constant is not read from anywhere, and the screen takes no mode from outside.
    expect(authModeSource).not.toMatch(/import\.meta|localStorage|sessionStorage|location|URLSearchParams|process\.env/);
    expect(screenSource).not.toMatch(/useSearchParams|URLSearchParams|localStorage|sessionStorage|import\.meta/);
    vi.stubEnv('VITE_AUTH_MODE', 'sso');
    window.localStorage.setItem('authMode', 'sso');
    renderApp('/sign-in?mode=sso&authMode=sso');
    expect(screen.queryByText(SSO_COPY.mfa)).toBeNull();
    expect(screen.getByText(DEMO_NOTE)).toBeTruthy();
    window.localStorage.removeItem('authMode');
  });
});

describe('/sign-in in demo mode', () => {
  it('renders every specified string, one h1 and the landmarks', () => {
    openSignIn();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in to AskFootage' })).toBeTruthy();
    for (const text of [
      'Use your organization account to continue.',
      'Find the moment.',
      'Review the evidence.',
      'Secure access to recorded footage for your operations team.',
      'or',
      'Need access? Contact your factory administrator.',
      'Single sign-on is not configured in this build.',
      'AskFootage',
    ]) {
      expect(screen.getAllByText(text, { exact: true }).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'About AskFootage' })).toBeTruthy();
    expect(screen.getByRole('contentinfo')).toBeTruthy();
    expect(document.title).toBe('Sign in · AskFootage');
  });

  it('shows the two sign-in methods disabled and explained by the note, and hides the multi-factor line', () => {
    openSignIn();
    const note = screen.getByText(DEMO_NOTE);
    for (const name of ['Continue with Microsoft', 'Continue with company SSO']) {
      const button = screen.getByRole('button', { name });
      expect(button.getAttribute('aria-disabled')).toBe('true');
      expect(button.getAttribute('aria-describedby')).toBe(note.id);
      fireEvent.click(button); // does nothing: no navigation, no error
    }
    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy();
    expect(screen.queryByText(SSO_COPY.mfa)).toBeNull();
    expect(screen.queryByText(/multi-factor/i)).toBeNull();
  });

  it('"Continue to demo" goes to the existing Find Footage screen', async () => {
    openSignIn();
    const demo = screen.getByRole('link', { name: 'Continue to demo' });
    expect(demo.className).toContain('btn--primary');
    fireEvent.click(demo);
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
  });

  it('has no password or e-mail field, no image, and shows no footage, camera or user details', () => {
    const { container } = openSignIn();
    expect(container.querySelector('input, textarea, select, form, img')).toBeNull();
    expect(screen.queryByText(/password|e-?mail|username|CAM-\d/i)).toBeNull();
    expect(container.querySelector('video')).toBeNull();
  });

  it('draws the floor plan as hidden decoration with no text, and carries no third-party logo or model name', () => {
    const { container } = openSignIn();
    const plan = container.querySelector('svg.signin__plan')!;
    expect(plan.getAttribute('aria-hidden')).toBe('true');
    expect(plan.textContent).toBe('');
    expect(container.innerHTML).not.toMatch(/<image|href="http|<title|logo/i);
    expect(container.textContent).not.toMatch(/claude|gpt|gemini|openai|anthropic|\bmeta\b|\bsam\b/i);
  });

  it('the version comes from package.json, Privacy is a real link, Security is plain text', () => {
    openSignIn();
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText(`v${packageJson.version}`)).toBeTruthy();
    expect(within(footer).getByRole('link', { name: 'Privacy' }).getAttribute('href')).toBe('/welcome#privacy');
    expect(within(footer).getByText('Security').closest('a')).toBeNull();
    expect(within(footer).getAllByRole('link')).toHaveLength(1);
  });

  it('tab order (document order of what can take focus): skip link, Continue to demo, the two disabled methods, Privacy', () => {
    const { container } = openSignIn();
    const order = [...container.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')]
      .filter((element) => element.tabIndex >= 0)
      .map((element) => element.textContent?.trim());
    expect(order).toEqual(['Skip to content', 'Continue to demo', 'Continue with Microsoft', 'Continue with company SSO', 'Privacy']);
  });
});

describe('the "sso" copy', () => {
  it('shows the multi-factor line and no demo button or note (copy only; nothing is wired)', () => {
    render(
      <MemoryRouter>
        <SignInContent mode="sso" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Multi-factor authentication is managed by your organization.')).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Continue to demo' })).toBeNull();
    expect(screen.queryByText(DEMO_NOTE)).toBeNull();
    for (const name of [SIGN_IN_COPY.microsoftButton, SIGN_IN_COPY.ssoButton]) {
      expect(screen.getByRole('button', { name }).getAttribute('type')).toBe('button');
    }
  });

  it('SignInScreen always uses the constant', () => {
    render(
      <MemoryRouter>
        <SignInScreen />
      </MemoryRouter>,
    );
    expect(screen.queryByText(SSO_COPY.mfa)).toBeNull();
  });
});

describe('nothing else changed', () => {
  it('existing routes still render and none redirects to /sign-in', async () => {
    for (const [path, heading] of [
      ['/', 'Find Footage'],
      ['/cameras', 'Cameras'],
      ['/zones', 'Zones'],
      ['/saved', 'Saved clips'],
      ['/nowhere', 'Page not found'],
    ] as const) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[path]}>
          <App client={new MockApiClient()} />
        </MemoryRouter>,
      );
      expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeTruthy();
      expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
      unmount();
    }
    renderApp('/welcome');
    expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
  });
});
