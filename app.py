"""Streamlit app: vertical Instagram Reels from photos."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from reels.animations import PHOTO_ANIMATIONS, TEXT_ANIMATIONS
from reels.generator import ReelsConfig, SlideConfig, TextBlock, generate_reels
from reels.colors import DEFAULT_BG_ALPHA, DEFAULT_BG_COLOR, DEFAULT_FONT_COLOR
from reels.timing import TEXT_GAP_SEC, compute_slide_duration, schedule_texts
from reels.watermark import POSITIONS
from reels.corner_text import CORNER_POSITIONS, CornerTextBlock
from reels.watermark_reels import (
    WatermarkMediaItem,
    WatermarkReelsConfig,
    generate_watermark_reels,
    media_kind,
    safe_media_kind,
)
from reels.persistence import (
    AUTOSAVE_INTERVAL_SEC,
    build_snapshot_payload,
    cleanup_expired,
    ensure_session_id,
    list_snapshots,
    load_snapshot,
    media_paths_exist,
    persist_upload,
    should_autosave,
    write_snapshot,
)
from datetime import timedelta
import time

st.set_page_config(
    page_title="RealsMaker — Instagram Reels",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 RealsMaker")
st.caption("Вертикальные Reels (1080×1920) из фотографий с музыкой и анимацией")


def _color_hex(color_picker: str, alpha: int = DEFAULT_BG_ALPHA) -> str:
    h = color_picker.lstrip("#")
    if len(h) == 6:
        return f"#{h}{alpha:02X}"
    return color_picker


def _default_text_block() -> dict:
    font = st.session_state.get("default_font_color", DEFAULT_FONT_COLOR)
    bg = st.session_state.get("default_bg_color", DEFAULT_BG_COLOR)
    alpha = st.session_state.get("default_bg_alpha", DEFAULT_BG_ALPHA)
    return {
        "text": "",
        "font_color": font,
        "bg_color": _color_hex(bg, alpha),
        "duration": 2.5,
        "animation": "fade_in",
        "position": "bottom",
        "font_size": 0,  # 0 = auto
    }


def _default_slide() -> dict:
    return {
        "image_url": "",
        "photo_animation": "ken_burns",
        "texts": [_default_text_block()],
    }


if "slides" not in st.session_state:
    st.session_state.slides = [_default_slide()]


def _default_reals_text_block() -> dict:
    return {
        "text": "",
        "start_time": 0.0,
        "duration": 3.0,
        "position": "bottom_right",
        "font_size": 0,  # 0 = auto
    }


if "reals_text_blocks" not in st.session_state:
    st.session_state.reals_text_blocks = []

if "session_id" not in st.session_state:
    st.session_state.session_id = ensure_session_id(None)
    cleanup_expired()

if "reals_media" not in st.session_state:
    st.session_state.reals_media = []
if "reals_watermark" not in st.session_state:
    st.session_state.reals_watermark = None
if "static_media" not in st.session_state:
    st.session_state.static_media = []
if "last_autosave_ts" not in st.session_state:
    st.session_state.last_autosave_ts = None
if "last_autosave_path" not in st.session_state:
    st.session_state.last_autosave_path = None


def _collect_autosave_state() -> dict:
    return {
        "session_id": st.session_state.session_id,
        "youtube_url": st.session_state.get("youtube_url", ""),
        "music_start": st.session_state.get("music_start", 0.0),
        "music_end": st.session_state.get("music_end"),
        "fit_percent": st.session_state.get("fit_percent", 98),
        "default_font_color": st.session_state.get("default_font_color", DEFAULT_FONT_COLOR),
        "default_bg_color": st.session_state.get("default_bg_color", DEFAULT_BG_COLOR),
        "default_bg_alpha": st.session_state.get("default_bg_alpha", DEFAULT_BG_ALPHA),
        "slides": st.session_state.get("slides", []),
        "reals_photo_duration": st.session_state.get("reals_photo_duration", 3.0),
        "reals_wm_position": st.session_state.get("reals_wm_position", "bottom_right"),
        "reals_wm_scale": st.session_state.get("reals_wm_scale", 22),
        "reals_wm_opacity": st.session_state.get("reals_wm_opacity", 92),
        "reals_opening_enabled": st.session_state.get("reals_opening_enabled", False),
        "reals_opening_duration": st.session_state.get("reals_opening_duration", 2.0),
        "reals_credits_enabled": st.session_state.get("reals_credits_enabled", False),
        "reals_credits_duration": st.session_state.get("reals_credits_duration", 3.0),
        "reals_text_blocks": st.session_state.get("reals_text_blocks", []),
        "reals_media": st.session_state.get("reals_media", []),
        "reals_watermark": st.session_state.get("reals_watermark"),
        "static_slide_duration": st.session_state.get("static_slide_duration", 3.0),
        "static_media": st.session_state.get("static_media", []),
    }


def _run_autosave(*, force: bool = False) -> Path | None:
    if not force and not should_autosave(st.session_state.last_autosave_ts):
        return None
    payload = build_snapshot_payload(_collect_autosave_state())
    path = write_snapshot(payload)
    st.session_state.last_autosave_ts = time.time()
    st.session_state.last_autosave_path = str(path)
    return path


def _apply_snapshot(data: dict) -> None:
    if "session_id" in data and data["session_id"]:
        st.session_state.session_id = str(data["session_id"])
    if "slides" in data:
        st.session_state.slides = data["slides"]
    for key in (
        "youtube_url",
        "music_start",
        "music_end",
        "fit_percent",
        "default_font_color",
        "default_bg_color",
        "default_bg_alpha",
    ):
        if key in data and data[key] is not None:
            st.session_state[key] = data[key]
    reals = data.get("reals") or {}
    if reals:
        st.session_state.reals_photo_duration = reals.get("photo_duration", 3.0)
        st.session_state.reals_wm_position = reals.get("wm_position", "bottom_right")
        st.session_state.reals_wm_scale = reals.get("wm_scale", 22)
        st.session_state.reals_wm_opacity = reals.get("wm_opacity", 92)
        st.session_state.reals_opening_enabled = reals.get("opening_enabled", False)
        st.session_state.reals_opening_duration = reals.get("opening_duration", 2.0)
        st.session_state.reals_credits_enabled = reals.get("credits_enabled", False)
        st.session_state.reals_credits_duration = reals.get("credits_duration", 3.0)
        st.session_state.reals_text_blocks = reals.get("text_blocks") or []
        st.session_state.reals_media = reals.get("media") or []
        st.session_state.reals_watermark = reals.get("watermark")
    static = data.get("static") or {}
    if static:
        st.session_state.static_slide_duration = static.get("slide_duration", 3.0)
        st.session_state.static_media = static.get("media") or []
    # legacy v1: only slides
    if "slides" in data and "reals" not in data and "version" not in data:
        pass


def _preview_slide_duration(slide: dict) -> float:
    blocks = [
        TextBlock(
            text=tb.get("text", ""),
            duration=float(tb.get("duration", 2.5)),
        )
        for tb in slide.get("texts", [])
        if tb.get("text", "").strip()
    ]
    return compute_slide_duration(schedule_texts(blocks))


with st.sidebar:
    st.header("Музыка")
    youtube_url = st.text_input(
        "Ссылка YouTube",
        placeholder="https://www.youtube.com/watch?v=...",
    )
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        music_start = st.number_input("Начало (сек)", min_value=0.0, value=0.0, step=0.5)
    with col_m2:
        music_end_val = st.number_input(
            "Конец (сек, 0 = до конца ролика)",
            min_value=0.0,
            value=0.0,
            step=0.5,
        )
    music_end = music_end_val if music_end_val > music_start else None

    st.divider()
    st.header("Кадр")
    fit_percent = st.slider(
        "Вписывание картинки (%)",
        min_value=70,
        max_value=99,
        value=int(st.session_state.get("fit_percent", 98)),
        help="Сколько кадра занимает фото. Меньше — больше полей по краям.",
    )
    st.session_state.fit_percent = fit_percent
    fit_ratio = fit_percent / 100.0

    st.divider()
    st.header("Фотографии")
    bulk_urls = st.text_area(
        "Ссылки на фото (по одной на строку)",
        height=120,
        placeholder="https://example.com/photo1.jpg\nhttps://example.com/photo2.jpg",
    )
    if st.button("Добавить фото из списка", use_container_width=True):
        urls = [u.strip() for u in bulk_urls.splitlines() if u.strip()]
        for url in urls:
            slide = _default_slide()
            slide["image_url"] = url
            st.session_state.slides.append(slide)
        st.rerun()

    if st.button("➕ Пустой слайд", use_container_width=True):
        st.session_state.slides.append(_default_slide())
        st.rerun()

    st.divider()
    st.header("Цвета по умолчанию")
    default_bg_alpha = st.slider(
        "Прозрачность фона текста",
        0,
        255,
        st.session_state.get("default_bg_alpha", DEFAULT_BG_ALPHA),
    )
    st.session_state.default_bg_alpha = default_bg_alpha

    def_font = st.session_state.get("default_font_color", DEFAULT_FONT_COLOR)
    def_bg = st.session_state.get("default_bg_color", DEFAULT_BG_COLOR)
    fc_col, swap_col, bg_col = st.columns([4, 1, 4])
    with fc_col:
        picked_font = st.color_picker("Шрифт", def_font, key="sidebar_font")
    with swap_col:
        st.write("")
        if st.button("⇄", key="swap_sidebar_colors", help="Поменять шрифт и фон местами"):
            st.session_state.default_font_color = def_bg
            st.session_state.default_bg_color = def_font
            st.rerun()
    with bg_col:
        picked_bg = st.color_picker("Фон текста", def_bg, key="sidebar_bg")

    st.session_state.default_font_color = picked_font
    st.session_state.default_bg_color = picked_bg
    default_font = picked_font
    default_bg = picked_bg


# Persist sidebar inputs for autosave / restore
st.session_state.youtube_url = youtube_url.strip()
st.session_state.music_start = float(music_start)
st.session_state.music_end = music_end

# Background autosave tick (Streamlit ≥1.33 fragment)
try:
    @st.fragment(run_every=timedelta(seconds=60))
    def _autosave_heartbeat() -> None:
        path = _run_autosave(force=False)
        if path:
            st.caption(f"Автосохранение: `{path.name}`")

    _autosave_heartbeat()
except TypeError:
    # Older Streamlit without run_every — save on interactions only
    _run_autosave(force=False)

tab_slides, tab_static, tab_reals, tab_json, tab_help = st.tabs(
    ["Слайды", "Статичный Reels", "Reals", "JSON", "Справка"]
)

with tab_help:
    st.markdown(
        f"""
