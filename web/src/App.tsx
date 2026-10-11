import { useEffect, useRef, useState } from 'react'
import {
  applySnapshot,
  createJob,
  fetchMeta,
  getJob,
  listDrafts,
  loadDraft,
  loadLocal,
  pruneMissingMedia,
  saveDraft,
  saveLocal,
  type AppState,
  type AppTab,
  type JobStatus,
  type MediaFile,
  type TextBlock,
  uploadFiles,
} from './api'
import MediaList from './MediaList'
import PreviewStage from './PreviewStage'
import './App.css'

const emptyText = (): TextBlock => ({
  text: '',
  start_time: 0,
  duration: 3,
  position: 'bottom_right',
  font_size: 0,
})

export default function App() {
  const [state, setState] = useState<AppState>(() => loadLocal())
  const [wmPositions, setWmPositions] = useState<Record<string, string>>({})
  const [cornerPositions, setCornerPositions] = useState<Record<string, string>>({})
  const [job, setJob] = useState<JobStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [drafts, setDrafts] = useState<{ name: string; label: string }[]>([])
  const [draftName, setDraftName] = useState('')
  const [toast, setToast] = useState('')
  const pollRef = useRef<number | null>(null)
  const autosaveRef = useRef<number | null>(null)

  const patch = (partial: Partial<AppState>) =>
    setState((s) => {
      const next = { ...s, ...partial }
      saveLocal(next)
      return next
    })

  const setTab = (tab: AppTab) => {
    patch({ tab })
    setJob(null)
    setErr('')
  }

  const stateRef = useRef(state)
  stateRef.current = state

  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setWmPositions(m.wm_positions)
        setCornerPositions(m.corner_positions)
      })
      .catch(() => {})
    listDrafts()
      .then((d) => setDrafts(d.drafts))
      .catch(() => {})
  }, [])

  // Verify persisted media still on server (tmp cleanup after ~6h); drop missing.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const current = stateRef.current
      const has =
        current.reals_media.length > 0 ||
        current.static_media.length > 0 ||
        !!current.reals_watermark
      if (!has) return
      const { state: next, dropped } = await pruneMissingMedia(current)
      if (cancelled) return
      if (!dropped.length) return
      saveLocal(next)
      setState(next)
      const names = dropped.slice(0, 3).join(', ')
      const more = dropped.length > 3 ? ` и ещё ${dropped.length - 3}` : ''
      setToast(
        `Истекли / пропали с сервера (${dropped.length}): ${names}${more}. Загрузите снова.`,
      )
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    autosaveRef.current = window.setInterval(() => {
      saveLocal(stateRef.current)
    }, 30_000)
    const serverTimer = window.setInterval(() => {
      const s = stateRef.current
      saveDraft(s)
        .then((r) => {
          if (r.session_id && r.session_id !== s.session_id) {
            patch({ session_id: r.session_id })
          }
          setToast(`Autosave: ${r.name}`)
          listDrafts().then((d) => setDrafts(d.drafts)).catch(() => {})
        })
        .catch(() => {})
    }, 180_000)
    return () => {
      if (autosaveRef.current) clearInterval(autosaveRef.current)
      clearInterval(serverTimer)
    }
  }, [])

  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'error') {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    pollRef.current = window.setInterval(() => {
      getJob(job.id)
        .then(setJob)
        .catch((e) => setErr(String(e)))
    }, 1500)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [job?.id, job?.status])

  async function onMedia(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    setErr('')
    try {
      const res = await uploadFiles(files, stateRef.current.session_id, 'reals')
      setState((s) => {
        const next = {
          ...s,
          session_id: res.session_id,
          reals_media: [...s.reals_media, ...res.files],
        }
        saveLocal(next)
        return next
      })
      setToast(`Добавлено файлов: ${res.files.length}`)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onStaticMedia(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    setErr('')
    try {
      const res = await uploadFiles(files, stateRef.current.session_id, 'static')
      setState((s) => {
        const next = {
          ...s,
          session_id: res.session_id,
          static_media: [...s.static_media, ...res.files],
        }
        saveLocal(next)
        return next
      })
      setToast(`Добавлено фото: ${res.files.length}`)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onWatermark(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    setErr('')
    try {
      const res = await uploadFiles(files, stateRef.current.session_id, 'wm')
      const wm = res.files[0]
      patch({ session_id: res.session_id, reals_watermark: wm })
      setToast('Вотермарка загружена')
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  function updateText(i: number, partial: Partial<TextBlock>) {
    const blocks = state.reals_text_blocks.map((b, idx) =>
      idx === i ? { ...b, ...partial } : b,
    )
    patch({ reals_text_blocks: blocks })
  }

  function musicEndValue() {
    return state.music_end && state.music_end > state.music_start ? state.music_end : null
  }

  async function startWatermarkRender() {
    setErr('')
    if (!state.reals_watermark?.path) {
      setErr('Загрузите вотермарку')
      return
    }
    if (!state.reals_media.length) {
      setErr('Загрузите хотя бы одно фото или видео')
      return
    }
    setBusy(true)
    try {
      await saveDraft(state)
      const res = await createJob({
        kind: 'watermark',
        session_id: state.session_id,
        media_ids: state.reals_media.map((m) => m.id || m.path),
        media_paths: state.reals_media.map((m) => m.path),
        media: state.reals_media.map((m) => ({
          path: m.path,
          trim_start: m.trim_start ?? 0,
          trim_end: m.trim_end ?? m.duration_sec ?? null,
        })),
        watermark_path: state.reals_watermark.path,
        photo_duration: state.reals_photo_duration,
        fit_percent: state.fit_percent,
        wm_position: state.reals_wm_position,
        wm_scale: state.reals_wm_scale,
        wm_opacity: state.reals_wm_opacity,
        youtube_url: state.youtube_url,
        music_start: state.music_start,
        music_end: musicEndValue(),
        opening_enabled: state.reals_opening_enabled,
        opening_duration: state.reals_opening_duration,
        credits_enabled: state.reals_credits_enabled,
        credits_duration: state.reals_credits_duration,
        text_blocks: state.reals_text_blocks.filter((t) => t.text.trim()),
      })
      setJob(res)
      setToast(`Job ${res.job_id}`)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function startStaticRender() {
    setErr('')
    if (!state.static_media.length) {
      setErr('Загрузите хотя бы одно изображение')
      return
    }
    setBusy(true)
    try {
      await saveDraft(state)
      const res = await createJob({
        kind: 'static',
        session_id: state.session_id,
        media_ids: state.static_media.map((m) => m.id || m.path),
        media_paths: state.static_media.map((m) => m.path),
        photo_duration: state.static_slide_duration,
        fit_percent: state.fit_percent,
        youtube_url: state.youtube_url,
        music_start: state.music_start,
        music_end: musicEndValue(),
      })
      setJob(res)
      setToast(`Job ${res.job_id}`)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onSaveDraft() {
    try {
      const r = await saveDraft(state)
      patch({ session_id: r.session_id })
      setToast(`Сохранено: ${r.name}`)
      const d = await listDrafts()
      setDrafts(d.drafts)
    } catch (e) {
      setErr(String(e))
    }
  }

  async function onRestoreDraft() {
    if (!draftName) return
    try {
      const data = await loadDraft(draftName)
      const applied = applySnapshot(data, state)
      const { state: next, dropped } = await pruneMissingMedia(applied)
      saveLocal(next)
      setState(next)
      if (dropped.length) {
        setToast(
          `Восстановлено: ${draftName} · пропало файлов: ${dropped.length}`,
        )
      } else {
        setToast(`Восстановлено: ${draftName}`)
      }
    } catch (e) {
      setErr(String(e))
    }
  }

  const rendering = job?.status === 'pending' || job?.status === 'running'
  const isStatic = state.tab === 'static'

  function reorderReals(next: MediaFile[]) {
    patch({ reals_media: next })
  }

  function reorderStatic(next: MediaFile[]) {
    patch({ static_media: next })
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>RealsMaker</h1>
          <p className="muted">
            {isStatic
              ? '1080×1920 · фото · Ken Burns · без текста'
              : '1080×1920 · вотермарка · Opening / Титры · Jost Bold'}
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn ghost" onClick={onSaveDraft} disabled={busy}>
            Сохранить слепок
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={isStatic ? startStaticRender : startWatermarkRender}
            disabled={busy || rendering}
          >
            {isStatic ? 'Создать статичный Reels' : 'Создать Reels'}
          </button>
        </div>
      </header>

      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={!isStatic}
          className={`tab ${!isStatic ? 'active' : ''}`}
          onClick={() => setTab('watermark')}
        >
          Reals
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={isStatic}
          className={`tab ${isStatic ? 'active' : ''}`}
          onClick={() => setTab('static')}
        >
          Статичный Reels
        </button>
      </div>

      {toast && <div className="toast">{toast}</div>}
      {err && <div className="error">{err}</div>}

      {isStatic ? (
        <div className="grid">
          <section className="panel">
            <h2>Фото</h2>
            <p className="muted small">
              Вертикальные изображения (9:16). Лёгкий Ken Burns, без текста. Поля — фирменный цвет.
            </p>
            <label className="file">
              <span>Изображения (добавить к списку, порядок = ролик)</span>
              <input
                type="file"
                multiple
                accept="image/*,.jpg,.jpeg,.png,.webp"
                onChange={(e) => {
                  onStaticMedia(e.target.files)
                  e.target.value = ''
                }}
              />
            </label>
            {state.static_media.length > 0 && (
              <MediaList
                items={state.static_media}
                onReorder={reorderStatic}
                onRemove={(i) =>
                  patch({ static_media: state.static_media.filter((_, idx) => idx !== i) })
                }
                onPatch={(i, p) =>
                  patch({
                    static_media: state.static_media.map((m, idx) =>
                      idx === i ? { ...m, ...p } : m,
                    ),
                  })
                }
                timeline={{ photoDuration: state.static_slide_duration }}
              />
            )}

            <div className="row">
              <label>
                Длительность каждого фото (с)
                <input
                  type="number"
                  min={0.5}
                  max={30}
                  step={0.5}
                  value={state.static_slide_duration}
                  onChange={(e) => patch({ static_slide_duration: Number(e.target.value) })}
                />
              </label>
              <label>
                Вписывание (%)
                <input
                  type="number"
                  min={70}
                  max={99}
                  value={state.fit_percent}
                  onChange={(e) => patch({ fit_percent: Number(e.target.value) })}
                />
              </label>
            </div>
          </section>

          <section className="panel">
            <h2>Музыка (YouTube)</h2>
            <label>
              URL
              <input
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={state.youtube_url}
                onChange={(e) => patch({ youtube_url: e.target.value })}
              />
            </label>
            <div className="row">
              <label>
                Начало (с)
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={state.music_start}
                  onChange={(e) => patch({ music_start: Number(e.target.value) })}
                />
              </label>
              <label>
                Конец (с, 0 = авто)
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={state.music_end ?? 0}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    patch({ music_end: v > 0 ? v : null })
                  }}
                />
              </label>
            </div>
          </section>

          <section className="panel">
            <h2>Рендер</h2>
            {!job && <p className="muted">Нажмите «Создать статичный Reels» — рендер в фоне.</p>}
            {job && (
              <div className="job">
                <div className="row between">
                  <span>
                    Job <code>{job.id}</code>
                  </span>
                  <span className={`status ${job.status}`}>{job.status}</span>
                </div>
                <div className="bar">
                  <div style={{ width: `${job.progress}%` }} />
                </div>
                <p className="muted">{job.message}</p>
                {job.error && <pre className="error-pre">{job.error}</pre>}
                {job.status === 'done' && job.result_url && (
                  <a className="btn primary" href={job.result_url} download>
                    Скачать MP4
                  </a>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Drafts (tmp, 6 ч)</h2>
            <div className="row">
              <select value={draftName} onChange={(e) => setDraftName(e.target.value)}>
                <option value="">— выбрать —</option>
                {drafts.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.label} · {d.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn ghost" onClick={onRestoreDraft}>
                Восстановить
              </button>
            </div>
            <p className="muted small">
              Session: {state.session_id || '—'} · localStorage + server snapshots
            </p>
          </section>
        </div>
      ) : (
        <div className="grid">
          <section className="panel">
            <h2>Медиа</h2>
            <label className="file">
              <span>Фото / видео (добавить к списку, порядок = ролик)</span>
              <input
                type="file"
                multiple
                accept="image/*,video/*,.mp4,.mov,.webm,.m4v"
                onChange={(e) => {
                  onMedia(e.target.files)
                  e.target.value = ''
                }}
              />
            </label>
            {state.reals_media.length > 0 && (
              <MediaList
                items={state.reals_media}
                onReorder={reorderReals}
                onRemove={(i) =>
                  patch({ reals_media: state.reals_media.filter((_, idx) => idx !== i) })
                }
                onPatch={(i, p) =>
                  patch({
                    reals_media: state.reals_media.map((m, idx) =>
                      idx === i ? { ...m, ...p } : m,
                    ),
                  })
                }
                timeline={{
                  photoDuration: state.reals_photo_duration,
                  openingEnabled: state.reals_opening_enabled,
                  openingDuration: state.reals_opening_duration,
                  creditsEnabled: state.reals_credits_enabled,
                  creditsDuration: state.reals_credits_duration,
                }}
              />
            )}

            <div className="row">
              <label>
                Длительность фото (с)
                <input
                  type="number"
                  min={0.5}
                  max={30}
                  step={0.5}
                  value={state.reals_photo_duration}
                  onChange={(e) => patch({ reals_photo_duration: Number(e.target.value) })}
                />
              </label>
              <label>
                Вписывание (%)
                <input
                  type="number"
                  min={70}
                  max={99}
                  value={state.fit_percent}
                  onChange={(e) => patch({ fit_percent: Number(e.target.value) })}
                />
              </label>
            </div>
          </section>

          <section className="panel">
            <h2>Вотермарка</h2>
            <label className="file">
              <span>Вотермарка (PNG)</span>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => {
                  onWatermark(e.target.files)
                  e.target.value = ''
                }}
              />
            </label>
            {state.reals_watermark && (
              <div className="wm-preview">
                {state.reals_watermark.url ? (
                  <div className="media-thumb">
                    <img
                      src={state.reals_watermark.url}
                      alt={state.reals_watermark.name}
                    />
                  </div>
                ) : null}
                <p className="muted small">WM: {state.reals_watermark.name}</p>
              </div>
            )}
            <label>
              Позиция
              <select
                value={state.reals_wm_position}
                onChange={(e) => patch({ reals_wm_position: e.target.value })}
              >
                {Object.entries(wmPositions).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Размер (% ширины): {state.reals_wm_scale}
              <input
                type="range"
                min={8}
                max={50}
                value={state.reals_wm_scale}
                onChange={(e) => patch({ reals_wm_scale: Number(e.target.value) })}
              />
            </label>
            <label>
              Прозрачность на медиа (%): {state.reals_wm_opacity}
              <input
                type="range"
                min={10}
                max={100}
                value={state.reals_wm_opacity}
                onChange={(e) => patch({ reals_wm_opacity: Number(e.target.value) })}
              />
              <span className="muted small">Opening / Титры всегда opacity 1.0</span>
            </label>
          </section>

          <section className="panel">
            <h2>Opening / Титры</h2>
            <label className="check">
              <input
                type="checkbox"
                checked={state.reals_opening_enabled}
                onChange={(e) => patch({ reals_opening_enabled: e.target.checked })}
              />
              Opening
            </label>
            <label>
              Длительность Opening (с)
              <input
                type="number"
                min={0.5}
                max={30}
                step={0.5}
                disabled={!state.reals_opening_enabled}
                value={state.reals_opening_duration}
                onChange={(e) => patch({ reals_opening_duration: Number(e.target.value) })}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={state.reals_credits_enabled}
                onChange={(e) => patch({ reals_credits_enabled: e.target.checked })}
              />
              Титры
            </label>
            <label>
              Длительность Титры (с)
              <input
                type="number"
                min={0.5}
                max={30}
                step={0.5}
                disabled={!state.reals_credits_enabled}
                value={state.reals_credits_duration}
                onChange={(e) => patch({ reals_credits_duration: Number(e.target.value) })}
              />
            </label>
          </section>

          <section className="panel">
            <h2>Музыка (YouTube)</h2>
            <label>
              URL
              <input
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={state.youtube_url}
                onChange={(e) => patch({ youtube_url: e.target.value })}
              />
            </label>
            <div className="row">
              <label>
                Начало (с)
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={state.music_start}
                  onChange={(e) => patch({ music_start: Number(e.target.value) })}
                />
              </label>
              <label>
                Конец (с, 0 = авто)
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={state.music_end ?? 0}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    patch({ music_end: v > 0 ? v : null })
                  }}
                />
              </label>
            </div>
          </section>

          <section className="panel span2">
            <div className="row between">
              <h2>Текстовые блоки (до 10)</h2>
              <button
                type="button"
                className="btn ghost"
                disabled={state.reals_text_blocks.length >= 10}
                onClick={() =>
                  patch({ reals_text_blocks: [...state.reals_text_blocks, emptyText()] })
                }
              >
                + Блок
              </button>
            </div>
            {state.reals_text_blocks.length === 0 && (
              <p className="muted">Нет блоков. Добавьте подписи по углам кадра.</p>
            )}
            {state.reals_text_blocks.map((tb, i) => (
              <div className="text-block" key={i}>
                <textarea
                  rows={2}
                  placeholder="Текст"
                  value={tb.text}
                  onChange={(e) => updateText(i, { text: e.target.value })}
                />
                <div className="row">
                  <label>
                    Старт (с)
                    <input
                      type="number"
                      min={0}
                      step={0.1}
                      value={tb.start_time}
                      onChange={(e) => updateText(i, { start_time: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    Длит. (с)
                    <input
                      type="number"
                      min={0.3}
                      step={0.1}
                      value={tb.duration}
                      onChange={(e) => updateText(i, { duration: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    Угол
                    <select
                      value={tb.position}
                      onChange={(e) => updateText(i, { position: e.target.value })}
                    >
                      {Object.entries(cornerPositions).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Шрифт px (0=авто)
                    <input
                      type="number"
                      min={0}
                      max={200}
                      value={tb.font_size}
                      onChange={(e) => updateText(i, { font_size: Number(e.target.value) })}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  className="btn ghost danger"
                  onClick={() =>
                    patch({
                      reals_text_blocks: state.reals_text_blocks.filter((_, idx) => idx !== i),
                    })
                  }
                >
                  Удалить
                </button>
              </div>
            ))}
          </section>

          <PreviewStage
            media={state.reals_media}
            textBlocks={state.reals_text_blocks}
            timeline={{
              photoDuration: state.reals_photo_duration,
              openingEnabled: state.reals_opening_enabled,
              openingDuration: state.reals_opening_duration,
              creditsEnabled: state.reals_credits_enabled,
              creditsDuration: state.reals_credits_duration,
            }}
          />

          <section className="panel">
            <h2>Рендер</h2>
            {!job && <p className="muted">Нажмите «Создать Reels» — рендер в фоне.</p>}
            {job && (
              <div className="job">
                <div className="row between">
                  <span>
                    Job <code>{job.id}</code>
                  </span>
                  <span className={`status ${job.status}`}>{job.status}</span>
                </div>
                <div className="bar">
                  <div style={{ width: `${job.progress}%` }} />
                </div>
                <p className="muted">{job.message}</p>
                {job.error && <pre className="error-pre">{job.error}</pre>}
                {job.status === 'done' && job.result_url && (
                  <a className="btn primary" href={job.result_url} download>
                    Скачать MP4
                  </a>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Drafts (tmp, 6 ч)</h2>
            <div className="row">
              <select value={draftName} onChange={(e) => setDraftName(e.target.value)}>
                <option value="">— выбрать —</option>
                {drafts.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.label} · {d.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn ghost" onClick={onRestoreDraft}>
                Восстановить
              </button>
            </div>
            <p className="muted small">
              Session: {state.session_id || '—'} · localStorage + server snapshots
            </p>
          </section>
        </div>
      )}
    </div>
  )
}
