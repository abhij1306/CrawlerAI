import { apiClient } from '@/api/client';
import type { ApiRequestOptions } from '@/api/client';

import { strictValidate, userSchema } from './schemas';
import type { LoginResponse, User } from './types';

export const authApi = {
  register: async (email: string, password: string) => {
    const res = await apiClient.post<User>('/api/auth/register', { email, password });
    return strictValidate(userSchema, res, 'register');
  },
  login: async (email: string, password: string) => {
    const response = await apiClient.post<LoginResponse>('/api/auth/login', { email, password });
    if (response?.user) {
      response.user = strictValidate(userSchema, response.user, 'login');
    }
    return response;
  },
  me: async (options?: ApiRequestOptions) => {
    const res = await apiClient.get<User>('/api/auth/me', options);
    return strictValidate(userSchema, res, 'me');
  },
};
