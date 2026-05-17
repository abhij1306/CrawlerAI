import { redirect } from 'next/navigation';

// Next.js App Router entrypoint for `/`; invoked by file-system routing.
export default function HomePage() {
  redirect('/login');
}
