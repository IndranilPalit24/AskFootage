/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the AskFootage API, e.g. http://localhost:8000. Unset: the in-memory demo client. Never a secret. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