### Как пользоваться

1. Укажите **YouTube**-ссылку и таймкоды музыки в боковой панели.
2. Добавьте **ссылки на фото** и тексты для каждого слайда.
3. Тексты на слайде идут **строго по очереди** с паузой **{TEXT_GAP_SEC} с** между ними.
4. **Длительность слайда** считается автоматически по текстам.
5. **Вписывание** (70–99%) — в боковой панели; поля — цвет `{DEFAULT_BG_COLOR}`.
6. Нажмите **Создать Reels** и скачайте MP4.
7. Вкладка **JSON**: автосохранение каждые 3 мин в tmp (6 ч хранения); можно восстановить слепок после сбоя.

### Вкладка «Статичный Reels»

Загрузка вертикальных картинок с диска, одинаковая длительность, лёгкий Ken Burns, без текста.

### Вкладка «Reals»

Загрузка **фото и видео** с вотермаркой. Видео проигрывается как есть (со звуком, если есть).  
Фото показывается заданное время. Кадр вписывается в 1080×1920, пустоты — `{DEFAULT_BG_COLOR}`.  
До 10 **текстовых блоков** по таймлайну: верх/низ × лево/право, анимация разворота от края.  
**Opening / Титры** — вотермарка по центру на фоне `{DEFAULT_BG_COLOR}`.

