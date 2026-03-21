import subprocess


def add_watermark(input_file):
    output = "output.mp4"
    text   = "Join channel for more @Squad_4xx   Join channel for more @Squad_4xx"

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf",
        (
            f"drawtext=text='{text}':"
            "fontcolor=white@0.4:fontsize=26:"
            "x=w-mod(max(t*18\\,w+tw),w):y=h-50"
        ),
        "-c:a", "copy",
        output
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")

    return output
