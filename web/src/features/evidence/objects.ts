import type { Evidence } from '../../api/generated/types';

/**
 * Neutral object labels implied by the evidence: carrying -> person, box; in_zone and dwell -> person.
 * Labels only ever name a kind of object, never who someone is.
 */
export function objectsFromEvidence(evidence: Evidence[]): string[] {
  const objects = new Set<string>();
  for (const item of evidence) {
    objects.add('person');
    if (item.kind === 'carrying') objects.add('box');
  }
  return [...objects];
}
