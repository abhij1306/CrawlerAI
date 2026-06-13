import type { ImgHTMLAttributes } from 'react';

type AppImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> & {
  src: string;
  fill?: boolean;
  priority?: boolean;
  unoptimized?: boolean;
};

export default function Image({
  fill,
  priority: _priority,
  unoptimized: _unoptimized,
  style,
  ...props
}: Readonly<AppImageProps>) {
  const fillStyle = fill
    ? ({
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover',
      } as const)
    : undefined;

  return <img {...props} style={{ ...fillStyle, ...style }} />;
}
