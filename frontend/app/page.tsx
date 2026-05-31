import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Invoro',
  description: 'AI commerce intelligence and structured extraction platform.',
};

// Next.js App Router entrypoint for `/`; invoked by file-system routing.
export default function HomePage() {
  redirect('/login');
}
