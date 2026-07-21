import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { FormEvent, useState } from 'react';

import { AUTH_SESSION_QUERY_KEY } from '../../components/layout/auth-session-query';
import { InlineAlert } from '../../components/ui/patterns';
import { Button, Field, Input, Subtitle, Title } from '../../components/ui/primitives';
import { api } from '../../lib/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
      const response = await api.login(email, password);
      queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, response.user);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="space-y-3">
        <Title kicker="Auth">Sign in</Title>
        <Subtitle>Use your crawler workspace credentials.</Subtitle>
      </div>
      <form className="mt-6 grid gap-3.5" onSubmit={onSubmit}>
        <Field label="Email">
          <Input
            type="email"
            value={email}
            onChange={(event) => {
              setError('');
              setEmail(event.target.value);
            }}
            placeholder="name@company.com"
            className="h-[var(--control-height-lg)]"
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
            className="h-[var(--control-height-lg)]"
            required
          />
        </Field>
        {error ? <InlineAlert message={error} /> : null}
        <div className="pt-2">
          <Button type="submit" size="lg" className="w-full text-sm" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </div>
      </form>
    </div>
  );
}
