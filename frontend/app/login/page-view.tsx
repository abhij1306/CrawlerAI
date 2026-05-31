'use client';

// Next.js App Router entrypoint for `/login`; invoked by file-system routing.
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

import { InlineAlert } from '../../components/ui/patterns';
import { Button, Field, Input, Subtitle, Title } from '../../components/ui/primitives';
import { api } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      setError('');
      await api.login(email, password);
      router.replace('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Title kicker="Auth">Sign in</Title>
        <Subtitle>Use your crawler workspace credentials.</Subtitle>
      </div>
      <form className="grid gap-4" onSubmit={onSubmit}>
        <Field label="Email">
          <Input
            type="email"
            value={email}
            onChange={(event) => {
              setError('');
              setEmail(event.target.value);
            }}
            placeholder="name@company.com"
            required
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            value={password}
            onChange={(event) => {
              setError('');
              setPassword(event.target.value);
            }}
            placeholder="••••••••"
            required
          />
        </Field>
        {error ? <InlineAlert message={error} /> : null}
        <div className="pt-2">
          <Button type="submit" size="lg" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </div>
      </form>
    </div>
  );
}
