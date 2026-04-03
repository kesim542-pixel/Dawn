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
        "-q:v", "1",
        "-vf", "scale=320:-1",
        thumb_path
    ], capture_output=True)

    return thumb_path if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0 else None


def get_video_duration(input_file: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_file],
        capture_output=True, text=True
    )
    try:
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def add_watermark(input_file: str, progress_cb=None) -> tuple:
    """
    Add watermark with:
    - SLOW motion scroll (30px/sec)
    - Auto repeats every scroll completion
    - High quality CRF 18 + copy audio
    """
    output = "output.mp4"
    thumb  = "thumb.jpg"

    # Text with extra spaces so repeat is not visible
    text = "Join channel for more  @Squad_4xx          Join channel for more  @Squad_4xx"

    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\\'")
        .replace(":",  "\\:")
    )

    duration   = get_video_duration(input_file)
    thumb_path = extract_thumbnail(input_file, thumb)

    # Slow scroll: 30px/sec — completes one scroll then restarts
    # mod(t*speed, W+TW) = repeat scroll automatically
    scroll_speed = 30

    vf_filter = (
        "drawtext="
        "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{safe_text}':"
        "fontcolor=white:"
        "fontsize=30:"
        "shadowcolor=black@0.9:"
        "shadowx=2:shadowy=2:"
        "box=1:"
        "boxcolor=black@0.5:"
        "boxborderw=10:"
        f"x=w-mod(t*{scroll_speed}\\,w+tw):"
        "y=h-th-30"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",          # zero audio quality loss
        "-movflags", "+faststart",
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

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

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
    t.join(timeout=3)

    if proc.returncode != 0:
        err = "".join(stderr_lines[-20:])
        raise RuntimeError(f"ffmpeg failed:\n{err[-600:]}")

    return output, thumb_path


def get_thumbnail_only(input_file: str) -> str:
    return extract_thumbnail(input_file, "thumb.jpg")
