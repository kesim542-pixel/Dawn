import subprocess
import threading


def add_watermark(input_file: str, progress_cb=None) -> str:
    output = "output.mp4"
    text   = "Join channel for more @Squad_4xx   Join channel for more @Squad_4xx"

    # ── FIX 1: Safe text escaping for drawtext ────────────────────────────
    # Do NOT use single-quote wrapping with special chars.
    # Instead escape only what ffmpeg drawtext requires:
    #   backslash → \\,  colon → \:,  single quote → \'
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

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf",
        (
            "drawtext="
            "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"text='{safe_text}':"
            "fontcolor=white@0.6:"
            "fontsize=24:"
            "x=w-mod(max(t*120\\,w+tw)\\,w+tw):"
            "y=h-th-20"
        ),
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
        stderr=subprocess.PIPE,  # captured but drained in background thread
        text=True
    )

    # ── FIX 2: Drain stderr in background thread to prevent DEADLOCK ─────
    # ffmpeg writes heavy logs to stderr. If we don't drain it, the pipe
    # buffer fills up, ffmpeg BLOCKS, and our stdout loop waits forever
    # → silent hang. Solution: drain stderr in a separate thread.
    stderr_lines = []

    def drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    # ── Read progress from stdout ─────────────────────────────────────────
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

    return output
