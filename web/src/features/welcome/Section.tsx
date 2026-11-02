import type { ReactNode } from 'react';

interface SectionProps {
  id: string;
  title: string;
  lead?: string;
  /** Light grey band behind the section, to separate it from its neighbours. */
  tinted?: boolean;
  children: ReactNode;
}

/** One landing section: a labelled region with its heading, an optional lead line, and its content. */
export function Section({ id, title, lead, tinted = false, children }: SectionProps) {
  return (
    <section
      id={id}
      className={tinted ? 'welcome-section welcome-section--tinted' : 'welcome-section'}
      aria-labelledby={`${id}-title`}
    >
      <div className="welcome-wrap">
        <h2 id={`${id}-title`}>{title}</h2>
        {lead ? <p className="welcome-lead">{lead}</p> : null}
        {children}
      </div>
    </section>
  );
}
