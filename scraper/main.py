"""
main.py
-------
FastAPI app exposing the Google Maps scraper as an HTTP API.
Called by n8n via HTTP Request node.

Endpoints:
  GET  /health              — liveness check
  GET  /today-queries       — returns today's rotation queries
  POST /scrape/gmaps        — scrape a single query+location
  POST /scrape/gmaps/batch  — scrape multiple queries sequentially (Phase 2)
  POST /enrich/website      — fetch + parse a business website (Phase 2)
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from gmaps_scraper import scrape_gmaps
from query_rotator import get_today_india_queries, get_today_international_queries
from website_enricher import enrich_website

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Lifespan (Playwright browser install check) ────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("VoxAI GMaps Scraper API starting up...")
    yield
    logger.info("VoxAI GMaps Scraper API shutting down.")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="VoxAI GMaps Scraper API",
    description="Google Maps scraper for outbound lead generation. Called by n8n.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response Models ─────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    query: str = Field(..., example="coaching institutes")
    location: str = Field(..., example="Ludhiana")
    max_results: int = Field(default=10, ge=1, le=50)
    region: str = Field(default="india", pattern="^(india|intl)$")
    country: str = Field(default="IN", example="IN")

    model_config = {"json_schema_extra": {
        "example": {
            "query": "coaching institutes",
            "location": "Ludhiana",
            "max_results": 10,
            "region": "india",
            "country": "IN",
        }
    }}


class BatchScrapeRequest(BaseModel):
    queries: list[ScrapeRequest] = Field(..., max_length=30)


class WebsiteEnrichRequest(BaseModel):
    url: str = Field(..., example="https://www.example.com")


class TodayQueriesResponse(BaseModel):
    india: list[dict]
    international: list[dict]
    india_count: int
    international_count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Liveness probe — n8n uses this to verify the scraper is reachable."""
    return {
        "status": "ok",
        "service": "voxai-gmaps-scraper",
        "proxy_configured": bool(os.getenv("PROXY_URL")),
    }


@app.get("/today-queries", response_model=TodayQueriesResponse)
async def today_queries(
    india_count: int = 30,
    intl_count: int = 20,
):
    """
    Return today's rotation queries for both regions.
    n8n can call this first to know what queries to scrape today.
    """
    india = get_today_india_queries(india_count)
    intl = get_today_international_queries(intl_count)
    return {
        "india": india,
        "international": intl,
        "india_count": len(india),
        "international_count": len(intl),
    }


@app.post("/scrape/gmaps")
async def scrape_single(req: ScrapeRequest):
    """
    Scrape Google Maps for one query + location.
    Returns a list of lead objects matching the spec schema.
    """
    logger.info(
        "Scraping: query='%s' location='%s' max=%d region=%s country=%s",
        req.query, req.location, req.max_results, req.region, req.country,
    )
    try:
        leads = await scrape_gmaps(
            query=req.query,
            location=req.location,
            max_results=req.max_results,
            region=req.region,
            country=req.country,
        )
        return {
            "success": True,
            "query": req.query,
            "location": req.location,
            "count": len(leads),
            "leads": leads,
        }
    except Exception as e:
        logger.error("Scrape failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scrape/gmaps/batch")
async def scrape_batch(req: BatchScrapeRequest):
    """
    Scrape multiple queries sequentially.
    Used in Phase 2 for the full 30 India + 20 international daily batch.
    Rate-limited to run queries one by one (no parallel browser instances).
    """
    all_leads: list[dict] = []
    errors: list[dict] = []

    for item in req.queries:
        logger.info("Batch item: %s in %s", item.query, item.location)
        try:
            leads = await scrape_gmaps(
                query=item.query,
                location=item.location,
                max_results=item.max_results,
                region=item.region,
                country=item.country,
            )
            all_leads.extend(leads)
        except Exception as e:
            logger.error("Batch item failed (%s in %s): %s", item.query, item.location, e)
            errors.append({"query": item.query, "location": item.location, "error": str(e)})

    return {
        "success": True,
        "total_leads": len(all_leads),
        "error_count": len(errors),
        "errors": errors,
        "leads": all_leads,
    }


@app.post("/enrich/website")
async def enrich_website_endpoint(req: WebsiteEnrichRequest):
    """
    Fetch and parse a business website.
    Returns: title, meta_description, body_text_excerpt, has_chat_widget,
             chat_widgets_found, fetch_success.
    n8n calls this per lead (Phase 2) immediately after inserting the lead.
    """
    logger.info("Enriching website: %s", req.url)
    result = await enrich_website(req.url)
    return result
