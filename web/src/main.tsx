import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { createApiClient } from './api/client';
import { App } from './app/App';
import { applyTokens } from './styles/tokens';
import './styles/global.css';

applyTokens();

// Created once per page load, outside React, so re-renders never make a second client.
const client = createApiClient();

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root element');

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App client={client} />
    </BrowserRouter>
  </StrictMode>,
);
