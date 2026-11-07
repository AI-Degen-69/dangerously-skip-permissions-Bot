import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { Activity, Company, Contact, Deal, Me, Overview, StoredFile, Task } from '../../shared/types'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...rest,
    headers: {
      accept: 'application/json',
      ...(json !== undefined ? { 'content-type': 'application/json' } : {}),
      ...(rest.headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!response.ok) {
    let message = response.statusText
    let code: string | undefined
    try {
      const body = (await response.json()) as { error?: string; message?: string }
      message = body.message ?? body.error ?? message
      code = body.error
    } catch {
      /* no body */
    }
    throw new ApiError(response.status, message, code)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// Queries

export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me'), retry: false, staleTime: 60_000 })
export const useOverview = () => useQuery({ queryKey: ['overview'], queryFn: () => api<Overview>('/overview') })

export interface ContactsQuery {
  q?: string
  status?: string
  companyId?: string
  sort?: 'activity' | 'name'
  page?: number
}
export const useContacts = (query: ContactsQuery) =>
  useQuery({
    queryKey: ['contacts', query],
    queryFn: () => {
      const params = new URLSearchParams()
      if (query.q) params.set('q', query.q)
      if (query.status) params.set('status', query.status)
      if (query.companyId) params.set('companyId', query.companyId)
      if (query.sort) params.set('sort', query.sort)
      if (query.page) params.set('page', String(query.page))
      return api<{ items: Contact[]; total: number; page: number; pageSize: number }>(`/contacts?${params}`)
    },
    placeholderData: (previous) => previous,
  })

export const useContact = (id: string | undefined) =>
  useQuery({
    queryKey: ['contact', id],
    queryFn: () => api<{ contact: Contact; activities: Activity[]; deals: Deal[]; files: StoredFile[] }>(`/contacts/${id}`),
    enabled: Boolean(id),
  })

export const useCompanies = (q = '') =>
  useQuery({
    queryKey: ['companies', q],
    queryFn: () => api<{ items: Company[] }>(`/companies?q=${encodeURIComponent(q)}`),
    placeholderData: (previous) => previous,
  })

export const useCompany = (id: string | undefined) =>
  useQuery({
    queryKey: ['company', id],
    queryFn: () => api<{ company: Company; contacts: Contact[]; deals: Deal[]; activities: Activity[] }>(`/companies/${id}`),
    enabled: Boolean(id),
  })

export const useDeals = () => useQuery({ queryKey: ['deals'], queryFn: () => api<{ items: Deal[] }>('/deals') })
export const useDeal = (id: string | null) =>
  useQuery({
    queryKey: ['deal', id],
    queryFn: () => api<{ deal: Deal; activities: Activity[]; files: StoredFile[] }>(`/deals/${id}`),
    enabled: Boolean(id),
  })
export const useTasks = () => useQuery({ queryKey: ['tasks'], queryFn: () => api<{ items: Task[] }>('/tasks') })

export const useSearch = (q: string) =>
  useQuery({
    queryKey: ['search', q],
    queryFn: () =>
      api<{
        contacts: { id: string; name: string; email: string | null; hue: number }[]
        companies: { id: string; name: string; domain: string | null; hue: number }[]
        deals: { id: string; title: string; stage: string; value: number }[]
      }>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length > 0,
    staleTime: 10_000,
  })

// Mutations. Each invalidates the lists it can affect; detail pages refetch
// through their own keys.

export function useInvalidate() {
  const client = useQueryClient()
  return (...keys: string[]) => Promise.all(keys.map((key) => client.invalidateQueries({ queryKey: [key] })))
}

export function useApiMutation<TInput, TResult>(
  run: (input: TInput) => Promise<TResult>,
  invalidates: string[],
  options?: { onSuccess?: (result: TResult, input: TInput) => void },
) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: run,
    onSuccess: async (result, input) => {
      await invalidate(...invalidates)
      options?.onSuccess?.(result, input)
    },
  })
}

export async function uploadFile(
  file: File,
  target: { contactId?: string; dealId?: string; companyId?: string },
): Promise<StoredFile> {
  const form = new FormData()
  form.set('file', file)
  if (target.contactId) form.set('contactId', target.contactId)
  if (target.dealId) form.set('dealId', target.dealId)
  if (target.companyId) form.set('companyId', target.companyId)
  const result = await api<{ file: StoredFile }>('/files', { method: 'POST', body: form })
  return result.file
}

export async function uploadAvatar(contactId: string, file: File): Promise<string> {
  const form = new FormData()
  form.set('file', file)
  const result = await api<{ avatarKey: string }>(`/files/avatar/${contactId}`, { method: 'PUT', body: form })
  return result.avatarKey
}
