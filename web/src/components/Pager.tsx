import { useState } from 'react';

/** Rows shown at once in a long table. */
export const PAGE_SIZE = 50;

export interface Paging<T> {
  /** The rows of the current page. */
  rows: readonly T[];
  page: number;
  pageCount: number;
  total: number;
  /** 1-based first and last row shown. */
  from: number;
  to: number;
  setPage: (page: number) => void;
}

/**
 * Pages a list. Going to another list (another day or camera) starts again at page 1; the page never points
 * past the end when the list shrinks.
 */
export function usePaging<T>(items: readonly T[], pageSize = PAGE_SIZE): Paging<T> {
  const [state, setState] = useState<{ list: readonly T[]; page: number }>({ list: items, page: 0 });
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  let page = state.page;
  if (state.list !== items) {
    // A different list: derive the reset while rendering, not in an effect, so there is no flash of the old page.
    page = 0;
    setState({ list: items, page: 0 });
  }
  page = Math.min(page, pageCount - 1);
  const start = page * pageSize;
  return {
    rows: items.slice(start, start + pageSize),
    page,
    pageCount,
    total: items.length,
    from: items.length === 0 ? 0 : start + 1,
    to: Math.min(start + pageSize, items.length),
    setPage: (next) => setState({ list: items, page: Math.min(Math.max(next, 0), pageCount - 1) }),
  };
}

/**
 * Previous / Next under a long table, with the range shown. Not rendered when everything fits on one page.
 * Real buttons: keyboard and screen reader friendly; the range is announced when it changes.
 */
export function Pager({ paging, noun }: { paging: Paging<unknown>; noun: string }) {
  if (paging.pageCount <= 1) return null;
  return (
    <nav className="pager" aria-label={`${noun} pages`}>
      <p className="pager__range" aria-live="polite">
        Showing {paging.from}–{paging.to} of {paging.total} {noun}
      </p>
      <div className="btn-row">
        <button type="button" className="btn btn--sm" aria-disabled={paging.page === 0 || undefined} onClick={() => paging.page > 0 && paging.setPage(paging.page - 1)}>
          Previous page
        </button>
        <span className="pager__page">
          Page {paging.page + 1} of {paging.pageCount}
        </span>
        <button
          type="button"
          className="btn btn--sm"
          aria-disabled={paging.page >= paging.pageCount - 1 || undefined}
          onClick={() => paging.page < paging.pageCount - 1 && paging.setPage(paging.page + 1)}
        >
          Next page
        </button>
      </div>
    </nav>
  );
}
