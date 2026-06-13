import { lazy, Suspense } from 'react';
import type { ComponentType, ReactNode } from 'react';

type DynamicOptions = {
  loading?: () => ReactNode;
  ssr?: boolean;
};

type DynamicLoader<P> = () => Promise<{ default: ComponentType<P> } | ComponentType<P>>;

export default function dynamic<P extends object>(
  loader: DynamicLoader<P>,
  options: DynamicOptions = {},
) {
  const LazyComponent = lazy(async () => {
    const loaded = await loader();
    return typeof loaded === 'function' ? { default: loaded } : loaded;
  });

  function DynamicComponent(props: P) {
    return (
      <Suspense fallback={options.loading ? options.loading() : null}>
        <LazyComponent {...props} />
      </Suspense>
    );
  }

  return DynamicComponent;
}
