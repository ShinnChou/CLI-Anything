"""Kdenlive CLI - MLT XML generation helpers and timecode conversions."""

import re
import uuid
from typing import Dict, Any, List, Optional


def xml_escape(s: str) -> str:
    """Escape special characters for XML."""
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&apos;")
    return s


def seconds_to_timecode(seconds: float) -> str:
    """Convert seconds (float) to HH:MM:SS.mmm timecode string."""
    if seconds < 0:
        raise ValueError(f"Seconds must be non-negative: {seconds}")
    hours = int(seconds // 3600)
    remainder = seconds - hours * 3600
    minutes = int(remainder // 60)
    remainder = remainder - minutes * 60
    secs = int(remainder)
    millis = int(round((remainder - secs) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def timecode_to_seconds(tc: str) -> float:
    """Convert HH:MM:SS.mmm timecode to seconds (float).

    Also accepts plain float strings.
    """
    # Try plain float first
    try:
        return float(tc)
    except ValueError:
        pass

    pattern = r'^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$'
    m = re.match(pattern, tc)
    if not m:
        raise ValueError(f"Invalid timecode format: {tc}. Expected HH:MM:SS.mmm or seconds.")
    hours = int(m.group(1))
    minutes = int(m.group(2))
    secs = int(m.group(3))
    millis = int(m.group(4)) if m.group(4) else 0
    # Pad millis to 3 digits
    millis_str = m.group(4) if m.group(4) else "0"
    millis = int(millis_str.ljust(3, '0'))
    return hours * 3600 + minutes * 60 + secs + millis / 1000.0


def seconds_to_frames(seconds: float, fps_num: int = 30, fps_den: int = 1) -> int:
    """Convert seconds to frame count."""
    fps = fps_num / max(fps_den, 1)
    return int(round(seconds * fps))


def frames_to_seconds(frames: int, fps_num: int = 30, fps_den: int = 1) -> float:
    """Convert frame count to seconds."""
    fps = fps_num / max(fps_den, 1)
    return frames / fps


def _indent(text: str, level: int) -> str:
    """Indent text by level."""
    prefix = "  " * level
    return prefix + text


def _order_tracks(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order tracks for Kdenlive: audio tracks first, then video tracks."""
    audio = [t for t in tracks if t.get("type") == "audio"]
    video = [t for t in tracks if t.get("type") != "audio"]
    return audio + video


def build_mlt_xml(project: Dict[str, Any]) -> str:
    """Build a complete MLT XML document from a project dictionary.

    Generates valid Kdenlive MLT XML matching the real Kdenlive file format:
    - Separate producer instances for bin (master) vs timeline (service copies)
    - Each track is a tractor wrapping A/B playlists
    - Main tractor references track tractors
    - Internal mix/composite transitions and track filters
    """
    profile = project.get("profile", {})
    width = profile.get("width", 1920)
    height = profile.get("height", 1080)
    fps_num = profile.get("fps_num", 30)
    fps_den = profile.get("fps_den", 1)
    progressive = profile.get("progressive", True)
    dar_num = profile.get("dar_num", 16)
    dar_den = profile.get("dar_den", 9)

    # Calculate SAR (sample aspect ratio)
    sar_num = dar_num * height
    sar_den = dar_den * width

    # Order tracks: audio first, then video (Kdenlive convention)
    tracks = _order_tracks(project.get("tracks", []))

    # Compute timeline duration for black track
    timeline_duration_frames = 0
    for track in tracks:
        for clip_entry in track.get("clips", []):
            clip_end = clip_entry.get("position", 0) + (clip_entry.get("out", 0) - clip_entry.get("in", 0))
            end_frames = seconds_to_frames(clip_end, fps_num, fps_den)
            if end_frames > timeline_duration_frames:
                timeline_duration_frames = end_frames
    if timeline_duration_frames == 0:
        timeline_duration_frames = seconds_to_frames(300, fps_num, fps_den)

    # Build lookup: clip_id -> bin clip data & kdenlive numeric id
    bin_clips = project.get("bin", [])
    clip_kdenlive_ids = {}
    clip_sources = {}
    for idx, clip in enumerate(bin_clips):
        kid = idx + 2  # kdenlive:id starts from 2 (0,1 reserved)
        clip_kdenlive_ids[clip["id"]] = kid
        clip_sources[clip["id"]] = clip

    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<mlt LC_NUMERIC="C" version="7.0.0" '
                 f'title="{xml_escape(project.get("name", "untitled"))}" '
                 f'producer="main_bin">')

    # ── Profile ─────────────────────────────────────────────────
    lines.append(f'  <profile description="{xml_escape(profile.get("name", "custom"))}" '
                 f'width="{width}" height="{height}" '
                 f'progressive="{1 if progressive else 0}" '
                 f'sample_aspect_num="{sar_num}" sample_aspect_den="{sar_den}" '
                 f'display_aspect_num="{dar_num}" display_aspect_den="{dar_den}" '
                 f'frame_rate_num="{fps_num}" frame_rate_den="{fps_den}" '
                 f'colorspace="709"/>')

    # ── Bin producers (master copies, referenced from main_bin) ──
    for clip in bin_clips:
        clip_id = xml_escape(clip["id"])
        source = xml_escape(clip.get("source", ""))
        duration_frames = seconds_to_frames(clip.get("duration", 0), fps_num, fps_den)
        kid = clip_kdenlive_ids[clip["id"]]
        lines.append(f'  <producer id="{clip_id}" in="0" out="{max(duration_frames - 1, 0)}">')
        lines.append(f'    <property name="resource">{source}</property>')
        lines.append(f'    <property name="kdenlive:clipname">{xml_escape(clip.get("name", ""))}</property>')
        lines.append(f'    <property name="kdenlive:clip_type">{_clip_type_num(clip.get("type", "video"))}</property>')
        lines.append(f'    <property name="length">{duration_frames}</property>')
        lines.append(f'    <property name="kdenlive:folderid">-1</property>')
        lines.append(f'    <property name="kdenlive:id">{kid}</property>')
        lines.append('  </producer>')

    # ── main_bin playlist (project bin) ──────────────────────────
    doc_uuid = str(uuid.uuid4())
    lines.append('  <playlist id="main_bin">')
    lines.append('    <property name="kdenlive:docproperties.version">1.04</property>')
    lines.append(f'    <property name="kdenlive:docproperties.profile">{xml_escape(profile.get("name", "custom"))}</property>')
    lines.append(f'    <property name="kdenlive:docproperties.uuid">{doc_uuid}</property>')
    lines.append('    <property name="kdenlive:docproperties.kdenliveversion">24.02</property>')
    lines.append('    <property name="xml_retain">1</property>')
    for clip in bin_clips:
        clip_id = xml_escape(clip["id"])
        duration_frames = seconds_to_frames(clip.get("duration", 0), fps_num, fps_den)
        lines.append(f'    <entry producer="{clip_id}" in="0" out="{max(duration_frames - 1, 0)}"/>')
    lines.append('  </playlist>')

    # ── Black track producer (no kdenlive:id — internal) ─────────
    lines.append(f'  <producer id="black_track" in="0" out="{timeline_duration_frames}">')
    lines.append('    <property name="length">2147483647</property>')
    lines.append('    <property name="eof">continue</property>')
    lines.append('    <property name="resource">black</property>')
    lines.append('    <property name="aspect_ratio">1</property>')
    lines.append('    <property name="mlt_service">color</property>')
    lines.append('    <property name="kdenlive:playlistid">black_track</property>')
    lines.append('    <property name="mlt_image_format">rgba</property>')
    lines.append('    <property name="set.test_audio">0</property>')
    lines.append('  </producer>')

    # ── Per-track: service producers, A/B playlists, tractor ─────
    svc_producer_counter = 0
    filter_counter = 0
    playlist_counter = 0
    tractor_counter = 0
    track_tractor_ids = []

    for track in tracks:
        is_audio = track.get("type") == "audio"
        hide_sub = "video" if is_audio else "audio"

        playlist_a_id = f"playlist{playlist_counter}"
        playlist_b_id = f"playlist{playlist_counter + 1}"
        tractor_id = f"tractor{tractor_counter}"

        # Create separate "service" producers for each clip on this track
        # and map them to playlist entries
        clip_entries_for_playlist = []
        for clip_entry in track.get("clips", []):
            src_clip_id = clip_entry.get("clip_id", "")
            src_clip = clip_sources.get(src_clip_id)
            if not src_clip:
                continue

            kid = clip_kdenlive_ids.get(src_clip_id, 0)
            source = xml_escape(src_clip.get("source", ""))
            duration_frames = seconds_to_frames(src_clip.get("duration", 0), fps_num, fps_den)
            svc_id = f"svc_producer{svc_producer_counter}"
            svc_producer_counter += 1

            # Service producer: a copy of the bin clip for timeline use
            lines.append(f'  <producer id="{svc_id}" in="0" out="{max(duration_frames - 1, 0)}">')
            lines.append(f'    <property name="resource">{source}</property>')
            lines.append(f'    <property name="kdenlive:clipname">{xml_escape(src_clip.get("name", ""))}</property>')
            lines.append(f'    <property name="kdenlive:clip_type">{_clip_type_num(src_clip.get("type", "video"))}</property>')
            lines.append(f'    <property name="length">{duration_frames}</property>')
            lines.append(f'    <property name="kdenlive:id">{kid}</property>')
            lines.append(f'    <property name="mlt_service">avformat-novalidate</property>')
            if is_audio:
                lines.append('    <property name="set.test_audio">0</property>')
                lines.append('    <property name="set.test_image">1</property>')
            else:
                lines.append('    <property name="set.test_audio">1</property>')
                lines.append('    <property name="set.test_image">0</property>')
            lines.append('  </producer>')

            clip_entries_for_playlist.append((svc_id, clip_entry, kid))

        # Playlist A (has clip entries)
        lines.append(f'  <playlist id="{playlist_a_id}">')
        if is_audio:
            lines.append('    <property name="kdenlive:audio_track">1</property>')

        prev_end = 0.0
        for svc_id, clip_entry, kid in clip_entries_for_playlist:
            pos = clip_entry.get("position", 0.0)
            gap = pos - prev_end
            if gap > 0.001:
                gap_frames = seconds_to_frames(gap, fps_num, fps_den)
                lines.append(f'    <blank length="{gap_frames}"/>')

            in_frames = seconds_to_frames(clip_entry.get("in", 0), fps_num, fps_den)
            out_frames = seconds_to_frames(clip_entry.get("out", 0), fps_num, fps_den)
            lines.append(f'    <entry producer="{svc_id}" in="{in_frames}" out="{max(out_frames - 1, 0)}">')
            lines.append(f'      <property name="kdenlive:id">{kid}</property>')

            for filt in clip_entry.get("filters", []):
                mlt_svc = xml_escape(filt.get("mlt_service", ""))
                lines.append(f'      <filter mlt_service="{mlt_svc}">')
                lines.append(f'        <property name="kdenlive:filter_name">{xml_escape(filt.get("name", ""))}</property>')
                for pk, pv in filt.get("params", {}).items():
                    lines.append(f'        <property name="{xml_escape(pk)}">{xml_escape(str(pv))}</property>')
                lines.append('      </filter>')

            lines.append('    </entry>')
            clip_dur = clip_entry.get("out", 0) - clip_entry.get("in", 0)
            prev_end = pos + clip_dur

        lines.append('  </playlist>')

        # Playlist B (always empty — used for transitions/split edits)
        lines.append(f'  <playlist id="{playlist_b_id}"/>')

        # Track tractor
        lines.append(f'  <tractor id="{tractor_id}" in="0">')
        if is_audio:
            lines.append('    <property name="kdenlive:audio_track">1</property>')
        lines.append('    <property name="kdenlive:trackheight">67</property>')
        lines.append('    <property name="kdenlive:timeline_active">1</property>')
        lines.append('    <property name="kdenlive:collapsed">0</property>')
        lines.append(f'    <track hide="{hide_sub}" producer="{playlist_a_id}"/>')
        lines.append(f'    <track hide="{hide_sub}" producer="{playlist_b_id}"/>')
        # Internal track filters (volume, panner, audiolevel)
        lines.append(f'    <filter id="filter{filter_counter}">')
        lines.append('      <property name="window">75</property>')
        lines.append('      <property name="max_gain">20dB</property>')
        lines.append('      <property name="mlt_service">volume</property>')
        lines.append('      <property name="internal_added">237</property>')
        lines.append('      <property name="disable">1</property>')
        lines.append('    </filter>')
        filter_counter += 1
        lines.append(f'    <filter id="filter{filter_counter}">')
        lines.append('      <property name="channel">-1</property>')
        lines.append('      <property name="mlt_service">panner</property>')
        lines.append('      <property name="internal_added">237</property>')
        lines.append('      <property name="start">0.5</property>')
        lines.append('      <property name="disable">1</property>')
        lines.append('    </filter>')
        filter_counter += 1
        lines.append(f'    <filter id="filter{filter_counter}">')
        lines.append('      <property name="iec_scale">0</property>')
        lines.append('      <property name="mlt_service">audiolevel</property>')
        lines.append('      <property name="peak">1</property>')
        lines.append('      <property name="disable">1</property>')
        lines.append('    </filter>')
        filter_counter += 1
        lines.append('  </tractor>')

        track_tractor_ids.append(tractor_id)
        playlist_counter += 2
        tractor_counter += 1

    # ── Main tractor (timeline) ──────────────────────────────────
    main_tractor_id = f"tractor{tractor_counter}"
    lines.append(f'  <tractor id="{main_tractor_id}" in="0" out="{timeline_duration_frames}">')

    # Black track first (direct reference, no wrapper playlist)
    lines.append('    <track producer="black_track"/>')
    for tid in track_tractor_ids:
        lines.append(f'    <track producer="{tid}"/>')

    # Internal Kdenlive transitions (mix for audio, composite for video)
    trans_counter = 0
    for tractor_idx, track in enumerate(tracks, start=1):
        is_audio = track.get("type") == "audio"
        if is_audio:
            lines.append(f'    <transition id="transition{trans_counter}">')
            lines.append('      <property name="a_track">0</property>')
            lines.append(f'      <property name="b_track">{tractor_idx}</property>')
            lines.append('      <property name="mlt_service">mix</property>')
            lines.append('      <property name="kdenlive_id">mix</property>')
            lines.append('      <property name="internal_added">237</property>')
            lines.append('      <property name="always_active">1</property>')
            lines.append('      <property name="accepts_blanks">1</property>')
            lines.append('      <property name="sum">1</property>')
            lines.append('    </transition>')
        else:
            lines.append(f'    <transition id="transition{trans_counter}">')
            lines.append('      <property name="a_track">0</property>')
            lines.append(f'      <property name="b_track">{tractor_idx}</property>')
            lines.append('      <property name="version">0.1</property>')
            lines.append('      <property name="mlt_service">frei0r.cairoblend</property>')
            lines.append('      <property name="kdenlive_id">frei0r.cairoblend</property>')
            lines.append('      <property name="internal_added">237</property>')
            lines.append('      <property name="always_active">1</property>')
            lines.append('    </transition>')
        trans_counter += 1

    # User-defined transitions (track indices shifted +1 for black track)
    for trans in project.get("transitions", []):
        mlt_svc = xml_escape(trans.get("mlt_service", ""))
        pos_frames = seconds_to_frames(trans.get("position", 0), fps_num, fps_den)
        dur_frames = seconds_to_frames(trans.get("duration", 1), fps_num, fps_den)
        a_idx = _track_index(tracks, trans["track_a"]) + 1
        b_idx = _track_index(tracks, trans["track_b"]) + 1
        lines.append(f'    <transition mlt_service="{mlt_svc}" '
                     f'in="{pos_frames}" out="{pos_frames + dur_frames}" '
                     f'a_track="{a_idx}" b_track="{b_idx}">')
        for pk, pv in trans.get("params", {}).items():
            if pk in ("duration",):
                continue
            lines.append(f'      <property name="{xml_escape(pk)}">{xml_escape(str(pv))}</property>')
        lines.append('    </transition>')

    # Master volume/panner/audiolevel filters on main tractor
    lines.append(f'    <filter id="filter{filter_counter}">')
    lines.append('      <property name="window">75</property>')
    lines.append('      <property name="max_gain">20dB</property>')
    lines.append('      <property name="mlt_service">volume</property>')
    lines.append('      <property name="internal_added">237</property>')
    lines.append('      <property name="disable">1</property>')
    lines.append('    </filter>')
    filter_counter += 1
    lines.append(f'    <filter id="filter{filter_counter}">')
    lines.append('      <property name="channel">-1</property>')
    lines.append('      <property name="mlt_service">panner</property>')
    lines.append('      <property name="internal_added">237</property>')
    lines.append('      <property name="start">0.5</property>')
    lines.append('      <property name="disable">1</property>')
    lines.append('    </filter>')
    filter_counter += 1
    lines.append(f'    <filter id="filter{filter_counter}">')
    lines.append('      <property name="iec_scale">0</property>')
    lines.append('      <property name="mlt_service">audiolevel</property>')
    lines.append('      <property name="peak">1</property>')
    lines.append('      <property name="disable">1</property>')
    lines.append('    </filter>')

    lines.append('  </tractor>')

    # ── Kdenlive document metadata (guides) ──────────────────────
    guides = project.get("guides", [])
    if guides:
        lines.append('  <kdenlivedoc>')
        for g in guides:
            pos_frames = seconds_to_frames(g["position"], fps_num, fps_den)
            lines.append(f'    <guide pos="{pos_frames}" '
                         f'comment="{xml_escape(g.get("label", ""))}" '
                         f'type="{xml_escape(g.get("type", "default"))}"/>')
        lines.append('  </kdenlivedoc>')

    lines.append('</mlt>')
    return '\n'.join(lines)


def _clip_type_num(clip_type: str) -> int:
    """Convert clip type string to Kdenlive type number."""
    mapping = {
        "video": 0,
        "audio": 1,
        "image": 2,
        "color": 3,
        "title": 4,
    }
    return mapping.get(clip_type, 0)


def _track_index(tracks: list, track_id: int) -> int:
    """Find 0-based index of track by ID."""
    for i, t in enumerate(tracks):
        if t["id"] == track_id:
            return i
    return 0
