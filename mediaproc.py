"""Подготовка медиа для OBS и окна программы: любое видео → гарантированно играющее.

ffmpeg берём из пакета imageio-ffmpeg (ставится вместе с программой).
Что делаем с видео:
  ok        — уже H.264 + обычный AAC + оглавление в начале: не трогаем
  remux     — кодеки хорошие, но оглавление (moov) в конце: переупаковка без потери качества
  audio     — видео хорошее, звук «странный» (HE-AAC, Opus…): перекодируем только звук
  transcode — HEVC, VP9, AV1, нечётный размер…: полностью в H.264 + AAC
"""
import asyncio
import os
import re
import shutil
import struct
import sys

WIN = sys.platform == "win32"


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _flags():
    return {"creationflags": 0x08000000} if WIN else {}      # без чёрного окна на Windows


def moov_first(path):
    """True, если оглавление MP4 стоит до данных — браузер начнёт играть сразу."""
    try:
        with open(path, "rb") as f:
            pos, size_total = 0, os.path.getsize(path)
            while pos + 8 <= size_total:
                f.seek(pos)
                size, typ = struct.unpack(">I4s", f.read(8))
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                if typ == b"moov":
                    return True
                if typ == b"mdat":
                    return False
                if size < 8:
                    return False
                pos += size
    except Exception:
        pass
    return False


async def probe(path):
    """Длительность, кодеки, размер — из вывода ffmpeg -i."""
    ff = ffmpeg_exe()
    if not ff:
        raise RuntimeError("нет ffmpeg")
    p = await asyncio.create_subprocess_exec(ff, "-hide_banner", "-i", path, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.PIPE, **_flags())
    _, err = await p.communicate()
    t = err.decode("utf-8", "replace")
    info = {"duration": 0.0, "vcodec": None, "vprofile": None, "pix": None, "w": 0, "h": 0, "acodec": None, "aprofile": None}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", t)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Stream #\S+.*?: Video: (\w+)(?: \(([^)]+)\))?[^\n]*?, (\w+)(?:\([^)]*\))?, (\d+)x(\d+)", t)
    if m:
        info.update(vcodec=m.group(1), vprofile=m.group(2), pix=m.group(3), w=int(m.group(4)), h=int(m.group(5)))
    m = re.search(r"Stream #\S+.*?: Audio: (\w+)(?: \(([^)]+)\))?", t)
    if m:
        info.update(acodec=m.group(1), aprofile=m.group(2))
    return info


def plan(info, path):
    ext = path.lower().rsplit(".", 1)[-1]
    ok_v = (info["vcodec"] == "h264" and str(info["pix"] or "").startswith("yuv420p")
            and info["w"] % 2 == 0 and info["h"] % 2 == 0)
    ok_a = info["acodec"] is None or (info["acodec"] == "aac" and (info["aprofile"] in (None, "LC")))
    if not info["vcodec"]:
        return "transcode"
    if ok_v and ok_a:
        return "ok" if ext == "mp4" and moov_first(path) else "remux"
    if ok_v:
        return "audio"
    return "transcode"


async def convert(src, dst, mode, duration, progress=None):
    ff = ffmpeg_exe()
    base = [ff, "-hide_banner", "-nostats", "-y", "-i", src]
    tail = ["-movflags", "+faststart", "-progress", "pipe:1", dst]
    if mode == "remux":
        args = base + ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy"] + tail
    elif mode == "audio":
        args = base + ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ac", "2"] + tail
    else:
        args = base + ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                       "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                       "-c:a", "aac", "-b:a", "160k", "-ac", "2"] + tail
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **_flags())
    err_task = asyncio.ensure_future(p.stderr.read())
    while True:
        line = await p.stdout.readline()
        if not line:
            break
        m = re.match(rb"out_time_(?:us|ms)=(\d+)", line)
        if m and duration and progress:
            progress(min(0.99, int(m.group(1)) / 1e6 / duration))
    code = await p.wait()
    err = (await err_task).decode("utf-8", "replace")
    if code != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 100:
        raise RuntimeError((err.strip().splitlines() or ["ffmpeg не смог обработать файл"])[-1][:200])


async def thumbnail(src, dst, duration):
    ff = ffmpeg_exe()
    at = f"{min(1.0, max(0.0, duration / 3)):.2f}"
    p = await asyncio.create_subprocess_exec(ff, "-hide_banner", "-y", "-ss", at, "-i", src, "-frames:v", "1",
                                             "-vf", "scale=360:-2", "-q:v", "5", dst,
                                             stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **_flags())
    await p.wait()
    return os.path.exists(dst)
