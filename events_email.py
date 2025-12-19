#!/usr/bin/env python3
"""Scrape DO214 events and build a formatted email list."""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
from datetime import datetime, timezone
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

URL = "https://do214.com/events/"


@dataclasses.dataclass
class Event:
    title: str
    start_date: datetime
    url: str
    description: str | None = None
    fun_score: int = 0
    categories: list[str] = dataclasses.field(default_factory=list)


def fetch_page_html(url: str) -> str:
    """Fetch rendered HTML, preferring Playwright when available."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            html = page.content()
            browser.close()
            return html
    except Exception:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            },
            timeout=30,
        )
        if response.status_code == 403:
            raise RuntimeError(
                "Received 403 from DO214. Install Playwright and run with a "
                "headless browser session to fetch the page."
            )
        response.raise_for_status()
        return response.text


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.isoparse(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_json_ld_events(soup: BeautifulSoup) -> list[Event]:
    events: list[Event] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})

    def handle_item(item: dict):
        if item.get("@type") == "Event":
            start_date = parse_datetime(item.get("startDate"))
            if not start_date:
                return
            title = normalize_text(item.get("name"))
            url = item.get("url") or URL
            description = normalize_text(item.get("description"))
            if title:
                events.append(
                    Event(
                        title=title,
                        start_date=start_date,
                        url=url,
                        description=description or None,
                    )
                )

    for script in scripts:
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            payload = [payload]

        for item in payload:
            if isinstance(item, dict):
                if item.get("@type") == "ItemList":
                    for entry in item.get("itemListElement", []) or []:
                        if isinstance(entry, dict) and "item" in entry:
                            entry = entry["item"]
                        if isinstance(entry, dict):
                            handle_item(entry)
                else:
                    handle_item(item)

    return events


def parse_fallback_events(soup: BeautifulSoup) -> list[Event]:
    events: list[Event] = []
    for link in soup.select("a[href*='/events/']"):
        href = link.get("href")
        title = normalize_text(link.get_text())
        if not href or not title:
            continue
        parent = link.find_parent(["article", "div", "li"])
        time_tag = parent.find("time") if parent else None
        start_date = parse_datetime(time_tag.get("datetime") if time_tag else None)
        if not start_date:
            continue
        events.append(
            Event(
                title=title,
                start_date=start_date,
                url=href,
            )
        )
    return events


def fun_score(event: Event) -> int:
    title = event.title.lower()
    description = (event.description or "").lower()
    text = f"{title} {description}"
    keywords = {
        "festival": 5,
        "party": 4,
        "live": 3,
        "music": 3,
        "concert": 4,
        "comedy": 3,
        "happy hour": 2,
        "free": 2,
        "outdoor": 2,
        "food": 2,
        "beer": 2,
        "wine": 2,
        "dance": 3,
        "karaoke": 3,
        "trivia": 2,
        "market": 2,
        "brunch": 2,
        "workshop": 1,
    }
    score = 0
    for keyword, weight in keywords.items():
        if keyword in text:
            score += weight
    return score


def categorize_event(event: Event) -> list[str]:
    text = f"{event.title} {event.description or ''}".lower()
    category_rules = {
        "Kids events": ["kids", "family", "children", "storybook", "playdate"],
        "Music events": ["music", "concert", "live", "dj", "band", "festival"],
        "Adult outings": [
            "happy hour",
            "cocktail",
            "wine",
            "beer",
            "brewery",
            "nightlife",
            "21+",
        ],
        "Comedy": ["comedy", "stand-up", "improv"],
        "Food & Drink": ["food", "tasting", "brunch", "dinner"],
        "Markets & Shopping": ["market", "bazaar", "shopping", "pop-up"],
        "Outdoor & Fitness": ["outdoor", "hike", "yoga", "fitness", "run"],
        "Workshops": ["workshop", "class", "learn", "lesson"],
    }
    categories = [
        category
        for category, keywords in category_rules.items()
        if any(keyword in text for keyword in keywords)
    ]
    return categories or ["General"]


def within_next_two_months(event: Event, reference: datetime) -> bool:
    window_end = reference + relativedelta(months=2)
    return reference <= event.start_date <= window_end


def build_email_body(events: Iterable[Event]) -> str:
    events_by_date: dict[str, list[Event]] = {}
    for event in events:
        date_key = event.start_date.strftime("%A, %B %d, %Y")
        events_by_date.setdefault(date_key, []).append(event)

    lines = [
        "Subject: DO214 Events Digest (Next 2 Months)",
        "",
        "Hi there,",
        "",
        "Here are the current and upcoming DO214 events for the next two months.",
        "They are sorted by date (descending) and ranked by fun score per day.",
        "",
    ]

    for date_key in sorted(
        events_by_date.keys(),
        key=lambda key: datetime.strptime(key, "%A, %B %d, %Y"),
        reverse=True,
    ):
        lines.append(date_key)
        lines.append("-" * len(date_key))
        for event in sorted(
            events_by_date[date_key],
            key=lambda e: e.fun_score,
            reverse=True,
        ):
            time_str = event.start_date.strftime("%I:%M %p").lstrip("0")
            categories = ", ".join(event.categories)
            lines.append(
                f"• {event.title} ({time_str}) [Fun score: {event.fun_score}]\n"
                f"  Categories: {categories}\n"
                f"  {event.url}"
            )
        lines.append("")

    lines.append("Have fun!")
    return "\n".join(lines)


def generate_email(url: str = URL) -> str:
    html = fetch_page_html(url)
    soup = BeautifulSoup(html, "html.parser")

    events = parse_json_ld_events(soup)
    if not events:
        events = parse_fallback_events(soup)

    now = datetime.now(timezone.utc)
    filtered = [event for event in events if within_next_two_months(event, now)]
    for event in filtered:
        event.fun_score = fun_score(event)
        event.categories = categorize_event(event)

    sorted_events = sorted(filtered, key=lambda e: e.start_date, reverse=True)
    return build_email_body(sorted_events)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape DO214 events and build an email-ready list."
    )
    parser.add_argument(
        "--output",
        help="Write the email body to this file instead of stdout.",
    )
    parser.add_argument(
        "--url",
        default=URL,
        help="Events listing URL to scrape.",
    )
    args = parser.parse_args()

    email_body = generate_email(args.url)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(email_body)
    else:
        print(email_body)


if __name__ == "__main__":
    main()
