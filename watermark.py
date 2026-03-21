import subprocess
import threading
import os


def extract_thumbnail(input_file: str, thumb_path: str = "thumb.jpg") -> str:
    """
    Extract the best thumbnail from the video:
    - Tries middle frame first (most representative)
    - Falls back to first frame if video is very short
    """
    # Get duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         input_file],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
        seek_time = duration / 2  # middle of video = best thumbnail
    except Exception:
        seek_time = 1.0  # fallback: 1 second in

    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", input_file,
        "-vframes", "1",          # extract exactly 1 frame
        "-q:v", "2",              # high quality JPEG
        "-vf", "scale=320:-1",    # resize to 320px wide (Telegram standard)
        thumb_path
    ], capture_output=True)

    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path
    return None


def add_watermark(input_file: str, progress_cb=None) -> tuple:
    """
    Add scrolling watermark to video AND extract thumbnail.
    Returns (output_video_path, thumbnail_path)
    """
    output    = "output.mp4"
    thumb     = "thumb.jpg"
    text      = "Join channel for more @Squad_4xx   Join channel for more @Squad_4xx"

    # ── Escape text for ffmpeg drawtext ──────────────────────────────────
    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\\'")
        .replace(":",  "\\:")
    )

    # ── Get video duration for progress % ────────────────────────────────
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         input_file],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
    except Exception:
        duration = 0

    # ── Extract thumbnail BEFORE watermarking (cleaner frame) ────────────
    thumb_path = extract_thumbnail(input_file, thumb)

    # ── ffmpeg watermark filter ───────────────────────────────────────────
    # FIX 1: white text + BLACK SHADOW = always visible on any background
    # FIX 2: box background behind text for extra contrast
    # FIX 3: larger font size (30 instead of 24)
    # FIX 4: full opacity (1.0 instead of 0.6)
    vf_filter = (
        "drawtext="
        "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{safe_text}':"

        # ── Visibility fixes ──────────────────────────────────────────
        "fontcolor=white:"               # full white — no transparency
        "fontsize=28:"                   # bigger font
        "shadowcolor=black:"             # black drop shadow
        "shadowx=2:shadowy=2:"           # shadow offset 2px

        # ── Semi-transparent dark box behind text ─────────────────────
        "box=1:"                         # enable background box
        "boxcolor=black@0.45:"           # 45% black box
        "boxborderw=8:"                  # padding inside box

        # ── Scrolling position ────────────────────────────────────────
        "x=w-mod(max(t*130\\,w+tw)\\,w+tw):"   # smooth left scroll
        "y=h-th-25"                             # 25px from bottom
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        output
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # ── Drain stderr in background to prevent deadlock ───────────────────
    stderr_lines = []

    def drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    # ── Read progress ─────────────────────────────────────────────────────
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
    """Extract thumbnail without watermark (for no-watermark uploads)."""
    return extract_thumbnail(input_file, "thumb.jpg")
