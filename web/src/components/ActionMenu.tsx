import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

export interface MenuAction {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

interface ActionMenuProps {
  /** What the menu is for, as its accessible name ("Actions for Loading Bay 1"). */
  label: string;
  /** The trigger button's content, and the class that styles it. */
  trigger: ReactNode;
  triggerClassName: string;
  /** Names the trigger when its content is only an icon. */
  triggerLabel?: string;
  items: readonly MenuAction[];
  /** The menu opens to the right edge of the trigger (default) or the left. */
  align?: 'right' | 'left';
}

/**
 * A button that opens a menu: Enter, Space or the Down arrow opens it, the arrow keys move, Home and End jump,
 * Escape closes and returns to the button, and a click outside closes it. Items are real buttons with role menuitem.
 */
export function ActionMenu({ label, trigger, triggerClassName, triggerLabel, items, align = 'right' }: ActionMenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return undefined;
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const away = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  function entries(): HTMLElement[] {
    return [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!open) return;
    const list = entries();
    const at = list.indexOf(document.activeElement as HTMLElement);
    let target: HTMLElement | undefined;
    switch (event.key) {
      case 'Escape':
        event.preventDefault();
        setOpen(false);
        button.current?.focus();
        return;
      case 'Tab':
        setOpen(false);
        return;
      case 'ArrowDown':
        target = list[(at + 1) % list.length];
        break;
      case 'ArrowUp':
        target = list[(at - 1 + list.length) % list.length];
        break;
      case 'Home':
        target = list[0];
        break;
      case 'End':
        target = list[list.length - 1];
        break;
      default:
        return;
    }
    event.preventDefault();
    target?.focus();
  }

  return (
    <div className="menu-root" ref={root} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        className={triggerClassName}
        aria-label={triggerLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {trigger}
      </button>
      {open ? (
        <div id={menuId} ref={menu} role="menu" aria-label={label} className={align === 'right' ? 'menu' : 'menu menu--left'}>
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              className={item.danger ? 'menu__item menu__item--danger' : 'menu__item'}
              onClick={() => {
                setOpen(false);
                button.current?.focus();
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
