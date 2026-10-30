import type { Evidence } from '../../api/generated/types';
import { Chip } from '../../components/Chip';

export function EvidenceChips({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <ul className="chip-list" aria-label="Evidence">
      {evidence.map((item, index) => (
        <li key={`${item.kind}-${index}`}>
          <Chip tone="accent">{item.text}</Chip>
        </li>
      ))}
    </ul>
  );
}
