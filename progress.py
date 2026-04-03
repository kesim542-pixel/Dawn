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
        return "0 KB/s"
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} MB/s"
    return f"{bps/1_000:.0f} KB/s"

def fmt_eta(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds) or seconds > 36000:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

def fmt_size(b: float) -> str:
    if b >= 1_000_000_000:
        return f"{b/1_000_000_000:.2f} GB"
    if b >= 1_000_000:
        return f"{b/1_000:.1f} MB"
    return f"{b/1_000:.0f} KB"

# ── Animated progress message ─────────────────────────────────────────────

class ProgressMessage:
    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message, title: str = "Processing"):
        self.message    = message
        self.title      = title
        self.percent    = 0.0
        self.speed_bps  = 0.0
        self.downloaded = 0
        self.total      = 0
        self._msg       = None
        self._task      = None
        self._stopped   = False
        self._spin_idx  = 0
        self._start_ts  = time.time()

    def _render(self) -> str:
        bar     = make_bar(self.percent)
        elapsed = time.time() - self._start_ts
        
        # ETA calculation based on real-time speed
        if self.speed_bps > 0 and self.total > 0:
            remaining = max(0, self.total - self.downloaded)
            eta_val = remaining / self.speed_bps
        else:
            eta_val = 0

        spin = self.SPINNER[self._spin_idx % len(self.SPINNER)]
        self._spin_idx += 1

        size_info = ""
        if self.total > 0:
            size_info = f"\n📦 `{fmt_size(self.downloaded)}` / `{fmt_size(self.total)}`"

        return (
            f"{spin} *{self.title}*\n\n"
            f"`[{bar}]` {self.percent:.1f}%\n"
            f"⚡ Speed : `{fmt_speed(self.speed_bps)}`\n"
            f"⏱ ETA   : `{fmt_eta(eta_val)}`\n"
            f"⏳ Elapsed: `{fmt_eta(elapsed)}`"
            f"{size_info}"
        )

    async def start(self):
        self._msg = await self.message.reply_text(self._render(), parse_mode="Markdown")
        self._task = asyncio.create_task(self._loop())

    async def _loop(self):
        while not self._stopped:
            try:
                await self._msg.edit_text(self._render(), parse_mode="Markdown")
            except Exception: pass
            await asyncio.sleep(2)

    async def update(self, percent: float, speed_bps: float = 0, downloaded: int = 0, total: int = 0):
        self.percent    = min(percent, 99.9)
        self.speed_bps  = speed_bps
        self.downloaded = downloaded
        self.total      = total

    async def done(self, final_text: str):
        self._stopped = True
        if self._task: self._task.cancel()
        elapsed = time.time() - self._start_ts
        try:
            await self._msg.edit_text(
                f"✅ *{self.title} — Done!*\n\n`[{'█' * 16}]` 100%\n⏱ Total: `{fmt_eta(elapsed)}`\n\n{final_text}",
                parse_mode="Markdown"
            )
        except Exception: pass

    async def error(self, error_text: str):
        self._stopped = True
        if self._task: self._task.cancel()
        try:
            await self._msg.edit_text(f"❌ *{self.title} — Failed*\n\n{error_text}", parse_mode="Markdown")
        except Exception: pass
