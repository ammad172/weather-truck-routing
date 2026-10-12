import type { Place, PlanRequest, PlanResponse } from './types'

export class ApiError extends Error {}

export const OFFLINE_MESSAGE = "Couldn't reach the server. Check your connection and try again."

export async function geocode(query: string, signal?: AbortSignal): Promise<Place[]> {
  const response = await send(`/api/geocode?q=${encodeURIComponent(query)}`, { signal })
  const body = await readJson(response)
  return (body as { results: Place[] }).results
}

export async function plan(request: PlanRequest): Promise<PlanResponse> {
  const response = await send('/api/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return (await readJson(response)) as PlanResponse
}

/** fetch, with a readable message when the request never got a response (offline, connection dropped). */
async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error // a superseded autosuggest query
    throw new ApiError(OFFLINE_MESSAGE)
  }
}

async function readJson(response: Response): Promise<unknown> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Not JSON (e.g. a proxy error page); fall through to the status-based message.
  }
  if (!response.ok) throw new ApiError(errorMessage(response.status, body))
  return body
}

/** DRF errors are either {"detail": "..."} or {"field": ["...", ...]}. */
function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    if ('detail' in body && typeof body.detail === 'string') return body.detail
    const fields = Object.entries(body as Record<string, unknown>).flatMap(([field, value]) =>
      (Array.isArray(value) ? value : [value]).map((message) => `${FIELD_NAMES[field] ?? field}: ${String(message)}`),
    )
    if (fields.length) return fields.join(' ')
  }
  return status >= 500 ? 'The server had a problem. Please try again.' : `Request failed (${status}).`
}

const FIELD_NAMES: Record<string, string> = {
  origin: 'From',
  destination: 'To',
  departure: 'Departure',
  weight_lb: 'Load',
  interval_mi: 'Checkpoint interval',
}
