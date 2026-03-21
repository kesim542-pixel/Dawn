import subprocess
import time


def add_watermark(input_file: str, progress_cb=None) -> str:
    """
    Add scrolling watermark. progress_cb(percent) is called periodically.
    """
    output = "output.mp4"
    text   = "Join channel for more @Squad_4xx   Join channel for more @Squad_4xx"

    # Get duration first so we can calculate %
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_file],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
    except Exception:
        duration = 0

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf",
        (
            f"drawtext=text='{text}':"
            "fontcolor=white@0.4:fontsize=26:"
            "x=w-mod(max(t*18\\,w+tw),w):y=h-50"
        ),
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        output
    ]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    # Parse ffmpeg progress output
    out_time = 0
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=")[1])
                out_time = ms / 1_000_000
                if duration > 0 and progress_cb:
                    pct = min((out_time / duration) * 100, 99)
                    progress_cb(pct)
            except Exception:
                pass

    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg error: {err[-300:]}")

    return output
