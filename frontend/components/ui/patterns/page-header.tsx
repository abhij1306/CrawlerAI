import { Children, isValidElement, useEffectEvent, useLayoutEffect } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';

import { useTopBarStore } from '../../layout/top-bar-context';

function stableNodeSignature(value: ReactNode): string {
  if (value == null) return '';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableNodeSignature(entry)).join('|')}]`;
  }
  if (isValidElement(value)) {
    const props = (value.props ?? {}) as Record<string, unknown>;
    const typeName = stableElementTypeName(value.type);
    const propEntries = Object.entries(props)
      .reduce<string[]>((acc, [key, propValue]) => {
        if (key !== 'children' && key !== 'style' && typeof propValue !== 'function') {
          acc.push(`${key}:${stableNodeSignature(propValue as ReactNode)}`);
        }
        return acc;
      }, [])
      .sort((left, right) => left.localeCompare(right));
    return `<${typeName}${propEntries.length ? ` ${propEntries.join(',')}` : ''}>${stableNodeSignature(props.children as ReactNode)}</${typeName}>`;
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '[object]';
    }
  }
  return Children.toArray(value)
    .map((entry) => stableNodeSignature(entry))
    .join('|');
}

function stableElementTypeName(type: unknown): string {
  if (typeof type === 'string') return type;
  if (typeof type === 'symbol') return type.description ?? 'symbol';
  if (typeof type === 'function' || (typeof type === 'object' && type !== null)) {
    if ('displayName' in type && typeof type.displayName === 'string') {
      return type.displayName;
    }
    if ('name' in type && typeof type.name === 'string') {
      return type.name;
    }
  }
  return 'component';
}

export function PageHeader({
  title,
  description,
  actions,
}: Readonly<{
  title: ReactNode;
  description?: string;
  actions?: ReactNode;
}>) {
  const { setHeader } = useTopBarStore();
  const { pathname } = useLocation();
  const signature = `${stableNodeSignature(title)}::${description ?? ''}::${stableNodeSignature(actions)}`;
  const syncHeader = useEffectEvent(() => {
    setHeader({ pathKey: pathname, signature, title, description, actions });
  });
  useLayoutEffect(() => {
    syncHeader();
  }, [actions, pathname, signature, title]);
  return null;
}