### Цвета по умолчанию

Шрифт `{DEFAULT_FONT_COLOR}`, фон подписи `{DEFAULT_BG_COLOR}` (кнопка ⇄ меняет их местами).
        """
    )

with tab_static:
    st.markdown(
        f"""
Загрузите **вертикальные** изображения (9:16) с компьютера.  
Вписывание — **{fit_percent}%** (настройка в боковой панели). Пустые поля — `{DEFAULT_BG_COLOR}`.  
Лёгкое движение Ken Burns, без текста. Одинаковая длительность каждого кадра.  
Музыка — из боковой панели (YouTube), если указана.
        """
    )

    static_duration = st.number_input(
        "Длительность каждого фото (сек)",
        min_value=0.5,
        max_value=30.0,
        value=float(st.session_state.get("static_slide_duration", 3.0)),
        step=0.5,
        key="static_slide_duration_input",
    )
    st.session_state.static_slide_duration = static_duration

    uploaded_images = st.file_uploader(
        "Изображения",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="static_images_uploader",
    )

    if uploaded_images:
        st.session_state.static_media = [
            persist_upload(
                st.session_state.session_id,
                filename=upl.name,
                data=upl.getvalue(),
                subdir="static",
                index=i,
            )
            for i, upl in enumerate(uploaded_images)
        ]
        _run_autosave(force=False)
        total_sec = len(uploaded_images) * static_duration
        st.caption(
            f"Фото: **{len(uploaded_images)}** · длительность ролика ≈ **{total_sec:.1f} с** · сохранено в tmp"
        )
        preview_cols = st.columns(min(len(uploaded_images), 5))
        for i, upl in enumerate(uploaded_images):
            with preview_cols[i % len(preview_cols)]:
                st.image(upl, caption=upl.name, use_container_width=True)
    elif st.session_state.static_media:
        ok, missing = media_paths_exist(st.session_state.static_media)
        st.info(f"Восстановленные фото из tmp: **{ok}** (нет файлов: {missing})")

    if st.session_state.get("rendered_static_video"):
        st.success("Статичный Reels готов.")
        st.download_button(
            label="Скачать static_reels.mp4",
            data=st.session_state.rendered_static_video,
            file_name="static_reels.mp4",
            mime="video/mp4",
            type="primary",
            use_container_width=True,
            key="download_static_reels",
        )

    if st.button("🎬 Создать статичный Reels", type="primary", use_container_width=True):
        if not uploaded_images:
            st.error("Загрузите хотя бы одно изображение.")
        else:
            config = ReelsConfig(
                slides=[],
                youtube_url=youtube_url.strip(),
                music_start=music_start,
                music_end=music_end,
            )
            progress = st.progress(0, text="Старт...")
            status = st.empty()

            def on_progress(msg: str) -> None:
                status.info(msg)

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                slides_cfg: list[SlideConfig] = []
                for i, upl in enumerate(uploaded_images):
                    ext = Path(upl.name).suffix or ".jpg"
                    img_path = tmp_path / f"{i:03d}{ext}"
                    img_path.write_bytes(upl.getvalue())
                    slides_cfg.append(
                        SlideConfig(
                            image_path=str(img_path),
                            duration=static_duration,
                            photo_animation="ken_burns_subtle",
                            texts=[],
                            frame_mode="fit",
                            fit_ratio=fit_ratio,
                        )
                    )
                config.slides = slides_cfg
                out = tmp_path / "static_reels.mp4"
                work = tmp_path / "work"
                try:
                    generate_reels(config, out, work, progress_callback=on_progress)
                    progress.progress(100, text="Готово!")
                    status.empty()
                    st.session_state.rendered_static_video = out.read_bytes()
                    st.rerun()
                except Exception as e:
                    progress.empty()
                    status.empty()
                    st.error(f"Ошибка: {e}")
                    st.info(
                        "Проверьте, что установлены ffmpeg и (для музыки) yt-dlp."
                    )

with tab_reals:
    st.markdown(
        f"""
