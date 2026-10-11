import { useEffect, useState, type DragEvent, type MouseEvent } from 'react'
import type { MediaFile } from './api'

export type MediaTimelineOpts = {
  photoDuration: number
  openingEnabled?: boolean
  openingDuration?: number
  creditsEnabled?: boolean
  creditsDuration?: number
}

export type MediaRange = {
  start: number
  end: number | null
  unknown: boolean
  label: string
}

function fmt(sec: number): string {
  return (Math.round(sec * 10) / 10).toFixed(1)
}

/** Effective clip length for timeline (honors trim). */
export function effectiveMediaDuration(
  m: MediaFile,
  photoDuration: number,
): number | null {
  if (m.kind === 'video') {
    const full = m.duration_sec
    if (full == null || !(full > 0)) return null
    const start = m.trim_start ?? 0
    const end = m.trim_end ?? full
    if (!(start >= 0 && end <= full + 1e-9 && start < end)) return null
    return end - start
  }
  return photoDuration
}

export function computeMediaRanges(
  media: MediaFile[],
  opts: MediaTimelineOpts,
): { ranges: MediaRange[]; mediaEnd: number; totalEnd: number } {
  let t =
    opts.openingEnabled && (opts.openingDuration || 0) > 0
      ? Number(opts.openingDuration)
      : 0
  let uncertain = false
  const ranges: MediaRange[] = media.map((m) => {
    if (uncertain) {
      return { start: t, end: null, unknown: true, label: '?–? с' }
    }
    const start = t
    if (m.kind === 'video') {
      const d = effectiveMediaDuration(m, opts.photoDuration)
      if (d != null && d > 0) {
        t += d
        return {
          start,
          end: start + d,
          unknown: false,
          label: `${fmt(start)}–${fmt(start + d)} с`,
        }
      }
      uncertain = true
      return {
        start,
        end: null,
        unknown: true,
        label: `${fmt(start)}–? с · видео ~?`,
      }
    }
    const d = opts.photoDuration
    t += d
    return {
      start,
      end: start + d,
      unknown: false,
      label: `${fmt(start)}–${fmt(start + d)} с`,
    }
  })
  const mediaEnd = t
  const credits =
    opts.creditsEnabled && (opts.creditsDuration || 0) > 0
      ? Number(opts.creditsDuration)
      : 0
  return { ranges, mediaEnd, totalEnd: mediaEnd + credits }
}

function stopDrag(e: MouseEvent) {
  e.stopPropagation()
}

type Props = {
  items: MediaFile[]
  onReorder: (next: MediaFile[]) => void
  onRemove?: (index: number) => void
  onPatch?: (index: number, patch: Partial<MediaFile>) => void
  timeline: MediaTimelineOpts
  emptyHint?: string
}

