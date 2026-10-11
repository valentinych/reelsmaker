export type MediaFile = {
  id: string
  path: string
  name: string
  size: number
  kind: string | null
  /** Probed video length (seconds); null/undefined for images or unknown. */
  duration_sec?: number | null
  /** Inclusive clip window for reel render (seconds). Defaults: 0 … duration_sec. */
  trim_start?: number | null
  trim_end?: number | null
  /** Server preview URL under /reel/api/media/file */
  url?: string | null
}

export type TextBlock = {
  text: string
  start_time: number
  duration: number
  position: string
  font_size: number
}

export type JobStatus = {
  id: string
  status: 'pending' | 'running' | 'done' | 'error' | string
  progress: number
  message: string
  error: string | null
  result_url: string | null
}

export type AppTab = 'watermark' | 'static'

export type AppState = {
  session_id: string
  tab: AppTab
  youtube_url: string
  music_start: number
  music_end: number | null
  fit_percent: number
  reals_photo_duration: number
  reals_wm_position: string
  reals_wm_scale: number
  reals_wm_opacity: number
  reals_opening_enabled: boolean
  reals_opening_duration: number
  reals_credits_enabled: boolean
  reals_credits_duration: number
  reals_text_blocks: TextBlock[]
  reals_media: MediaFile[]
  reals_watermark: MediaFile | null
  static_slide_duration: number
  static_media: MediaFile[]
}

const LS_KEY = 'realsmaker_v1'

export function defaultState(): AppState {
  const sid = localStorage.getItem('realsmaker_session') || ''
  return {
    session_id: sid,
    tab: 'watermark',
    youtube_url: '',
    music_start: 0,
    music_end: null,
    fit_percent: 98,
    reals_photo_duration: 3,
    reals_wm_position: 'bottom_right',
    reals_wm_scale: 22,
    reals_wm_opacity: 92,
    reals_opening_enabled: false,
    reals_opening_duration: 2,
    reals_credits_enabled: false,
    reals_credits_duration: 3,
    reals_text_blocks: [],
    reals_media: [],
    reals_watermark: null,
    static_slide_duration: 3,
    static_media: [],
  }
}

export function loadLocal(): AppState {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return defaultState()
    const merged = { ...defaultState(), ...JSON.parse(raw) } as AppState
    const sid = merged.session_id || ''
    return {
      ...merged,
      reals_media: reviveMediaList(merged.reals_media, sid),
      static_media: reviveMediaList(merged.static_media, sid),
      reals_watermark: merged.reals_watermark
        ? withPreviewUrl(merged.reals_watermark, sid)
        : null,
    }
  } catch {
    return defaultState()
  }
}

export function saveLocal(state: AppState) {
  localStorage.setItem(LS_KEY, JSON.stringify(state))
  if (state.session_id) localStorage.setItem('realsmaker_session', state.session_id)
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json() as Promise<T>
}

export async function uploadFiles(
  files: FileList | File[],
  sessionId: string,
  subdir = 'reals',
) {
  const fd = new FormData()
  fd.append('session_id', sessionId)
  fd.append('subdir', subdir)
  for (const f of Array.from(files)) fd.append('files', f)
  return api<{ session_id: string; files: MediaFile[] }>('/reel/api/media', {
    method: 'POST',
    body: fd,
  })
}

export async function createJob(body: Record<string, unknown>) {
  return api<{ job_id: string } & JobStatus>('/reel/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function getJob(id: string) {
  return api<JobStatus>(`/reel/api/jobs/${id}`)
}

export async function saveDraft(state: AppState) {
  return api<{ ok: boolean; session_id: string; name: string }>('/reel/api/drafts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.session_id, state }),
  })
}

export async function listDrafts() {
  return api<{ drafts: { name: string; label: string; path: string }[] }>(
    '/reel/api/drafts',
  )
}

export async function loadDraft(name: string) {
  return api<Record<string, unknown>>(`/reel/api/drafts/${encodeURIComponent(name)}`)
}

export async function fetchMeta() {
  return api<{
    wm_positions: Record<string, string>
    corner_positions: Record<string, string>
  }>('/reel/api/meta')
}

function withPreviewUrl(file: MediaFile, sessionId: string): MediaFile {
  if (!file.path || !sessionId) return file
  const q = new URLSearchParams({
    session_id: sessionId,
    path: file.path,
  })
  return { ...file, url: `/reel/api/media/file?${q.toString()}` }
}