Загрузите **фото и/или видео** и **вотермарку** (PNG с прозрачностью).  
Видео проигрывается как видео; кадр вписывается в Reels 1080×1920, пустоты — `{DEFAULT_BG_COLOR}`.  
Фото показывается заданное время. **Opening** и **Титры** — вотермарка по центру на фирменном фоне.  
До **10 текстовых блоков** по таймлайну (углы кадра).  
Музыка — из боковой панели (YouTube), если указана (заменяет звук видео).
        """
    )

    col_wm, col_dur = st.columns(2)
    with col_wm:
        watermark_file = st.file_uploader(
            "Вотермарка (PNG/JPG/WebP)",
            type=["png", "jpg", "jpeg", "webp"],
            key="reals_watermark_uploader",
        )
    with col_dur:
        photo_duration = st.number_input(
            "Длительность фото в Reels (сек)",
            min_value=0.5,
            max_value=30.0,
            value=float(st.session_state.get("reals_photo_duration", 3.0)),
            step=0.5,
            key="reals_photo_duration_input",
        )
        st.session_state.reals_photo_duration = photo_duration

    wm_pos_keys = list(POSITIONS.keys())
    wm_default = st.session_state.get("reals_wm_position", "bottom_right")
    if wm_default not in wm_pos_keys:
        wm_default = "bottom_right"
    wm_col1, wm_col2, wm_col3 = st.columns(3)
    with wm_col1:
        wm_position = st.selectbox(
            "Позиция вотермарки",
            wm_pos_keys,
            index=wm_pos_keys.index(wm_default),
            format_func=lambda k: POSITIONS[k],
            key="reals_wm_position_select",
        )
        st.session_state.reals_wm_position = wm_position
    with wm_col2:
        wm_scale = st.slider(
            "Размер вотермарки (% ширины кадра)",
            min_value=8,
            max_value=50,
            value=int(st.session_state.get("reals_wm_scale", 22)),
            key="reals_wm_scale_slider",
        )
        st.session_state.reals_wm_scale = wm_scale
    with wm_col3:
        wm_opacity = st.slider(
            "Прозрачность вотермарки (%)",
            min_value=10,
            max_value=100,
            value=int(st.session_state.get("reals_wm_opacity", 92)),
            key="reals_wm_opacity_slider",
            help="Только на фото/видео. Opening и Титры всегда без прозрачности.",
        )
        st.session_state.reals_wm_opacity = wm_opacity

    st.divider()
    st.markdown(f"**Opening / Титры** · фон `{DEFAULT_BG_COLOR}`, вотермарка по центру без прозрачности (PNG 100%)")
    splash_col1, splash_col2 = st.columns(2)
    with splash_col1:
        opening_enabled = st.checkbox(
            "Opening",
            value=bool(st.session_state.get("reals_opening_enabled", False)),
            key="reals_opening_checkbox",
        )
        st.session_state.reals_opening_enabled = opening_enabled
        opening_duration = st.number_input(
            "Длительность Opening (сек)",
            min_value=0.5,
            max_value=30.0,
            value=float(st.session_state.get("reals_opening_duration", 2.0)),
            step=0.5,
            disabled=not opening_enabled,
            key="reals_opening_duration_input",
        )
        if opening_enabled:
            st.session_state.reals_opening_duration = opening_duration
    with splash_col2:
        credits_enabled = st.checkbox(
            "Титры",
            value=bool(st.session_state.get("reals_credits_enabled", False)),
            key="reals_credits_checkbox",
        )
        st.session_state.reals_credits_enabled = credits_enabled
        credits_duration = st.number_input(
            "Длительность Титры (сек)",
            min_value=0.5,
            max_value=30.0,
            value=float(st.session_state.get("reals_credits_duration", 3.0)),
            step=0.5,
            disabled=not credits_enabled,
            key="reals_credits_duration_input",
        )
        if credits_enabled:
            st.session_state.reals_credits_duration = credits_duration

    st.divider()
    st.markdown(
        f"**Текстовые блоки** (до 10) · шрифт `{DEFAULT_FONT_COLOR}`, фон `{DEFAULT_BG_COLOR}`"
    )
    corner_pos_keys = list(CORNER_POSITIONS.keys())
    texts_to_remove: list[int] = []

    for t_idx, tb in enumerate(st.session_state.reals_text_blocks):
        with st.expander(f"Текст {t_idx + 1}", expanded=t_idx == 0 and bool(tb.get("text"))):
            tb["text"] = st.text_area(
                "Текст",
                value=tb.get("text", ""),
                height=68,
                key=f"reals_txt_{t_idx}",
            )
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                tb["start_time"] = st.number_input(
                    "Старт на таймлайне (сек)",
                    min_value=0.0,
                    max_value=600.0,
                    value=float(tb.get("start_time", 0.0)),
                    step=0.1,
                    key=f"reals_tstart_{t_idx}",
                )
            with tc2:
                tb["duration"] = st.number_input(
                    "Длительность (сек)",
                    min_value=0.3,
                    max_value=60.0,
                    value=float(tb.get("duration", 3.0)),
                    step=0.1,
                    key=f"reals_tdur_{t_idx}",
                )
            with tc3:
                pos_cur = tb.get("position", "bottom_right")
                if pos_cur not in corner_pos_keys:
                    pos_cur = "bottom_right"
                tb["position"] = st.selectbox(
                    "Угол",
                    corner_pos_keys,
                    index=corner_pos_keys.index(pos_cur),
                    format_func=lambda k: CORNER_POSITIONS[k],
                    key=f"reals_tpos_{t_idx}",
                )
            tb["font_size"] = st.number_input(
                "Размер шрифта (px)",
                min_value=0,
                max_value=200,
                value=int(tb.get("font_size") or 0),
                step=1,
                key=f"reals_tfs_{t_idx}",
                help="0 = автоподбор. Шрифт всегда Jost Bold.",
            )
            end_t = float(tb["start_time"]) + float(tb["duration"])
            fs = int(tb.get("font_size") or 0)
            fs_label = "авто" if fs <= 0 else f"{fs} px"
            st.caption(f"На экране: **{tb['start_time']:.1f}–{end_t:.1f} с** · шрифт Jost · {fs_label}")
            if st.button("Удалить блок", key=f"reals_rm_txt_{t_idx}"):
                texts_to_remove.append(t_idx)

    for ti in reversed(texts_to_remove):
        st.session_state.reals_text_blocks.pop(ti)
        st.rerun()

    add_txt_col, _ = st.columns([1, 3])
    with add_txt_col:
        if len(st.session_state.reals_text_blocks) < 10:
            if st.button("➕ Добавить текстовый блок", key="reals_add_text"):
                st.session_state.reals_text_blocks.append(_default_reals_text_block())
                st.rerun()
        else:
            st.caption("Достигнут лимит: 10 текстовых блоков.")

    uploaded_media = st.file_uploader(
        "Фото и видео (порядок загрузки = порядок в Reels)",
        type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm", "m4v"],
        accept_multiple_files=True,
        key="reals_media_uploader",
    )

    if uploaded_media:
        st.session_state.reals_media = [
            persist_upload(
                st.session_state.session_id,
                filename=upl.name,
                data=upl.getvalue(),
                subdir="reals",
                index=i,
            )
            for i, upl in enumerate(uploaded_media)
        ]
        n_img = sum(
            1 for f in uploaded_media if safe_media_kind(Path(f.name)) == "image"
        )
        n_vid = sum(
            1 for f in uploaded_media if safe_media_kind(Path(f.name)) == "video"
        )
        est_photo_sec = n_img * photo_duration
        st.caption(
            f"Файлов: **{len(uploaded_media)}** "
            f"(фото: {n_img}, видео: {n_vid}) · фото ≈ **{est_photo_sec:.1f} с** + длительность видео · сохранено в tmp"
        )
        preview_cols = st.columns(min(len(uploaded_media), 4))
        for i, upl in enumerate(uploaded_media):
            with preview_cols[i % len(preview_cols)]:
                kind = safe_media_kind(Path(upl.name))
                if kind == "image":
                    st.image(upl, caption=upl.name, use_container_width=True)
                elif kind == "video":
                    st.video(upl)
                    st.caption(upl.name)
                else:
                    st.warning(f"Неподдерживаемый формат: {upl.name}")
        _run_autosave(force=False)
    elif st.session_state.reals_media:
        ok, missing = media_paths_exist(st.session_state.reals_media)
        st.info(f"Медиа из tmp (после восстановления): **{ok}** ок, **{missing}** нет")

    if watermark_file:
        st.session_state.reals_watermark = persist_upload(
            st.session_state.session_id,
            filename=watermark_file.name,
            data=watermark_file.getvalue(),
            subdir="reals",
        )
        st.image(watermark_file, caption="Вотермарка", width=200)
        _run_autosave(force=False)
    elif st.session_state.reals_watermark and Path(st.session_state.reals_watermark.get("path", "")).is_file():
        st.caption(f"Вотермарка из tmp: `{Path(st.session_state.reals_watermark['path']).name}`")
        try:
            st.image(st.session_state.reals_watermark["path"], caption="Вотермарка (tmp)", width=200)
        except Exception:
            pass

    if st.session_state.get("rendered_reals_video"):
        st.success("Reals с вотермаркой готов.")
        st.download_button(
            label="Скачать reals_watermark.mp4",
            data=st.session_state.rendered_reals_video,
            file_name="reals_watermark.mp4",
            mime="video/mp4",
            type="primary",
            use_container_width=True,
            key="download_reals_watermark",
        )

    has_wm = bool(watermark_file) or (
        st.session_state.reals_watermark
        and Path(st.session_state.reals_watermark.get("path", "")).is_file()
    )
    has_media = bool(uploaded_media) or (
        st.session_state.reals_media
        and any(Path(d.get("path", "")).is_file() for d in st.session_state.reals_media)
    )

    if st.button("🎬 Создать Reals с вотермаркой", type="primary", use_container_width=True):
        if not has_wm:
            st.error("Загрузите файл вотермарки (или восстановите snapshot с вотермаркой).")
        elif not has_media:
            st.error("Загрузите хотя бы одно фото или видео (или восстановите snapshot).")
        else:
            progress = st.progress(0, text="Старт...")
            status = st.empty()

            def on_progress(msg: str) -> None:
                status.info(msg)

            _run_autosave(force=True)
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)

                # Prefer durable tmp media; fall back to fresh uploads
                wm_desc = st.session_state.get("reals_watermark")
                if wm_desc and Path(wm_desc.get("path", "")).is_file():
                    wm_path = Path(wm_desc["path"])
                elif watermark_file:
                    wm_path = tmp_path / f"watermark{Path(watermark_file.name).suffix or '.png'}"
                    wm_path.write_bytes(watermark_file.getvalue())
                else:
                    st.error("Вотермарка не найдена.")
                    st.stop()

                items: list[WatermarkMediaItem] = []
                media_descs = st.session_state.get("reals_media") or []
                if media_descs and all(Path(d.get("path", "")).is_file() for d in media_descs):
                    for d in media_descs:
                        media_path = Path(d["path"])
                        kind = media_kind(media_path)
                        items.append(
                            WatermarkMediaItem(
                                path=media_path,
                                kind=kind,
                                duration=photo_duration if kind == "image" else None,
                            )
                        )
                elif uploaded_media:
                    for i, upl in enumerate(uploaded_media):
                        ext = Path(upl.name).suffix or ".bin"
                        media_path = tmp_path / f"{i:03d}{ext}"
                        media_path.write_bytes(upl.getvalue())
                        kind = media_kind(media_path)
                        items.append(
                            WatermarkMediaItem(
                                path=media_path,
                                kind=kind,
                                duration=photo_duration if kind == "image" else None,
                            )
                        )
                else:
                    st.error("Медиафайлы не найдены.")
                    st.stop()

                config = WatermarkReelsConfig(
                    items=items,
                    watermark_path=wm_path,
                    photo_duration=photo_duration,
                    fit_ratio=fit_ratio,
                    watermark_position=wm_position,
                    watermark_scale=wm_scale / 100.0,
                    watermark_opacity=wm_opacity / 100.0,
                    youtube_url=youtube_url.strip(),
                    music_start=music_start,
                    music_end=music_end,
                    text_blocks=[
                        CornerTextBlock(
                            text=tb.get("text", ""),
                            start_time=float(tb.get("start_time", 0.0)),
                            duration=float(tb.get("duration", 3.0)),
                            position=tb.get("position", "bottom_right"),
                            font_size=(int(tb["font_size"]) if int(tb.get("font_size") or 0) > 0 else None),
                        )
                        for tb in st.session_state.reals_text_blocks
                        if tb.get("text", "").strip()
                    ],
                    opening_enabled=opening_enabled,
                    opening_duration=float(opening_duration) if opening_enabled else 0.0,
                    credits_enabled=credits_enabled,
                    credits_duration=float(credits_duration) if credits_enabled else 0.0,
                )
                out = tmp_path / "reals_watermark.mp4"
                work = tmp_path / "work"
                try:
                    generate_watermark_reels(config, out, work, progress_callback=on_progress)
                    progress.progress(100, text="Готово!")
                    status.empty()
                    st.session_state.rendered_reals_video = out.read_bytes()
                    st.rerun()
                except Exception as e:
                    progress.empty()
                    status.empty()
                    st.error(f"Ошибка: {e}")
                    st.info(
                        "Проверьте: ffmpeg и yt-dlp установлены, файлы не повреждены."
                    )

with tab_json:
    st.markdown(
        """
