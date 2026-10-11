import { useEffect, useMemo, useRef, useState } from 'react'
import type { MediaFile, TextBlock } from './api'
import { computeMediaRanges, type MediaTimelineOpts } from './MediaList'

/** Brand defaults from reels/colors.py — SPA text blocks don't expose color pickers. */
export const PREVIEW_FONT_COLOR = '#FFD8B5'
export const PREVIEW_BG_COLOR = '#56858C'

const LS_SCRUB = 'realsmaker_preview_scrub'
const LS_CLIP = 'realsmaker_preview_clip'

function fmt(sec: number): string {
  return (Math.round(sec * 10) / 10).toFixed(1)
}

function loadNum(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key))
    return Number.isFinite(v) ? v : fallback
  } catch {
    return fallback
  }
}

function saveNum(key: string, v: number) {
  try {
    localStorage.setItem(key, String(v))
  } catch {
    /* ignore */
  }
}

function activeTexts(blocks: TextBlock[], t: number): TextBlock[] {
  return blocks.filter((b) => {
    if (!b.text.trim()) return false
    const local = t - b.start_time
    return local >= 0 && local < b.duration
  })
}

function cornerClass(position: string): string {
  switch (position) {
    case 'top_left':
    case 'top_right':
    case 'bottom_left':
    case 'bottom_right':
      return position
    default:
      return 'bottom_right'
  }
}

function previewFontPx(fontSize: number): number {
  // Schematic: map 1080px frame → ~270px stage (~0.25×), clamp for readability.
  if (fontSize > 0) return Math.max(11, Math.min(28, fontSize * 0.25))
  return 15
}

type Zone = 'opening' | 'media' | 'credits' | 'empty'

type Props = {
  media: MediaFile[]
  textBlocks: TextBlock[]
  timeline: MediaTimelineOpts
}

