import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  /** What happened and what to do about it, in a sentence or two. */
  children?: ReactNode;
  /** The one helpful action: a link or a button. */
  action?: ReactNode;
  /** An error is announced at once; anything else is a quiet note. */
  tone?: 'info' | 'error';
  /** 1 when the state is the whole screen (it carries the page title); 2 inside a screen. */
  headingLevel?: 1 | 2;
}

/** An empty, failed or not-found state: a title, a sentence, one action. Never an empty box. */
export function EmptyState({ title, children, action, tone = 'info', headingLevel = 2 }: EmptyStateProps) {
  const Heading = headingLevel === 1 ? 'h1' : 'h2';
  return (
    <div className="empty" role={tone === 'error' ? 'alert' : undefined}>
      <Heading className="empty__title">{title}</Heading>
      {children ? <p className="empty__text">{children}</p> : null}
      {action ? <div className="empty__action">{action}</div> : null}
    </div>
  );
}
