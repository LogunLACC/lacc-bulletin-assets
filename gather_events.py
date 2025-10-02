from playwright.sync_api import sync_playwright
import json
import os
from datetime import datetime
import time

LOCATIONS = {
    "Chester, CA": "https://allevents.in/chester-ca/all",
    "Susanville, CA": "https://allevents.in/susanville/all"
}

## "Quincy, CA": "https://allevents.in/quincy-ca/all"

OUTPUT_FILE = "events.json"

current_year = datetime.now().year
all_events   = []

def load_existing_events():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_events(events):
    existing = load_existing_events()
    all_combined = existing + events

    unique_events = {
        (e["title"], e["date"], e["location"]): e
        for e in all_combined
        if e["title"] and e["date"]
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(unique_events.values()), f, indent=2)
    print(f"✅ Saved {len(unique_events)} total unique events to events.json")

def scrape_allevents(locations):
    all_events = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 420, "height": 800})
        page = context.new_page()

        for location, url in locations.items():
            print(f"\n📍 Scraping {location}...")
            try:
                page.goto(url, timeout=60000)

                try:
                    page.click("button[aria-label='Close']", timeout=3000)
                except:
                    pass

                page.wait_for_selector("li.event-card", timeout=30000)

                # Scroll & click View More
                for _ in range(20):
                    try:
                        if page.query_selector("button:has-text('View More')"):
                            page.click("button:has-text('View More')")
                            time.sleep(2)
                        else:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            time.sleep(2)
                    except:
                        break

                cards = page.query_selector_all("li.event-card")

                print(f"🧾 Found {len(cards)} event cards in {location}")

                for card in cards:
                    title_el    = card.query_selector("h3")
                    location_el = card.query_selector("div.subtitle")
                    date_el     = card.query_selector("div.date")
                    link_el     = card.query_selector("a[href*='/']")
                    img_el      = card.query_selector("img.banner-img")

                    title         = title_el.inner_text().strip() if title_el else "Untitled Event"
                    location_text = location_el.inner_text().strip() if location_el else None
                    date_text     = date_el.inner_text().strip() if date_el else None
                    event_url     = link_el.get_attribute("href") if link_el else None
                    image_url     = (
                        img_el.get_attribute("data-src")
                        or img_el.get_attribute("src")
                        if img_el
                        else None
                    )

                    # build the full date string BEFORE parsing
                    full_text = f"{date_text} {current_year}"  # e.g. "Sat, 07 Aug 2025"

                    try:
                        dt          = datetime.strptime(full_text, "%a, %d %b %Y")
                        pretty_date = dt.strftime("%a, %d %b %Y")
                    except (ValueError, TypeError):
                        pretty_date = None

                    all_events.append({
                        "image":      image_url,
                        "title":      title,
                        "date":       pretty_date,
                        "location_t": location_text,
                        "url":        event_url,
                        "source":     f"AllEvents – {location_text or 'Unknown'}",
                        "location":   location_text
                    })

            except Exception as e:
                print(f"❌ Failed to scrape {location}: {e}")

        browser.close()
    return all_events

if __name__ == "__main__":
    events = scrape_allevents(LOCATIONS)
    print(f"\n📦 Scraped {len(events)} new events total.")
    save_events(events)
