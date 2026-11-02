/** Skeleton rows shaped like result cards: a quiet pulse instead of a spinner. The label is announced, the shapes are not. */
export function ClipListSkeleton({ label, count = 3 }: { label?: string; count?: number }) {
  return (
    <div>
      {label ? (
        <p className="visually-hidden" role="status">
          {label}
        </p>
      ) : null}
      <ul className="clip-list" aria-hidden="true">
        {Array.from({ length: count }, (_, index) => (
          <li key={index}>
            <div className="card clip-card">
              <span className="skeleton skeleton--poster" />
              <div className="clip-card__body">
                <span className="skeleton skeleton--line skeleton--short" />
                <span className="skeleton skeleton--title" />
                <span className="skeleton skeleton--line" />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Skeleton table rows (a table's own loading state). */
export function TableSkeletonRows({ columns, rows = 3 }: { columns: number; rows?: number }) {
  return Array.from({ length: rows }, (_, row) => (
    <tr key={row} aria-hidden="true">
      {Array.from({ length: columns }, (_, column) => (
        <td key={column}>
          <span className="skeleton skeleton--line" />
        </td>
      ))}
    </tr>
  ));
}
