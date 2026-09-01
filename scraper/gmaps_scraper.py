"""
gmaps_scraper.py
----------------
Core Google Maps scraper using Playwright + playwright-stealth.
Designed to be called from main.py (FastAPI) or run standalone for testing.

Anti-detection measures applied:
  - playwright-stealth to mask headless browser fingerprint
  - Randomized delays between all actions (jitter)
  - Incremental scroll steps (mimics human behaviour)
  - PROXY_URL env var support (wire up a residential proxy before production use)
  - Logs a warning if phone numbers appear to be stripped by Google (bot detection)
"""

import asyncio
import logging
import os
import random
import re
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import stealth_async

from phone_normalizer import normalize_e164

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
PROXY_URL = os.getenv("PROXY_URL")  # e.g. "http://user:pass@proxy-host:port"
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
MAX_RETRIES = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _random_delay(min_ms: int = 800, max_ms: int = 2400) -> None:
    """Sleep for a random duration to mimic human pacing."""
    delay = random.randint(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


def _build_proxy_config() -> Optional[dict]:
    """Parse PROXY_URL into Playwright's proxy config dict, or None if unset."""
    if not PROXY_URL:
        return None
    # Playwright expects: { "server": "...", "username": "...", "password": "..." }
    match = re.match(r"https?://(?:([^:]+):([^@]+)@)?(.+)", PROXY_URL)
    if match:
        username, password, server = match.groups()
        proxy: dict = {"server": f"http://{server}"}
        if username:
            proxy["username"] = username
        if password:
            proxy["password"] = password
        return proxy
    return {"server": PROXY_URL}


def _extract_phone_from_text(text: str) -> Optional[str]:
    """Pull the first phone-like string from arbitrary text."""
    # Matches common phone formats: +91 98765 43210, 9876543210, 050-123-4567, etc.
    pattern = r"(\+?\d[\d\s\-().]{7,}\d)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


async def _dismiss_consent_banner(page: Page) -> None:
    """Dismiss Google consent/cookie banners that appear in some regions."""
    try:
        btn = page.locator('button:has-text("Accept all"), button:has-text("Reject all"), button:has-text("I agree")')
        if await btn.count() > 0:
            await btn.first.click()
            await _random_delay(500, 1000)
    except Exception:
        pass  # Banner not present — that's fine


async def _extract_listing_details(page: Page, result_url: str) -> dict:
    """
    Open a listing detail panel and extract structured data.
    Called after clicking on a result card in the sidebar.
    """
    await _random_delay(1200, 2500)

    details: dict = {}

    try:
        # Business name — h1 in the detail panel
        name_el = page.locator('h1.DUwDvf, h1[data-item-id]').first
        if await name_el.count() > 0:
            details["business_name"] = (await name_el.inner_text()).strip()

        # Category
        cat_el = page.locator('button.DkEaL, span.mgr77e').first
        if await cat_el.count() > 0:
            details["category"] = (await cat_el.inner_text()).strip()

        # Address
        addr_el = page.locator('[data-item-id="address"]').first
        if await addr_el.count() > 0:
            details["address"] = (await addr_el.inner_text()).strip()

        # Phone number
        phone_el = page.locator('[data-item-id^="phone:tel"]').first
        if await phone_el.count() > 0:
            raw_phone_text = await phone_el.get_attribute("data-item-id") or ""
            # data-item-id = "phone:tel:+919876543210"
            phone_match = re.search(r"phone:tel:(.+)", raw_phone_text)
            if phone_match:
                details["phone"] = phone_match.group(1).strip()
        
        # Fallback: look for any tel: link on the page
        if not details.get("phone"):
            tel_link = page.locator('a[href^="tel:"]').first
            if await tel_link.count() > 0:
                href = await tel_link.get_attribute("href") or ""
                details["phone"] = href.replace("tel:", "").strip()

        # Website
        website_el = page.locator('[data-item-id="authority"]').first
        if await website_el.count() > 0:
            details["website"] = (await website_el.inner_text()).strip()

        # Rating
        rating_el = page.locator('span.MW4etd').first
        if await rating_el.count() > 0:
            try:
                details["rating"] = float((await rating_el.inner_text()).strip())
            except ValueError:
                pass

        # Review count
        reviews_el = page.locator('span.UY7F9').first
        if await reviews_el.count() > 0:
            raw_reviews = (await reviews_el.inner_text()).strip()
            count_match = re.search(r"[\d,]+", raw_reviews.replace(",", ""))
            if count_match:
                try:
                    details["review_count"] = int(count_match.group().replace(",", ""))
                except ValueError:
                    pass

    except Exception as e:
        logger.warning("Error extracting listing details: %s", e)

    return details


async def scrape_gmaps(
    query: str,
    location: str,
    max_results: int,
    region: str,
    country: str,
) -> list[dict]:
    """
    Scrape Google Maps for businesses matching query + location.

    Args:
        query:       e.g. "coaching institutes"
        location:    e.g. "Ludhiana" or "Dubai, UAE"
        max_results: Maximum number of listings to return
        region:      "india" or "intl"
        country:     ISO 2-letter code, e.g. "IN", "AE"

    Returns:
        List of lead dicts matching the spec schema (Section 4.1).
    """
    proxy_config = _build_proxy_config()
    if not proxy_config:
        logger.warning(
            "No PROXY_URL set. Running without proxy. "
            "Google may strip phone numbers at scale. Acceptable for Phase 1 testing."
        )

    leads: list[dict] = []
    search_term = f"{query} in {location}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with async_playwright() as p:
                browser_args = {
                    "headless": HEADLESS,
                    "args": ["--no-sandbox", "--disable-setuid-sandbox"],
                }
                if proxy_config:
                    browser_args["proxy"] = proxy_config

                browser = await p.chromium.launch(**browser_args)
                context: BrowserContext = await browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                )
                page = await context.new_page()

                # Apply stealth patches (masks navigator.webdriver, etc.)
                await stealth_async(page)

                # Navigate to Google Maps
                await page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
                await _dismiss_consent_banner(page)
                await _random_delay(1000, 2000)

                # Type the search query
                search_box = page.locator('input#searchboxinput')
                await search_box.fill(search_term)
                await _random_delay(300, 700)
                await search_box.press("Enter")
                await page.wait_for_load_state("networkidle")
                await _random_delay(1500, 3000)

                # Collect result cards from the sidebar
                results_panel = page.locator('div[role="feed"]')
                collected_data: list[dict] = []
                seen_names: set[str] = set()
                scroll_attempts = 0
                max_scroll_attempts = max_results * 3  # Generous ceiling

                while len(collected_data) < max_results and scroll_attempts < max_scroll_attempts:
                    # Find all currently visible result cards
                    cards = results_panel.locator('a[href*="/maps/place/"]')
                    card_count = await cards.count()

                    for i in range(card_count):
                        if len(collected_data) >= max_results:
                            break
                        try:
                            card = cards.nth(i)
                            card_label = await card.get_attribute("aria-label") or ""
                            if not card_label or card_label in seen_names:
                                continue
                            seen_names.add(card_label)

                            # Click the card to open detail panel
                            await card.click()
                            await _random_delay(1500, 3000)

                            details = await _extract_listing_details(page, "")

                            if not details.get("business_name"):
                                details["business_name"] = card_label

                            # Normalize phone
                            raw_phone = details.get("phone")
                            normalized_phone = normalize_e164(raw_phone, country) if raw_phone else None

                            if not raw_phone:
                                logger.warning(
                                    "No phone found for '%s' — Google may be stripping data. "
                                    "Consider adding a residential proxy (PROXY_URL env var).",
                                    details.get("business_name"),
                                )

                            lead = {
                                "business_name": details.get("business_name", ""),
                                "category": details.get("category", ""),
                                "phone_raw": raw_phone,
                                "phone_normalized": normalized_phone,
                                "address": details.get("address", ""),
                                "website": details.get("website"),
                                "rating": details.get("rating"),
                                "review_count": details.get("review_count"),
                                "source": "gmaps",
                                "region": region,
                                "country": country,
                                "scraped_at": datetime.now(timezone.utc).isoformat(),
                            }
                            collected_data.append(lead)

                            # Go back to results list
                            await page.go_back()
                            await _random_delay(1000, 2000)

                        except Exception as e:
                            logger.warning("Error processing card %d: %s", i, e)
                            continue

                    # Scroll the results panel incrementally
                    await results_panel.evaluate(
                        "el => el.scrollBy({ top: 300, behavior: 'smooth' })"
                    )
                    await _random_delay(800, 1600)
                    scroll_attempts += 1

                    # Check if we've hit the end of results
                    end_of_list = page.locator('span.HlvSq')
                    if await end_of_list.count() > 0:
                        logger.info("Reached end of results for query: %s", search_term)
                        break

                leads = collected_data
                await browser.close()
                logger.info(
                    "Scraped %d leads for '%s' (attempt %d/%d)",
                    len(leads), search_term, attempt, MAX_RETRIES
                )
                break  # Success — exit retry loop

        except Exception as e:
            logger.error("Attempt %d/%d failed for query '%s': %s", attempt, MAX_RETRIES, search_term, e)
            if attempt < MAX_RETRIES:
                backoff = 2 ** attempt * random.uniform(1.0, 2.0)
                logger.info("Retrying in %.1f seconds...", backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("All %d attempts failed. Returning empty list.", MAX_RETRIES)

    return leads


if __name__ == "__main__":
    # Quick standalone test: scrape 3 results for a single query
    logging.basicConfig(level=logging.INFO)
    import json

    results = asyncio.run(
        scrape_gmaps(
            query="coaching institutes",
            location="Ludhiana",
            max_results=3,
            region="india",
            country="IN",
        )
    )
    print(json.dumps(results, indent=2))
