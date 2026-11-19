"""Morning briefing: greeting and date, today's weather, today's reminders, and a few headlines."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .hub import SkillHub, SkillReply, join_words
from .news import Headline, NewsFeed, short_title
from .timeparse import part_of_day, speak_clock, speak_date

_GREETINGS = {"pagi": "Selamat pagi!", "siang": "Selamat siang!", "sore": "Selamat sore!", "malam": "Selamat malam!", "dini hari": "Halo!"}


class Briefing:
    """Composes the briefing from existing skills; every part degrades gracefully when offline."""

    def __init__(self, hub: SkillHub, news: NewsFeed | None, config: dict[str, Any]):
        self.hub = hub
        self.news = news
        self.headline_count = int(config.get("briefing", {}).get("spoken_headlines", 2))

    def compose(self) -> SkillReply:
        """About 4-6 spoken sentences; the full version (5 headlines with links) goes to the screen."""
        now: datetime = self.hub.now()
        spoken = [f"{_GREETINGS[part_of_day(now.hour)]} Hari ini {speak_date(now)}."]
        detail = [f"Briefing {speak_date(now)}, {now:%H.%M}"]

        weather = self.hub.weather_for(None, 0)
        if weather.ok:
            spoken.append(weather.text)
            detail.append(weather.detail)
        else:
            detail.append("Cuaca: tidak tersedia")

        today = [item for item in self.hub.reminders.upcoming(("reminder", "alarm")) if item.due.date() == now.date()]
        if today:
            phrases = [f"{item.message or 'pengingat'} {speak_clock(item.due)}" for item in today[:3]]
            spoken.append(f"Hari ini ada {len(today)} pengingat: {join_words(phrases)}.")
            detail.extend(f"Pengingat {item.due:%H.%M}: {item.message}" for item in today)
        else:
            spoken.append("Belum ada pengingat untuk hari ini.")

        headlines: list[Headline] = self.news.headlines(5) if self.news is not None else []
        if headlines:
            top = [f"{h.source} melaporkan, {short_title(h.title)}" for h in headlines[: self.headline_count]]
            spoken.append("Berita utama: " + "; lalu ".join(top) + ".")
            detail.append("Berita:")
            detail.extend(f"- {h.title} ({h.source})\n  {h.link}" for h in headlines)
        return SkillReply(" ".join(spoken), detail="\n".join(detail), data={"berita": [h.title for h in headlines]})
