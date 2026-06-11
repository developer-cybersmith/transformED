import { createClient } from '@/lib/supabase/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

// ---------------------------------------------------------------------------
// Base API client
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function getAuthHeader(): Promise<Record<string, string>> {
  const supabase = createClient()
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(
  method: string,
  path: string,
  options: {
    body?: unknown
    formData?: FormData
    headers?: Record<string, string>
  } = {},
): Promise<T> {
  const authHeader = await getAuthHeader()

  const headers: Record<string, string> = {
    ...authHeader,
    ...options.headers,
  }

  let body: BodyInit | undefined

  if (options.formData) {
    // Do NOT set Content-Type for FormData — browser sets multipart boundary automatically
    body = options.formData
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
  })

  if (!response.ok) {
    let errorBody: unknown
    try {
      errorBody = await response.json()
    } catch {
      errorBody = await response.text()
    }

    const message =
      typeof errorBody === 'object' &&
      errorBody !== null &&
      'detail' in errorBody
        ? String((errorBody as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`

    throw new ApiError(response.status, message, errorBody)
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T
  }

  return response.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const apiClient = {
  get<T>(path: string): Promise<T> {
    return request<T>('GET', path)
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('POST', path, { body })
  },

  postForm<T>(path: string, formData: FormData): Promise<T> {
    return request<T>('POST', path, { formData })
  },

  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('PATCH', path, { body })
  },

  delete<T>(path: string): Promise<T> {
    return request<T>('DELETE', path)
  },
}