**Экспорт / импорт / автосохранение**

Каждые **3 минуты** (и при загрузке медиа) в `tmp/realsmaker/snapshots/` пишется слепок  
`reals_autosave_YYYY-MM-DD_HH-MM-SS.json` со всеми настройками и путями к медиа.  
Медиа лежит в `tmp/realsmaker/media/<session>/` и живёт **6 часов**, потом чистится.
        """
    )

    payload = build_snapshot_payload(_collect_autosave_state())
    col_dl, col_force = st.columns([2, 1])
    with col_dl:
        st.download_button(
            "Скачать текущий JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"reels_config_{st.session_state.session_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_force:
        if st.button("💾 Сохранить слепок сейчас", use_container_width=True):
            p = _run_autosave(force=True)
            if p:
                st.success(f"Сохранено: `{p.name}`")

    if st.session_state.last_autosave_path:
        st.caption(f"Последний autosave: `{Path(st.session_state.last_autosave_path).name}`")

    st.divider()
    st.subheader("Восстановить из autosave (tmp)")
    snaps = list_snapshots()
    if not snaps:
        st.info("Пока нет слепков в tmp. Они появятся через ~3 минуты работы или по кнопке выше.")
    else:
        labels = [f"{s['label']}  ·  {s['name']}" for s in snaps]
        choice = st.selectbox("Файл по дате/времени", range(len(snaps)), format_func=lambda i: labels[i])
        selected = snaps[choice]
        ok_m, miss_m = media_paths_exist(
            (load_snapshot(selected["path"]).get("reals") or {}).get("media")
        )
        st.caption(f"Медиа в слепке: доступно **{ok_m}**, отсутствует **{miss_m}**")
        if st.button("↩ Импортировать выбранный слепок", type="primary"):
            data = load_snapshot(selected["path"])
            _apply_snapshot(data)
            st.success(f"Загружено: `{selected['name']}`. Откройте вкладку Reals / Слайды.")
            st.rerun()

    st.divider()
    st.subheader("Загрузить JSON с диска")
    uploaded = st.file_uploader("JSON (ручной экспорт или autosave)", type=["json"], key="json_upload")
    if uploaded:
        data = json.load(uploaded)
        if st.button("Применить загруженный JSON"):
            _apply_snapshot(data)
            st.success("Конфигурация применена.")
            st.rerun()

with tab_slides:
    slides_to_remove: list[int] = []

    for idx, slide in enumerate(st.session_state.slides):
        auto_dur = _preview_slide_duration(slide)
        with st.expander(f"Слайд {idx + 1} · ~{auto_dur:.1f} с", expanded=idx == 0):
            c1, c2 = st.columns([3, 1])
            with c1:
                slide["image_url"] = st.text_input(
                    "Ссылка на фото",
                    value=slide.get("image_url", ""),
                    key=f"img_{idx}",
                )
            with c2:
                anim_keys = list(PHOTO_ANIMATIONS.keys())
                current = slide.get("photo_animation", "ken_burns")
                if current not in anim_keys:
                    current = anim_keys[0]
                slide["photo_animation"] = st.selectbox(
                    "Анимация фото",
                    anim_keys,
                    index=anim_keys.index(current),
                    format_func=lambda k: PHOTO_ANIMATIONS[k],
                    key=f"panim_{idx}",
                )

            st.caption(
                f"Длительность слайда: **{auto_dur:.1f} с** (авто) · между текстами **{TEXT_GAP_SEC} с**"
            )

            if slide.get("image_url"):
                try:
                    from reels.images import load_image

                    preview = load_image(slide["image_url"])
                    preview.thumbnail((270, 480))
                    st.image(preview, caption="Превью")
                except Exception as e:
                    st.warning(f"Не удалось загрузить превью: {e}")

            st.markdown("**Тексты на слайде** (по очереди)")
            texts_to_remove: list[int] = []
            if "texts" not in slide:
                slide["texts"] = []

            running_offset = 0.0
            for t_idx, tb in enumerate(slide["texts"]):
                if t_idx > 0:
                    prev_dur = float(slide["texts"][t_idx - 1].get("duration", 2.5))
                    running_offset += prev_dur + TEXT_GAP_SEC

                st.markdown(
                    f"---\n**Текст {t_idx + 1}** · старт ~{running_offset:.1f} с"
                )
                tb["text"] = st.text_area(
                    "Текст",
                    value=tb.get("text", ""),
                    height=68,
                    key=f"txt_{idx}_{t_idx}",
                )

                font_val = tb.get("font_color", default_font)
                bg_val = tb.get("bg_color", _color_hex(default_bg, default_bg_alpha))
                swap_key = f"swap_{idx}_{t_idx}"

                fc, swap_c, bg_c = st.columns([4, 1, 4])
                with fc:
                    font_color = st.color_picker(
                        "Шрифт", font_val, key=f"fc_{idx}_{t_idx}"
                    )
                with swap_c:
                    st.write("")
                    if st.button("⇄", key=swap_key, help="Поменять шрифт и фон местами"):
                        tb["font_color"] = (
                            bg_val[:7]
                            if bg_val.startswith("#") and len(bg_val) >= 7
                            else default_bg
                        )
                        tb["bg_color"] = _color_hex(font_val[:7], default_bg_alpha)
                        st.rerun()
                with bg_c:
                    bg_pick = st.color_picker(
                        "Фон",
                        bg_val[:7]
                        if bg_val.startswith("#") and len(bg_val) >= 7
                        else default_bg,
                        key=f"bg_{idx}_{t_idx}",
                    )
                tb["font_color"] = font_color
                tb["bg_color"] = _color_hex(bg_pick, default_bg_alpha)

                r3, r4 = st.columns(2)
                with r3:
                    tb["duration"] = st.number_input(
                        "Показ (сек)",
                        min_value=0.3,
                        max_value=30.0,
                        value=float(tb.get("duration", 2.5)),
                        step=0.1,
                        key=f"tdur_{idx}_{t_idx}",
                    )
                with r4:
                    text_anim_keys = list(TEXT_ANIMATIONS.keys())
                    tcur = tb.get("animation", "fade_in")
                    if tcur not in text_anim_keys:
                        tcur = text_anim_keys[0]
                    tb["animation"] = st.selectbox(
                        "Анимация текста",
                        text_anim_keys,
                        index=text_anim_keys.index(tcur),
                        format_func=lambda k: TEXT_ANIMATIONS[k],
                        key=f"tanim_{idx}_{t_idx}",
                    )

                pos_options = ["top", "center", "bottom"]
                pos_labels = {"top": "Вверху", "center": "По центру", "bottom": "Внизу"}
                pcur = tb.get("position", "bottom")
                if pcur not in pos_options:
                    pcur = "bottom"
                tb["position"] = st.selectbox(
                    "Позиция",
                    pos_options,
                    index=pos_options.index(pcur),
                    format_func=lambda k: pos_labels[k],
                    key=f"tpos_{idx}_{t_idx}",
                )
                tb["font_size"] = st.number_input(
                    "Размер шрифта (px)",
                    min_value=0,
                    max_value=200,
                    value=int(tb.get("font_size") or 0),
                    step=1,
                    key=f"tfs_{idx}_{t_idx}",
                    help="0 = автоподбор. Шрифт всегда Jost Bold.",
                )

                if st.button("Удалить текст", key=f"rm_txt_{idx}_{t_idx}"):
                    texts_to_remove.append(t_idx)

            for ti in reversed(texts_to_remove):
                slide["texts"].pop(ti)

            b1, b2 = st.columns(2)
            with b1:
                if st.button("➕ Добавить текст", key=f"add_txt_{idx}"):
                    slide["texts"].append(_default_text_block())
                    st.rerun()
            with b2:
                if st.button("🗑 Удалить слайд", key=f"rm_slide_{idx}"):
                    slides_to_remove.append(idx)

    for si in reversed(slides_to_remove):
        st.session_state.slides.pop(si)
        st.rerun()

    st.divider()

    if st.session_state.get("rendered_video"):
        st.success("Reels готов.")
        st.download_button(
            label="Скачать instagram_reels.mp4",
            data=st.session_state.rendered_video,
            file_name="instagram_reels.mp4",
            mime="video/mp4",
            type="primary",
            use_container_width=True,
        )

    if st.button("🎬 Создать Reels", type="primary", use_container_width=True):
        valid_slides = [s for s in st.session_state.slides if s.get("image_url", "").strip()]
        if not valid_slides:
            st.error("Добавьте хотя бы один слайд со ссылкой на фото.")
        else:
            slides_cfg = []
            for s in valid_slides:
                raw_texts = [
                    TextBlock(
                        text=tb.get("text", ""),
                        font_color=tb.get("font_color", default_font),
                        bg_color=tb.get("bg_color", _color_hex(default_bg, default_bg_alpha)),
                        duration=float(tb.get("duration", 2.5)),
                        animation=tb.get("animation", "fade_in"),
                        position=tb.get("position", "bottom"),
                        font_size=(int(tb["font_size"]) if int(tb.get("font_size") or 0) > 0 else None),
                    )
                    for tb in s.get("texts", [])
                    if tb.get("text", "").strip()
                ]
                scheduled = schedule_texts(raw_texts)
                slides_cfg.append(
                    SlideConfig(
                        image_url=s["image_url"].strip(),
                        duration=compute_slide_duration(scheduled),
                        photo_animation=s.get("photo_animation", "ken_burns"),
                        texts=scheduled,
                        frame_mode="fit",
                        fit_ratio=fit_ratio,
                    )
                )

            config = ReelsConfig(
                slides=slides_cfg,
                youtube_url=youtube_url.strip(),
                music_start=music_start,
                music_end=music_end,
            )

            progress = st.progress(0, text="Старт...")
            status = st.empty()

            def on_progress(msg: str) -> None:
                status.info(msg)

            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "reels_output.mp4"
                work = Path(tmp) / "work"
                try:
                    generate_reels(config, out, work, progress_callback=on_progress)
                    progress.progress(100, text="Готово!")
                    status.empty()
                    st.session_state.rendered_video = out.read_bytes()
                    st.rerun()
                except Exception as e:
                    progress.empty()
                    status.empty()
                    st.error(f"Ошибка: {e}")
                    st.info(
                        "Проверьте: ffmpeg и yt-dlp установлены, ссылки на фото открываются, "
                        "YouTube-ссылка корректна."
                    )