export default function PreviewStage({ media, textBlocks, timeline }: Props) {
  const [scrub, setScrub] = useState(() => loadNum(LS_SCRUB, 0))
  const [clipIndex, setClipIndex] = useState(() => Math.max(0, Math.floor(loadNum(LS_CLIP, 0))))
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const { ranges, mediaEnd, totalEnd } = useMemo(
    () => computeMediaRanges(media, timeline),
    [media, timeline],
  )

  const opening =
    timeline.openingEnabled && (timeline.openingDuration || 0) > 0
      ? Number(timeline.openingDuration)
      : 0
  const credits =
    timeline.creditsEnabled && (timeline.creditsDuration || 0) > 0
      ? Number(timeline.creditsDuration)
      : 0

  const maxT = Math.max(0.1, totalEnd || 0.1)

  // Clamp scrub / clip when media or timeline changes.
  useEffect(() => {
    setScrub((t) => {
      const next = Math.min(Math.max(0, t), maxT)
      if (next !== t) saveNum(LS_SCRUB, next)
      return next
    })
    setClipIndex((i) => {
      if (!media.length) return 0
      const next = Math.min(Math.max(0, i), media.length - 1)
      if (next !== i) saveNum(LS_CLIP, next)
      return next
    })
  }, [media.length, maxT])

  const zone: Zone = (() => {
    if (!media.length && opening <= 0 && credits <= 0) return 'empty'
    if (opening > 0 && scrub < opening) return 'opening'
    if (credits > 0 && scrub >= mediaEnd - 1e-9) return 'credits'
    if (!media.length) return 'empty'
    return 'media'
  })()

  // Which clip is under scrub (media zone); keep clipIndex in sync when scrubbing.
  const scrubClipIndex = (() => {
    if (zone !== 'media' || !media.length) return clipIndex
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i]
      if (r.unknown) {
        if (scrub >= r.start) return i
        continue
      }
      const end = r.end ?? Infinity
      if (scrub >= r.start && scrub < end - 1e-9) return i
      if (i === ranges.length - 1 && scrub >= r.start) return i
    }
    return clipIndex
  })()

  useEffect(() => {
    if (zone === 'media' && scrubClipIndex !== clipIndex && scrubClipIndex >= 0) {
      setClipIndex(scrubClipIndex)
      saveNum(LS_CLIP, scrubClipIndex)
    }
  }, [zone, scrubClipIndex, clipIndex])

  const activeClip = media[Math.min(clipIndex, Math.max(0, media.length - 1))] || null
  const activeRange = ranges[Math.min(clipIndex, Math.max(0, ranges.length - 1))] || null
  const texts = zone === 'media' ? activeTexts(textBlocks, scrub) : []

  function setScrubPersist(t: number) {
    const next = Math.min(Math.max(0, t), maxT)
    setScrub(next)
    saveNum(LS_SCRUB, next)
  }

  function selectClip(i: number, syncScrub = true) {
    if (i < 0 || i >= media.length) return
    setClipIndex(i)
    saveNum(LS_CLIP, i)
    if (syncScrub) {
      const start = ranges[i]?.start ?? opening
      setScrubPersist(start)
    }
  }

  // Seek video to trim_start + offset within clip.
  useEffect(() => {
    const el = videoRef.current
    if (!el || !activeClip || activeClip.kind !== 'video' || zone !== 'media') return
    const rangeStart = activeRange?.start ?? 0
    const trim0 = activeClip.trim_start ?? 0
    const local = Math.max(0, scrub - rangeStart)
    const target = trim0 + local
    const apply = () => {
      try {
        if (Number.isFinite(target) && Math.abs((el.currentTime || 0) - target) > 0.05) {
          el.currentTime = target
        }
      } catch {
        /* ignore seek errors before metadata */
      }
    }
    if (el.readyState >= 1) apply()
    else {
      const onMeta = () => {
        apply()
        el.removeEventListener('loadedmetadata', onMeta)
      }
      el.addEventListener('loadedmetadata', onMeta)
      return () => el.removeEventListener('loadedmetadata', onMeta)
    }
  }, [activeClip, activeRange, scrub, zone])

  if (!media.length && opening <= 0) {
    return (
      <section className="panel span2 preview-panel">
        <h2>Предпросмотр</h2>
        <p className="muted small">Загрузите медиа — здесь появится схематичный кадр 9:16.</p>
      </section>
    )
  }

  return (
    <section className="panel span2 preview-panel">
      <h2>Предпросмотр</h2>
      <p className="muted small">
        Схематично · углы текста и таймлайн до ffmpeg · без Ken Burns / анимации раскрытия
      </p>

      <div className="preview-layout">
        <div className="preview-stage-wrap">
          <div className="preview-stage" aria-label="Кадр 9:16">
            {zone === 'opening' && (
              <div className="preview-splash">
                <span>Opening</span>
              </div>
            )}
            {zone === 'credits' && (
              <div className="preview-splash">
                <span>Титры</span>
              </div>
            )}
            {zone === 'media' && activeClip && (
              <>
                <div className="preview-media">
                  {activeClip.url ? (
                    activeClip.kind === 'video' ? (
                      <video
                        key={activeClip.id || activeClip.path}
                        ref={videoRef}
                        src={activeClip.url}
                        muted
                        playsInline
                        preload="metadata"
                      />
                    ) : (
                      <img src={activeClip.url} alt="" />
                    )
                  ) : (
                    <div className="preview-media-fallback muted">Нет URL</div>
                  )}
                </div>
                {texts.map((tb, i) => (
                  <div
                    key={`${i}-${tb.start_time}-${tb.position}`}
                    className={`preview-text ${cornerClass(tb.position)}`}
                    style={{
                      color: PREVIEW_FONT_COLOR,
                      backgroundColor: PREVIEW_BG_COLOR,
                      fontSize: `${previewFontPx(tb.font_size)}px`,
                    }}
                  >
                    {tb.text}
                  </div>
                ))}
              </>
            )}
            {zone === 'empty' && (
              <div className="preview-splash muted">
                <span>—</span>
              </div>
            )}
          </div>
        </div>

        <div className="preview-controls">
          {media.length > 0 && (
            <div className="preview-clip-row">
              <button
                type="button"
                className="btn ghost"
                disabled={clipIndex <= 0}
                onClick={() => selectClip(clipIndex - 1)}
                aria-label="Предыдущий клип"
              >
                ←
              </button>
              <label className="preview-clip-select">
                Клип
                <select
                  value={Math.min(clipIndex, media.length - 1)}
                  onChange={(e) => selectClip(Number(e.target.value))}
                >
                  {media.map((m, i) => (
                    <option key={m.id || m.path} value={i}>
                      {i + 1}. {m.name}
                      {ranges[i] ? ` · ${ranges[i].label}` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn ghost"
                disabled={clipIndex >= media.length - 1}
                onClick={() => selectClip(clipIndex + 1)}
                aria-label="Следующий клип"
              >
                →
              </button>
            </div>
          )}

          <label className="preview-scrub">
            Таймлайн · {fmt(scrub)} с / {fmt(maxT)} с
            <input
              type="range"
              min={0}
              max={maxT}
              step={0.1}
              value={Math.min(scrub, maxT)}
              onChange={(e) => setScrubPersist(Number(e.target.value))}
            />
          </label>

          <p className="muted small preview-status">
            {zone === 'opening' && <>Opening 0–{fmt(opening)} с</>}
            {zone === 'credits' && (
              <>
                Титры {fmt(mediaEnd)}–{fmt(totalEnd)} с
              </>
            )}
            {zone === 'media' && activeClip && (
              <>
                Клип {clipIndex + 1}/{media.length}: {activeClip.name}
                {texts.length > 0
                  ? ` · текст: ${texts.length}`
                  : ' · нет активных текстов'}
              </>
            )}
            {zone === 'empty' && <>Нет медиа</>}
          </p>
        </div>
      </div>
    </section>
  )
}