export default function MediaList({
  items,
  onReorder,
  onRemove,
  onPatch,
  timeline,
  emptyHint,
}: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [overIndex, setOverIndex] = useState<number | null>(null)
  const [trimIndex, setTrimIndex] = useState<number | null>(null)
  const [trimStart, setTrimStart] = useState('0')
  const [trimEnd, setTrimEnd] = useState('')
  const [trimError, setTrimError] = useState('')
  const [preview, setPreview] = useState<MediaFile | null>(null)
  const { ranges, mediaEnd, totalEnd } = computeMediaRanges(items, timeline)
  const opening =
    timeline.openingEnabled && (timeline.openingDuration || 0) > 0
      ? Number(timeline.openingDuration)
      : 0
  const credits =
    timeline.creditsEnabled && (timeline.creditsDuration || 0) > 0
      ? Number(timeline.creditsDuration)
      : 0

  useEffect(() => {
    if (!preview) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [preview])

  if (!items.length) {
    return emptyHint ? <p className="muted small">{emptyHint}</p> : null
  }

  function move(from: number, to: number) {
    if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
      return
    }
    const next = items.slice()
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onReorder(next)
  }

  function onDragStart(e: DragEvent, index: number) {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }

  function onDragOver(e: DragEvent, index: number) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (overIndex !== index) setOverIndex(index)
  }

  function onDrop(e: DragEvent, index: number) {
    e.preventDefault()
    const fromRaw = e.dataTransfer.getData('text/plain')
    const from = dragIndex ?? Number(fromRaw)
    move(from, index)
    setDragIndex(null)
    setOverIndex(null)
  }

  function onDragEnd() {
    setDragIndex(null)
    setOverIndex(null)
  }

  function openTrim(index: number) {
    const m = items[index]
    if (!m || m.kind !== 'video') return
    const full = m.duration_sec ?? 0
    setTrimIndex(index)
    setTrimStart(String(m.trim_start ?? 0))
    setTrimEnd(String(m.trim_end ?? full))
    setTrimError('')
  }

  function applyTrim() {
    if (trimIndex == null || !onPatch) return
    const m = items[trimIndex]
    const full = m?.duration_sec
    if (full == null || !(full > 0)) {
      setTrimError('Длительность видео неизвестна')
      return
    }
    const start = Number(trimStart)
    const end = Number(trimEnd)
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      setTrimError('Введите числа')
      return
    }
    if (!(start >= 0 && start < end && end <= full + 1e-6)) {
      setTrimError(`Нужно: 0 ≤ start < end ≤ ${fmt(full)}`)
      return
    }
    onPatch(trimIndex, {
      trim_start: Math.round(start * 1000) / 1000,
      trim_end: Math.round(end * 1000) / 1000,
    })
    setTrimIndex(null)
    setTrimError('')
  }

  const trimSeg =
    Number.isFinite(Number(trimStart)) && Number.isFinite(Number(trimEnd))
      ? Math.max(0, Number(trimEnd) - Number(trimStart))
      : null

  return (
    <div className="media-list-wrap">
      {(opening > 0 || credits > 0) && (
        <p className="muted small media-timeline-note">
          {opening > 0 && <>Opening 0.0–{fmt(opening)} с · </>}
          медиа с {fmt(opening)} с
          {credits > 0 && (
            <>
              {' '}
              · титры {fmt(mediaEnd)}–{fmt(totalEnd)} с
            </>
          )}
          {' '}
          · всего ≈ {fmt(totalEnd)} с
        </p>
      )}
      <ul className="media-list">
        {items.map((m, i) => {
          const thumb = m.url || null
          const isVideo = m.kind === 'video'
          const range = ranges[i]
          const isLast = i === items.length - 1
          const clipDur = effectiveMediaDuration(m, timeline.photoDuration)
          const trimmed =
            isVideo &&
            m.duration_sec != null &&
            ((m.trim_start != null && m.trim_start > 0) ||
              (m.trim_end != null && m.trim_end < m.duration_sec - 1e-6))
          return (
            <li key={m.id || m.path} className="media-card-item">
              <div
                className={[
                  'media-card',
                  dragIndex === i ? 'dragging' : '',
                  overIndex === i && dragIndex !== i ? 'drag-over' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                draggable
                onDragStart={(e) => onDragStart(e, i)}
                onDragOver={(e) => onDragOver(e, i)}
                onDrop={(e) => onDrop(e, i)}
                onDragEnd={onDragEnd}
              >
                <span className="media-handle" title="Перетащить" aria-hidden>
                  ⋮⋮
                </span>
                <span className="media-order">{i + 1}</span>
                <div className="media-thumb">
                  {thumb ? (
                    isVideo ? (
                      <video src={thumb} muted playsInline preload="metadata" />
                    ) : (
                      <img src={thumb} alt="" />
                    )
                  ) : (
                    <span className="media-thumb-fallback">
                      {isVideo ? 'видео' : 'фото'}
                    </span>
                  )}
                </div>
                <div className="media-meta">
                  <div className="media-name" title={m.name}>
                    {m.name}
                  </div>
                  <div className="media-range">
                    {range?.label}
                    {isVideo && clipDur != null && clipDur > 0 && (
                      <span className="muted">
                        {' '}
                        · {trimmed ? `клип ${fmt(clipDur)}` : fmt(clipDur)} с
                        {trimmed && m.duration_sec != null
                          ? ` / ${fmt(m.duration_sec)}`
                          : ''}
                      </span>
                    )}
                    {isLast && credits > 0 && (
                      <span className="muted"> · далее титры</span>
                    )}
                  </div>
                  <div className="media-kind muted small">
                    {m.kind || '?'}
                    {m.size ? ` · ${(m.size / 1024).toFixed(0)} КБ` : ''}
                    {trimmed && (
                      <span>
                        {' '}
                        · trim {fmt(m.trim_start ?? 0)}–{fmt(m.trim_end ?? 0)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="media-actions" onMouseDown={stopDrag}>
                  <button
                    type="button"
                    className="btn ghost media-icon-btn"
                    aria-label="Просмотр"
                    title="Просмотр"
                    draggable={false}
                    onClick={() => setPreview(m)}
                  >
                    🔍
                  </button>
                  {isVideo && onPatch && (
                    <button
                      type="button"
                      className="btn ghost media-icon-btn"
                      aria-label="Обрезать"
                      title="Обрезать видео"
                      draggable={false}
                      onClick={() =>
                        trimIndex === i ? setTrimIndex(null) : openTrim(i)
                      }
                    >
                      ✎
                    </button>
                  )}
                  {onRemove && (
                    <button
                      type="button"
                      className="btn ghost danger media-remove"
                      aria-label="Удалить"
                      draggable={false}
                      onClick={() => onRemove(i)}
                    >
                      ×
                    </button>
                  )}
                </div>
              </div>
              {trimIndex === i && (
                <div className="media-trim-panel" onMouseDown={stopDrag}>
                  <div className="row media-trim-row">
                    <label>
                      Start (с)
                      <input
                        type="number"
                        min={0}
                        max={m.duration_sec ?? undefined}
                        step={0.1}
                        value={trimStart}
                        onChange={(e) => setTrimStart(e.target.value)}
                      />
                    </label>
                    <label>
                      End (с)
                      <input
                        type="number"
                        min={0}
                        max={m.duration_sec ?? undefined}
                        step={0.1}
                        value={trimEnd}
                        onChange={(e) => setTrimEnd(e.target.value)}
                      />
                    </label>
                    <div className="media-trim-meta muted small">
                      сегмент:{' '}
                      {trimSeg != null ? `${fmt(trimSeg)} с` : '—'}
                      {m.duration_sec != null && (
                        <> · полное {fmt(m.duration_sec)} с</>
                      )}
                    </div>
                  </div>
                  {trimError && <p className="error media-trim-error">{trimError}</p>}
                  <div className="media-trim-actions">
                    <button type="button" className="btn" onClick={applyTrim}>
                      Применить
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() => {
                        setTrimIndex(null)
                        setTrimError('')
                      }}
                    >
                      Отмена
                    </button>
                    {m.duration_sec != null && (
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => {
                          setTrimStart('0')
                          setTrimEnd(String(m.duration_sec))
                          setTrimError('')
                        }}
                      >
                        Сброс
                      </button>
                    )}
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {!(opening > 0 || credits > 0) && (
        <p className="muted small">
          {items.length} файл(ов) · ролик ≈ {fmt(totalEnd)} с · перетащите для порядка
        </p>
      )}

      {preview && (
        <div
          className="media-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Просмотр медиа"
          onClick={() => setPreview(null)}
        >
          <div
            className="media-lightbox-inner"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={stopDrag}
          >
            <button
              type="button"
              className="btn ghost media-lightbox-close"
              aria-label="Закрыть"
              onClick={() => setPreview(null)}
            >
              ×
            </button>
            <div className="media-lightbox-body">
              {preview.url ? (
                preview.kind === 'video' ? (
                  <video src={preview.url} controls autoPlay playsInline />
                ) : (
                  <img src={preview.url} alt={preview.name} />
                )
              ) : (
                <p className="muted">Нет URL превью</p>
              )}
            </div>
            <p className="media-lightbox-caption muted small">{preview.name}</p>
          </div>
        </div>
      )}
    </div>
  )
}
