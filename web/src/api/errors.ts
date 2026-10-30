import type { ErrorBody } from './generated/types';

/** An error from the API (or from reaching it), carrying the contract's stable code. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export const NETWORK_ERROR_MESSAGE = 'Could not reach the server. Check that it is running, then try again.';

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const detail = (value as { error?: unknown }).error;
  if (typeof detail !== 'object' || detail === null) return false;
  const { code, message } = detail as { code?: unknown; message?: unknown };
  return typeof code === 'string' && typeof message === 'string';
}

/** Builds an ApiError from a failed response, falling back to a generic message when the body is not the standard one. */
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (isErrorBody(body)) {
    return new ApiError(response.status, body.error.code, body.error.message);
  }
  const code = response.status >= 500 ? 'internal_error' : 'http_error';
  return new ApiError(response.status, code, `The server could not answer (HTTP ${response.status}). Try again.`);
}

/** Turns anything thrown into a message that is safe to show. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Try again.';
}
