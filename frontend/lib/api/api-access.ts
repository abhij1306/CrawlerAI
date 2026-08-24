import { apiClient } from '@/api/client';

export type ApiKeyRecord = {
  id: number;
  name: string;
  key_prefix: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
};

export type ApiKeyCreated = ApiKeyRecord & { api_key: string };

export type PublicApiCapabilities = {
  version: string;
  surfaces: string[];
  tools: string[];
  deferred: string[];
  deployment: string;
  mcp: {
    default_transport: string;
    network_scope: string;
    hosted: boolean;
  };
};

type PublicApiCapabilitiesResponse = {
  status: 'ok';
  data: PublicApiCapabilities;
};

export const apiAccessApi = {
  listKeys: () => apiClient.get<ApiKeyRecord[]>('/api/api-keys'),
  createKey: (name: string) => apiClient.post<ApiKeyCreated>('/api/api-keys', { name }),
  // Deletes the key outright — the server responds 204 with no body.
  deleteKey: (keyId: number) => apiClient.delete<void>(`/api/api-keys/${keyId}`),
  getCapabilities: async (apiKey: string) => {
    const response = await apiClient.get<PublicApiCapabilitiesResponse>('/api/v1/capabilities', {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    return response.data;
  },
};
