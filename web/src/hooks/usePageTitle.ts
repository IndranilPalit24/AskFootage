import { useEffect } from 'react';

const PRODUCT = 'AskFootage';

/**
 * Sets the browser tab title for a screen: "Cameras · AskFootage". null is just the product name; undefined
 * leaves whatever a child screen set (so a parent can name only the states it renders itself).
 */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (title === undefined) return;
    document.title = title ? `${title} · ${PRODUCT}` : PRODUCT;
  }, [title]);
}
