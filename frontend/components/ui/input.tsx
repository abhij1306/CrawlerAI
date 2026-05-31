'use client';

import type { ComponentPropsWithoutRef } from 'react';

import { cn } from '../../lib/utils';
import { inputVariants, textareaVariants } from './input-variants';

export function Input(props: ComponentPropsWithoutRef<'input'>) {
  const normalizedProps =
    props.type === 'file'
      ? props
      : 'value' in props
        ? { ...props, value: props.value ?? '' }
        : props;

  return <input {...normalizedProps} className={cn(inputVariants, normalizedProps.className)} />;
}

export function Textarea(props: ComponentPropsWithoutRef<'textarea'>) {
  const normalizedProps = 'value' in props ? { ...props, value: props.value ?? '' } : props;

  return (
    <textarea {...normalizedProps} className={cn(textareaVariants, normalizedProps.className)} />
  );
}