function reviveMediaList(list: MediaFile[] | undefined, sessionId: string): MediaFile[] {
  if (!list?.length) return list || []
  return list.map((m) => withPreviewUrl(m, sessionId))
}

/** HEAD (or tiny GET) against /reel/api/media/file — false if cleaned up / missing. */
export async function mediaFileExists(sessionId: string, path: string): Promise<boolean> {
  if (!sessionId || !path) return false
  const q = new URLSearchParams({ session_id: sessionId, path })
  const url = `/reel/api/media/file?${q.toString()}`
  try {
    const head = await fetch(url, { method: 'HEAD' })
    if (head.ok) return true
    if (head.status !== 405 && head.status !== 501) return false
    const get = await fetch(url, { method: 'GET', headers: { Range: 'bytes=0-0' } })
    return get.ok
  } catch {
    return false
  }
}

/** Drop media descriptors whose files no longer exist under the session tmp dir. */
export async function pruneMissingMedia(
  state: AppState,
): Promise<{ state: AppState; dropped: string[] }> {
  const sid = state.session_id
  const dropped: string[] = []

  async function keep(list: MediaFile[]): Promise<MediaFile[]> {
    if (!list.length) return []
    if (!sid) {
      for (const m of list) dropped.push(m.name || m.path)
      return []
    }
    const out: MediaFile[] = []
    for (const m of list) {
      const ok = await mediaFileExists(sid, m.path)
      if (ok) out.push(withPreviewUrl(m, sid))
      else dropped.push(m.name || basename(m.path))
    }
    return out
  }

  const reals_media = await keep(state.reals_media)
  const static_media = await keep(state.static_media)
  let reals_watermark = state.reals_watermark
  if (reals_watermark) {
    const ok = sid ? await mediaFileExists(sid, reals_watermark.path) : false
    if (ok) reals_watermark = withPreviewUrl(reals_watermark, sid)
    else {
      dropped.push(reals_watermark.name || 'watermark')
      reals_watermark = null
    }
  }

  return {
    state: { ...state, reals_media, static_media, reals_watermark },
    dropped,
  }
}

function basename(p: string): string {
  const parts = p.split(/[/\\]/)
  return parts[parts.length - 1] || p
}

export function applySnapshot(data: Record<string, unknown>, prev: AppState): AppState {
  const reals = (data.reals || {}) as Record<string, unknown>
  const staticSnap = (data.static || {}) as Record<string, unknown>
  const session_id = String(data.session_id || prev.session_id || '')
  return {
    ...prev,
    session_id,
    youtube_url: String(data.youtube_url ?? prev.youtube_url),
    music_start: Number(data.music_start ?? prev.music_start),
    music_end: (data.music_end as number | null) ?? prev.music_end,
    fit_percent: Number(data.fit_percent ?? prev.fit_percent),
    reals_photo_duration: Number(reals.photo_duration ?? prev.reals_photo_duration),
    reals_wm_position: String(reals.wm_position ?? prev.reals_wm_position),
    reals_wm_scale: Number(reals.wm_scale ?? prev.reals_wm_scale),
    reals_wm_opacity: Number(reals.wm_opacity ?? prev.reals_wm_opacity),
    reals_opening_enabled: Boolean(reals.opening_enabled ?? prev.reals_opening_enabled),
    reals_opening_duration: Number(reals.opening_duration ?? prev.reals_opening_duration),
    reals_credits_enabled: Boolean(reals.credits_enabled ?? prev.reals_credits_enabled),
    reals_credits_duration: Number(reals.credits_duration ?? prev.reals_credits_duration),
    reals_text_blocks: (reals.text_blocks as TextBlock[]) || prev.reals_text_blocks,
    reals_media: reviveMediaList((reals.media as MediaFile[]) || prev.reals_media, session_id),
    reals_watermark: (() => {
      const wm = (reals.watermark as MediaFile | null) ?? prev.reals_watermark
      return wm ? withPreviewUrl(wm, session_id) : null
    })(),
    static_slide_duration: Number(staticSnap.slide_duration ?? prev.static_slide_duration),
    static_media: reviveMediaList(
      (staticSnap.media as MediaFile[]) || prev.static_media,
      session_id,
    ),
  }
}
