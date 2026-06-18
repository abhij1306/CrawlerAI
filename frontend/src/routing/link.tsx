import type { AnchorHTMLAttributes, ReactNode } from 'react';
import { Link as RouterLink, useInRouterContext } from 'react-router-dom';

export type Route = string;

type AppLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & {
  href: string;
  children?: ReactNode;
};

function isExternalHref(href: string) {
  return /^(https?:|mailto:|tel:)/.test(href);
}

export function Link({ href, children, ...props }: Readonly<AppLinkProps>) {
  const inRouter = useInRouterContext();
  if (isExternalHref(href) || !inRouter) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  }

  return (
    <RouterLink to={href} {...props}>
      {children}
    </RouterLink>
  );
}

export default Link;
