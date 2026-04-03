"""
Progress bar with download/upload speed display.
Shows: bar + % + speed (KB/s or MB/s) + ETA + elapsed + size
"""
import asyncio
import time


class ProgressMessage:
    def __init__(self, message, title: str = "Processing"):
        self.message   = message
        self.title     = title
        self.msg       = None
        self._start    = None
        self._last_edit= 0
        self._last_pct = -1
        self._done     = False

    async def start(self):
        self._start = time.time()
        self.msg = await self.message.reply_text(
            f"⏳ *{self.title}*\n\n"
            "▱▱▱▱▱▱▱▱▱▱ 0%\n"
            "⚡ Speed : -- KB/s\n"
            "🕐 ETA   : --\n"
            "⏱ Elapsed: 00:00",
            parse_mode="Markdown"
        )

    async def update(self, pct: float, speed: float = 0,
                     downloaded: float = 0, total: float = 0):
        if self._done:
            return

        now = time.time()
        # Edit max every 2 seconds to avoid Telegram flood
        if now - self._last_edit < 2.0:
            return
        if abs(pct - self._last_pct) < 1.0 and pct < 99:
            return

        self._last_edit = now
        self._last_pct  = pct

        elapsed = int(now - self._start)
        e_str   = f"{elapsed//60:02d}:{elapsed%60:02d}"

        # Build bar
        filled = int(pct / 10)
        bar    = "▰" * filled + "▱" * (10 - filled)

        # Speed display
        if speed > 0:
            if speed >= 1024 * 1024:
                spd_str = f"{speed/1024/1024:.1f} MB/s"
            elif speed >= 1024:
                spd_str = f"{speed/1024:.0f} KB/s"
            else:
                spd_str = f"{speed:.0f} B/s"
        else:
            spd_str = "-- KB/s"

        # ETA
        if speed > 0 and total > downloaded > 0:
            remaining = (total - downloaded) / speed
            eta_str   = f"{int(remaining//60):02d}:{int(remaining%60):02d}"
        else:
            eta_str = "--"

        # Size display
        if total > 0:
            dl_mb    = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            size_str = f"{dl_mb:.1f}/{total_mb:.1f} MB"
        else:
            size_str = ""

        size_line = f"💾 Size  : {size_str}\n" if size_str else ""

        text = (
            f"⏳ *{self.title}*\n\n"
            f"{bar} {pct:.0f}%\n"
            f"⚡ Speed : {spd_str}\n"
            f"🕐 ETA   : {eta_str}\n"
            f"⏱ Elapsed: {e_str}\n"
            f"{size_line}"
        )

        try:
            await self.msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    async def done(self, extra: str = ""):
        if self._done:
            return
        self._done = True
        elapsed = int(time.time() - self._start)
        e_str   = f"{elapsed//60:02d}:{elapsed%60:02d}"
        text = (
            f"✅ *{self.title} — Done!*\n\n"
            f"▰▰▰▰▰▰▰▰▰▰ 100%\n"
            f"⏱ Total time: {e_str}\n"
        )
        if extra:
            text += f"\n{extra}"
        try:
            await self.msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    async def error(self, err: str = ""):
        if self._done:
            return
        self._done = True
        text = (
            f"❌ *{self.title} — Failed*\n\n"
            f"{err}"
        )
        try:
            await self.msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass
