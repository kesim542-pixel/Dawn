import asyncio
import time
import math


# ── Unicode block bar builder ─────────────────────────────────────────────
BLOCKS = ["░", "▒", "▓", "█"]

def make_bar(percent: float, width: int = 16) -> str:
    filled     = int(percent / 100 * width)
    remainder  = percent / 100 * width - filled
    bar        = "█" * filled
    if filled < width:
        quarter = int(remainder * 4)
        bar    += BLOCKS[quarter]
        bar    += "░" * (width - filled - 1)
    return bar


def fmt_speed(bps: float) -> str:
    if bps <= 0:
        return "-- KB/s"
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} MB/s"
    return f"{bps/1_000:.0f} KB/s"


def fmt_eta(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds):
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def fmt_size(b: float) -> str:
    if b >= 1_000_000_000:
        return f"{b/1_000_000_000:.2f} GB"
    if b >= 1_000_000:
        return f"{b/1_000_000:.1f} MB"
    return f"{b/1_000:.0f} KB"


# ── Animated progress message ─────────────────────────────────────────────

class ProgressMessage:
    """
    Sends ONE message and edits it in-place with live progress.
    Usage:
        pm = ProgressMessage(message, "⬇️ Downloading")
        await pm.start()
        ... update pm.percent / pm.speed_bps / pm.downloaded / pm.total ...
        await pm.done("✅ Download complete!")
    """

    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message, title: str = "Processing"):
        self.message    = message       # telegram Message object to reply to
        self.title      = title
        self.percent    = 0.0
        self.speed_bps  = 0.0
        self.downloaded = 0
        self.total      = 0
        self._msg       = None          # the sent Telegram message
        self._task      = None
        self._stopped   = False
        self._spin_idx  = 0
        self._start_ts  = time.time()

    def _render(self) -> str:
        bar     = make_bar(self.percent)
        elapsed = time.time() - self._start_ts
        eta     = ((100 - self.percent) / self.percent * elapsed) if self.percent > 0.5 else 0
        spin    = self.SPINNER[self._spin_idx % len(self.SPINNER)]
        self._spin_idx += 1

        size_info = ""
        if self.total > 0:
            size_info = f"\n📦 `{fmt_size(self.downloaded)}` / `{fmt_size(self.total)}`"

        return (
            f"{spin} *{self.title}*\n\n"
            f"`[{bar}]` {self.percent:.1f}%\n"
            f"⚡ Speed : `{fmt_speed(self.speed_bps)}`\n"
            f"⏱ ETA   : `{fmt_eta(eta)}`\n"
            f"⏳ Elapsed: `{fmt_eta(elapsed)}`"
            f"{size_info}"
        )

    async def start(self):
        self._msg = await self.message.reply_text(
            self._render(), parse_mode="Markdown"
        )
        self._start_ts = time.time()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self):
        while not self._stopped:
            try:
                await self._msg.edit_text(self._render(), parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(1.5)

    async def update(self, percent: float, speed_bps: float = 0,
                     downloaded: int = 0, total: int = 0):
        self.percent    = min(percent, 99.9)
        self.speed_bps  = speed_bps
        self.downloaded = downloaded
        self.total      = total

    async def done(self, final_text: str):
        self._stopped = True
        if self._task:
            self._task.cancel()
        elapsed = time.time() - self._start_ts
        try:
            await self._msg.edit_text(
                f"✅ *{self.title} — Done!*\n\n"
                f"`[{'█' * 16}]` 100%\n"
                f"⏱ Total time: `{fmt_eta(elapsed)}`\n\n"
                f"{final_text}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    async def error(self, error_text: str):
        self._stopped = True
        if self._task:
            self._task.cancel()
        try:
            await self._msg.edit_text(
                f"❌ *{self.title} — Failed*\n\n{error_text}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
