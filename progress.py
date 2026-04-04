"""
Professional Progress Bar
- Real-time speed (KB/s / MB/s)
- Accurate ETA
- Smooth updates (respects Telegram flood limits)
- Visual bar with blocks
"""
import asyncio
import time


class ProgressMessage:
    def __init__(self, message, title: str = "Processing"):
        self.message    = message
        self.title      = title
        self.msg        = None
        self._start     = None
        self._last_edit = 0
        self._last_pct  = -1
        self._done      = False
        self._bytes_log = []   # list of (timestamp, bytes) for accurate speed

    async def start(self):
        self._start = time.time()
        self.msg = await self.message.reply_text(
            f"⏳ *{self.title}*\n\n"
            "░░░░░░░░░░ 0%\n"
            "⚡ Speed  : --\n"
            "🕐 ETA    : --\n"
            "⏱ Elapsed : 00:00",
            parse_mode="Markdown"
        )

    def _format_speed(self, bps: float) -> str:
        """Format bytes/sec into human readable string."""
        if bps <= 0:
            return "--"
        if bps >= 1024 * 1024:
            return f"{bps / 1024 / 1024:.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps:.0f} B/s"

    def _format_eta(self, seconds: float) -> str:
        """Format seconds into MM:SS string."""
        if seconds <= 0 or seconds > 86400:
            return "--"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def _format_size(self, downloaded: float, total: float) -> str:
        """Format downloaded/total size."""
        if total <= 0:
            return ""
        def fmt(b):
            if b >= 1024 * 1024 * 1024:
                return f"{b/1024/1024/1024:.1f} GB"
            if b >= 1024 * 1024:
                return f"{b/1024/1024:.1f} MB"
            return f"{b/1024:.0f} KB"
        return f"{fmt(downloaded)} / {fmt(total)}"

    def _build_bar(self, pct: float) -> str:
        """Build visual progress bar."""
        filled = int(pct / 10)
        empty  = 10 - filled
        return "█" * filled + "░" * empty

    def _calc_speed(self, downloaded: float) -> float:
        """
        Calculate speed using rolling 3-second window
        for accurate real-time speed (not average since start).
        """
        now = time.time()
        self._bytes_log.append((now, downloaded))

        # Keep only last 3 seconds of data
        cutoff = now - 3.0
        self._bytes_log = [(t, b) for t, b in self._bytes_log if t >= cutoff]

        if len(self._bytes_log) < 2:
            # Fallback: use total elapsed
            elapsed = max(now - self._start, 0.001)
            return downloaded / elapsed

        # Speed = bytes difference / time difference (rolling window)
        oldest_t, oldest_b = self._bytes_log[0]
        newest_t, newest_b = self._bytes_log[-1]
        dt = max(newest_t - oldest_t, 0.001)
        db = newest_b - oldest_b
        return max(db / dt, 0)

    async def update(self, pct: float, speed: float = 0,
                     downloaded: float = 0, total: float = 0):
        if self._done:
            return

        now = time.time()

        # Respect Telegram flood limit: max 1 edit per 2 seconds
        if now - self._last_edit < 2.0:
            return
        # Skip tiny changes unless near end
        if abs(pct - self._last_pct) < 1.0 and pct < 98:
            return

        self._last_edit = now
        self._last_pct  = pct

        # Calculate accurate speed using rolling window
        if downloaded > 0:
            real_speed = self._calc_speed(downloaded)
        else:
            real_speed = speed  # use provided speed if no byte tracking

        # Calculate ETA
        if real_speed > 0 and total > downloaded > 0:
            eta_sec = (total - downloaded) / real_speed
            eta_str = self._format_eta(eta_sec)
        else:
            eta_str = "--"

        elapsed = int(now - self._start)
        e_str   = f"{elapsed//60:02d}:{elapsed%60:02d}"
        bar     = self._build_bar(pct)
        spd_str = self._format_speed(real_speed)
        siz_str = self._format_size(downloaded, total)

        text = (
            f"⏳ *{self.title}*\n\n"
            f"{bar} {pct:.0f}%\n"
            f"⚡ Speed  : {spd_str}\n"
            f"🕐 ETA    : {eta_str}\n"
            f"⏱ Elapsed : {e_str}"
        )
        if siz_str:
            text += f"\n💾 Size   : {siz_str}"

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
        text    = (
            f"✅ *{self.title} — Done!*\n\n"
            f"██████████ 100%\n"
            f"⏱ Total time : {e_str}"
        )
        if extra:
            text += f"\n\n{extra}"
        try:
            await self.msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    async def error(self, err: str = ""):
        if self._done:
            return
        self._done = True
        try:
            await self.msg.edit_text(
                f"❌ *{self.title} — Failed*\n\n{err}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
