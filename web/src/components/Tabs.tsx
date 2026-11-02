import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react';

export interface TabDef {
  id: string;
  label: string;
  panel: ReactNode;
}

interface TabsProps {
  label: string;
  tabs: readonly TabDef[];
  selected: string;
  onSelect: (id: string) => void;
}

/**
 * Tabs with the WAI-ARIA keyboard pattern: only the selected tab is in the Tab order, and the arrow keys, Home and
 * End move between tabs. Every panel stays mounted (the others are hidden) so a half-filled form is kept.
 */
export function Tabs({ label, tabs, selected, onSelect }: TabsProps) {
  const base = useId();
  const buttons = useRef(new Map<string, HTMLButtonElement>());

  function move(index: number) {
    const target = tabs[(index + tabs.length) % tabs.length];
    onSelect(target.id);
    buttons.current.get(target.id)?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    switch (event.key) {
      case 'ArrowRight':
        move(index + 1);
        break;
      case 'ArrowLeft':
        move(index - 1);
        break;
      case 'Home':
        move(0);
        break;
      case 'End':
        move(tabs.length - 1);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  return (
    <>
      <div className="tabs" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(element) => {
              if (element) buttons.current.set(tab.id, element);
              else buttons.current.delete(tab.id);
            }}
            type="button"
            role="tab"
            id={`${base}-tab-${tab.id}`}
            className="tabs__tab"
            aria-selected={tab.id === selected}
            aria-controls={`${base}-panel-${tab.id}`}
            tabIndex={tab.id === selected ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`${base}-panel-${tab.id}`}
          aria-labelledby={`${base}-tab-${tab.id}`}
          hidden={tab.id !== selected}
        >
          {tab.panel}
        </div>
      ))}
    </>
  );
}
