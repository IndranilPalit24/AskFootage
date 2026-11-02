import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { createApiClient } from './api/client';
import { resolveApiChoice } from './api/mode';
import { ConfigErrorScreen } from './app/ConfigErrorScreen';
import { App } from './app/App';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import { applyTokens } from './styles/tokens';
import './styles/global.css';

applyTokens();

// Chosen once per page load, outside React, so re-renders never make a second client. No API configured: say so.
const choice = resolveApiChoice(import.meta.env);
const client = choice.kind === 'unconfigured' ? null : createApiClient(choice);

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root element');

createRoot(container).render(
  <StrictMode>
    {choice.kind === 'unconfigured' || client === null ? (
      <ConfigErrorScreen reason={choice.kind === 'unconfigured' ? choice.reason : ''} />
    ) : (
      <BrowserRouter>
        <App client={client} mock={choice.kind === 'mock'} />
      </BrowserRouter>
    )}
  </StrictMode>,
);
