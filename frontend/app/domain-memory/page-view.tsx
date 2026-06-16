import { DomainMemoryContent } from '../../components/selectors/domain-memory/domain-memory-content';
import { useDomainMemoryWorkspace } from '../../components/selectors/domain-memory/use-domain-memory-workspace';

export default function DomainMemoryPage() {
  const controller = useDomainMemoryWorkspace();
  return <DomainMemoryContent controller={controller} />;
}
