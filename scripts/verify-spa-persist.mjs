#!/usr/bin/env node
/**
 * Smoke-check append + persistence against a running RealsMaker API.
 * Usage: node scripts/verify-spa-persist.mjs [baseUrl]
 * Default baseUrl: http://127.0.0.1:8770
 */
import { createHash } from 'node:crypto'

const base = (process.argv[2] || 'http://127.0.0.1:8770').replace(/\/$/, '')

function tinyPng() {
  const b64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
  return Buffer.from(b64, 'base64')
}

async function upload(sessionId, files, subdir = 'reals') {
  const fd = new FormData()
  fd.append('session_id', sessionId || '')
  fd.append('subdir', subdir)
  for (const [name, buf] of files) {
    fd.append('files', new Blob([buf], { type: 'image/png' }), name)
  }
  const res = await fetch(`${base}/reel/api/media`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(`upload ${res.status}: ${await res.text()}`)
  return res.json()
}

async function mediaExists(sessionId, path) {
  const q = new URLSearchParams({ session_id: sessionId, path })
  const url = `${base}/reel/api/media/file?${q}`
  const head = await fetch(url, { method: 'HEAD' })
  if (head.ok) return true
  if (head.status !== 405 && head.status !== 501) return false
  const get = await fetch(url, { method: 'GET', headers: { Range: 'bytes=0-0' } })
  return get.ok
}

async function main() {
  console.log('base:', base)

  const health = await fetch(`${base}/reel/api/health`)
  if (!health.ok) throw new Error(`health ${health.status}`)
  console.log('health:', await health.json())

  const spa = await fetch(`${base}/reel`)
  if (!spa.ok) throw new Error(`spa ${spa.status}`)
  const html = await spa.text()
  const asset = html.match(/\/reel\/assets\/index-[^"]+\.js/)
  console.log('spa asset:', asset?.[0] || '(none)')

  const a = await upload('', [['a.png', tinyPng()]])
  const sid = a.session_id
  console.log('session:', sid, 'first files:', a.files.length)
  if (a.files.length !== 1) throw new Error('expected 1 file on first upload')

  const b = await upload(sid, [['b.png', tinyPng()]])
  if (b.session_id !== sid) throw new Error('session_id changed unexpectedly')
  if (b.files.length !== 1) throw new Error('expected 1 new file on second upload')
  const merged = [...a.files, ...b.files]
  if (merged.length !== 2) throw new Error('append merge failed')
  if (merged[0].path === merged[1].path) throw new Error('paths collided')
  console.log('append OK: 1 + 1 =>', merged.map((f) => f.name).join(', '))

  for (const f of merged) {
    const ok = await mediaExists(sid, f.path)
    if (!ok) throw new Error(`media missing after upload: ${f.path}`)
  }
  console.log('mediaExists OK for both files')

  const missing = await mediaExists(sid, merged[0].path + '.gone')
  if (missing) throw new Error('expected missing path to fail')
  console.log('missing path correctly rejected')

  const state = {
    session_id: sid,
    tab: 'watermark',
    youtube_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    music_start: 1.5,
    music_end: 10,
    fit_percent: 95,
    reals_photo_duration: 4,
    reals_wm_position: 'bottom_right',
    reals_wm_scale: 22,
    reals_wm_opacity: 90,
    reals_opening_enabled: true,
    reals_opening_duration: 2,
    reals_credits_enabled: false,
    reals_credits_duration: 3,
    reals_text_blocks: [{ text: 'hi', start_time: 0, duration: 2, position: 'bottom_right', font_size: 0 }],
    reals_media: merged,
    reals_watermark: null,
    static_slide_duration: 3,
    static_media: [],
  }
  const save = await fetch(`${base}/reel/api/drafts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sid, state }),
  })
  if (!save.ok) throw new Error(`draft save ${save.status}: ${await save.text()}`)
  const saved = await save.json()
  console.log('draft saved:', saved.name)

  const load = await fetch(`${base}/reel/api/drafts/${encodeURIComponent(saved.name)}`)
  if (!load.ok) throw new Error(`draft load ${load.status}`)
  const snap = await load.json()
  const media = snap.reals?.media || []
  if (media.length !== 2) throw new Error(`draft media len ${media.length}`)
  if (snap.youtube_url !== state.youtube_url) throw new Error('youtube_url not restored')
  if (Number(snap.fit_percent) !== 95) throw new Error('fit_percent not restored')
  if (!snap.reals?.opening_enabled) throw new Error('opening not restored')
  console.log('draft restore OK: media order', media.map((m) => m.name).join(' -> '))

  if (asset?.[0]) {
    const js = await (await fetch(`${base}${asset[0]}`)).text()
    const hash = createHash('sha256').update(js).digest('hex').slice(0, 12)
    const hasAppend = js.includes('Добавлено файлов')
    const hasLabel = js.includes('добавить к списку')
    if (!hasAppend || !hasLabel) throw new Error('SPA bundle missing append UI strings')
    console.log('bundle sha256[:12]=', hash, 'append strings OK')
  }

  console.log('ALL CHECKS PASSED')
}

main().catch((e) => {
  console.error('FAIL:', e)
  process.exit(1)
})
