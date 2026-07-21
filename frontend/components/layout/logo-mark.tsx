import { cn } from '../../lib/utils';

export function LogoMark({
  collapsed = false,
  auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
  const mark = (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center overflow-hidden bg-accent text-accent-fg',
        auth ? 'size-7 rounded-lg' : 'size-6 rounded-md',
      )}
    >
      <img
        src="/crawlerai-logo.svg"
        className="size-full object-cover"
        alt=""
        width={96}
        height={96}
        aria-hidden="true"
        draggable={false}
      />
    </div>
  );

  if (collapsed) {
    return <div className="flex w-full justify-center">{mark}</div>;
  }

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {mark}
      <span className="truncate text-[15px] leading-none font-semibold tracking-tight text-foreground">
        CrawlerAI
      </span>
    </div>
  );
}
