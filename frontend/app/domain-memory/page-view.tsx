import { DomainMemoryContent } from '../../components/domain-memory/domain-memory-content';
import { useDomainMemoryWorkspace } from '../../components/domain-memory/use-domain-memory-workspace';

export default function DomainMemoryPage() {
  const controller = useDomainMemoryWorkspace();
  return <DomainMemoryContent controller={controller} />;
}
