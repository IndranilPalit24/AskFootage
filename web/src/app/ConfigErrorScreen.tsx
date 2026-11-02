import { DemoDisclosure } from '../components/DemoDisclosure';
import { EmptyState } from '../components/EmptyState';
import { usePageTitle } from '../hooks/usePageTitle';

/** Shown instead of the app when no API is chosen: an actionable message, never a quiet fallback to fake data. */
export function ConfigErrorScreen({ reason }: { reason: string }) {
  usePageTitle('API not configured');
  return (
    <main className="config-error">
      <EmptyState headingLevel={1} tone="error" title="AskFootage has no API to talk to">
        {reason} Start the API with .\.venv\Scripts\python.exe -m scripts.run_demo, then start the web app with
        cd web; $env:VITE_API_URL=&apos;http://localhost:8000&apos;; npm run dev. To look at the screens with made-up data and no footage,
        set VITE_API_MODE=mock instead.
      </EmptyState>
      <DemoDisclosure />
    </main>
  );
}
