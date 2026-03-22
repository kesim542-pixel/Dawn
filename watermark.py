import subprocess
import threading
import os


def extract_thumbnail(input_file: str, thumb_path: str = "thumb.jpg") -> str:
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_file],
        capture_output=True, text=True
    )
    try:
        duration  = float(probe.stdout.strip())
        seek_time = duration / 2
    except Exception:
        seek_time = 1.0

    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", input_file,
        "-vframes", "1",
        "-q:v", "1",           # highest quality JPEG
        "-vf", "scale=320:-1",
        thumb_path
    ], capture_output=True)

    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path
    return None


def get_source_info(input_file: str) -> dict:
    """Get video resolution, bitrate, fps from source."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,bit_rate",
         "-show_entries", "format=duration,bit_rate",
         "-of", "default=noprint_wrappers=1",
         input_file],
        capture_output=True, text=True
    )
    info = {}
    for line in probe.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def add_watermark(input_file: str, progress_cb=None) -> tuple:
    output = "output.mp4"
    thumb  = "thumb.jpg"
    text   = "Join channel for more @Squad_4xx   Join channel for more @Squad_4xx"

    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\\'")
        .replace(":",  "\\:")
    )

    # Get source info for matching quality
    info     = get_source_info(input_file)
    src_br   = info.get("bit_rate", "0")
    try:
        # Use source bitrate or minimum 4Mbps for high quality
        bitrate = max(int(src_br), 4_000_000)
    except Exception:
        bitrate = 4_000_000

    # Get duration for progress
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_file],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
    except Exception:
        duration = 0

    # Extract thumbnail from original (best quality frame)
    thumb_path = extract_thumbnail(input_file, thumb)

    vf_filter = (
        "drawtext="
        "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{safe_text}':"
        "fontcolor=white:"
        "fontsize=28:"
        "shadowcolor=black:"
        "shadowx=2:shadowy=2:"
        "box=1:"
        "boxcolor=black@0.45:"
        "boxborderw=8:"
        "x=w-mod(max(t*130\\,w+tw)\\,w+tw):"
        "y=h-th-25"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", vf_filter,

        # ── HIGH QUALITY settings ─────────────────────────────────────
        "-c:v", "libx264",
        "-preset", "slow",       # slow = better compression at same quality
        "-crf", "18",            # 18 = visually lossless (was 23 before)
        "-b:v", str(bitrate),    # match source bitrate
        "-maxrate", str(bitrate * 2),
        "-bufsize", str(bitrate * 2),
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",

        # ── HIGH QUALITY audio ────────────────────────────────────────
        "-c:a", "aac",
        "-b:a", "192k",          # high quality audio (was copy before)
        "-ar", "44100",

        # ── No quality reduction flags ────────────────────────────────
        "-movflags", "+faststart", # web optimized

        "-progress", "pipe:1",
        "-nostats",
        output
    ]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    stderr_lines = []

    def drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                ms      = int(line.split("=")[1])
                out_sec = ms / 1_000_000
                if duration > 0 and progress_cb:
                    pct = min((out_sec / duration) * 100, 99.0)
                    progress_cb(pct)
            except Exception:
                pass

    proc.wait()
    stderr_thread.join(timeout=3)

    if proc.returncode != 0:
        err = "".join(stderr_lines[-20:])
        raise RuntimeError(f"ffmpeg failed:\n{err[-600:]}")

    return output, thumb_path


def get_thumbnail_only(input_file: str) -> str:
    return extract_thumbnail(input_file, "thumb.jpg")
