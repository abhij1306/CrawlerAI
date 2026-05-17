'use client';

import { DomainMemoryContent } from './domain-memory/domain-memory-content';
import { useDomainMemoryWorkspace } from './domain-memory/use-domain-memory-workspace';

export default function DomainMemoryManagePage() {
  const controller = useDomainMemoryWorkspace();
  return <DomainMemoryContent controller={controller} />;
}
