"""
website_enricher.py
--------------------
Fetches and parses a business website to extract:
  - Page title
  - Meta description
  - First ~2000 characters of visible body text
  - Presence of common live-chat widget scripts (Intercom, Tawk.to, Crisp, etc.)

This runs as a FastAPI endpoint (/enrich/website) called by n8n for each lead
that has a website URL. A missing website is itself a signal for the AI layer
(no digital presence = high-opportunity lead).

Does NOT use Playwright here — a simple HTTPX fetch + BeautifulSoup parse is
sufficient for static content detection. Playwright is reserved for scraping
dynamic Google Maps UI.
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Chat widget fingerprints ───────────────────────────────────────────────────
# These are script src patterns or class names that indicate a live-chat widget
# is already installed on the site. Presence = the business has some customer
# comms tool in place (relevant context for the AI pain-point layer).

CHAT_WIDGET_PATTERNS: list[tuple[str, str]] = [
    ("Intercom",    r"intercom\.io|intercomcdn\.com|js\.intercomcdn\.com"),
    ("Tawk.to",     r"tawk\.to|embed\.tawk\.to"),
    ("Crisp",       r"crisp\.chat|client\.crisp\.chat"),
    ("Tidio",       r"tidio\.com|code\.tidio\.co"),
    ("Drift",       r"drift\.com|js\.drift\.com"),
    ("Zendesk",     r"zendesk\.com|zdassets\.com|ekr\.zdassets\.com"),
    ("Freshchat",   r"freshchat\.com|wchat\.freshchat\.com"),
    ("LiveChat",    r"livechat\.com|cdn\.livechatinc\.com"),
    ("HubSpot",     r"hs-scripts\.com|js\.hubspot\.com"),
    ("WhatsApp Widget", r"wa\.me|api\.whatsapp\.com/send"),
]

# HTTP timeout for website fetches
FETCH_TIMEOUT_SECONDS = 10

# Headers to mimic a real browser (reduces bot blocking on business websites)
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _detect_chat_widgets(html: str) -> tuple[bool, list[str]]:
    """
    Check HTML source for chat widget fingerprints.

    Returns:
        (has_chat_widget: bool, widgets_found: list[str])
    """
    found: list[str] = []
    for name, pattern in CHAT_WIDGET_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            found.append(name)
    return bool(found), found


def _extract_visible_text(soup: BeautifulSoup, max_chars: int = 2000) -> str:
    """
    Extract visible body text, stripping script/style tags.
    Returns first max_chars characters of the cleaned text.
    """
    # Remove invisible elements
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def enrich_website(url: str) -> dict:
    """
    Fetch and parse a business website URL.

    Args:
        url: The website URL (may or may not include https://)

    Returns:
        Dict with: title, meta_description, body_text_excerpt,
                   has_chat_widget, chat_widgets_found, fetch_success, error
    """
    # Normalise URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = {
        "url": url,
        "title": None,
        "meta_description": None,
        "body_text_excerpt": None,
        "has_chat_widget": False,
        "chat_widgets_found": [],
        "fetch_success": False,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            headers=FETCH_HEADERS,
            follow_redirects=True,
            verify=False,  # Some Indian SMB sites have expired/self-signed certs
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        html = response.text

        # ── Parse HTML ────────────────────────────────────────────────────────
        soup = BeautifulSoup(html, "lxml")

        # Title
        title_tag = soup.find("title")
        if title_tag:
            result["title"] = title_tag.get_text(strip=True)

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_desc and meta_desc.get("content"):
            result["meta_description"] = meta_desc["content"].strip()

        # Body text
        result["body_text_excerpt"] = _extract_visible_text(soup)

        # Chat widget detection
        has_widget, widgets = _detect_chat_widgets(html)
        result["has_chat_widget"] = has_widget
        result["chat_widgets_found"] = widgets

        result["fetch_success"] = True
        logger.info("Enriched website: %s | chat_widgets=%s", url, widgets or "none")

    except httpx.TimeoutException:
        result["error"] = "timeout"
        logger.warning("Website fetch timeout: %s", url)

    except httpx.HTTPStatusError as e:
        result["error"] = f"http_{e.response.status_code}"
        logger.warning("Website fetch HTTP error %d: %s", e.response.status_code, url)

    except Exception as e:
        result["error"] = str(e)[:200]
        logger.warning("Website fetch failed: %s | %s", url, e)

    return result


def detect_formal_english(text: str) -> bool:
    """
    Heuristic: return True if text appears to be purely formal English
    (no Hindi/regional script characters, no Hinglish slang patterns).
    Used for language tagging — India leads default to 'hinglish' unless
    the website/ad copy is clearly formal English.
    """
    if not text:
        return False

    # Detect Devanagari or other Indic scripts → definitely not formal English
    indic_pattern = re.compile(
        r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F]"
    )
    if indic_pattern.search(text):
        return False

    # Hinglish trigger words (common code-switch markers)
    hinglish_triggers = [
        "aapke", "aap", "hum", "karo", "kare", "karna", "hai", "hain",
        "nahi", "nahin", "yahan", "wahan", "bahut", "accha", "theek",
        "ji", "bhai", "dost", "sab", "abhi", "sirf"
    ]
    text_lower = text.lower()
    if any(word in text_lower.split() for word in hinglish_triggers):
        return False

    return True


if __name__ == "__main__":
    import asyncio
    import json

    async def test():
        result = await enrich_website("https://www.example.com")
        print(json.dumps(result, indent=2))

    asyncio.run(test())
