import type { ComponentPropsWithoutRef, Ref } from 'react';

import { cn } from '../../lib/utils';

/** 32px control-height input; focus = --focus-ring via `.focus-ring`. */
export const inputClasses =
  'focus-ring h-[var(--control-height)] w-full rounded-sm border border-border bg-panel-strong px-2.5 text-base leading-normal text-foreground transition-[border-color,box-shadow] placeholder:text-subtle hover:border-border-strong focus:border-accent disabled:cursor-not-allowed disabled:opacity-50';

export const textareaClasses =
  'focus-ring min-h-[96px] w-full resize-y rounded-sm border border-border bg-panel-strong px-3 py-2 text-base leading-normal text-foreground transition-[border-color,box-shadow] placeholder:text-subtle hover:border-border-strong focus:border-accent disabled:cursor-not-allowed disabled:opacity-50';

export function Input({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'input'> & { ref?: Ref<HTMLInputElement> }>) {
  return <input ref={ref} className={cn(inputClasses, className)} {...props} />;
}

export function Textarea({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'textarea'> & { ref?: Ref<HTMLTextAreaElement> }>) {
  return <textarea ref={ref} className={cn(textareaClasses, className)} {...props} />;
}
export { inputClasses as inputVariants, textareaClasses as textareaVariants };
