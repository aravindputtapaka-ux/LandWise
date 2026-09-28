import asyncio
import os
from datetime import datetime
from urllib.parse import urlparse

from app.services.forecast_service import (
    extract_year_price_pairs,
    parse_historical_text,
)
import httpx
from bs4 import BeautifulSoup

from app.services.price_parser import (
    extract_observations,
    extract_residential_price_only,
    to_dict,
)
from app.services.media_service import youtube_transcript


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class SourceServiceError(Exception):
    pass


def _key() -> str:
    key = os.getenv("TAVILY_API_KEY")

    if not key:
        raise SourceServiceError(
            "TAVILY_API_KEY is not configured"
        )

    return key


# ============================================================
# COMMON TAVILY REQUEST
# ============================================================

async def _post(
    url: str,
    payload: dict,
    timeout: float = 12.0,
) -> dict:

    try:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout,
                connect=4.0,
            ),
            follow_redirects=True,
        ) as client:

            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {_key().strip()}",
                    "Content-Type": "application/json",
                    "User-Agent": "LandWiseAI/2.0",
                },
            )

            response.raise_for_status()

            return response.json()

    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1200] if exc.response is not None else str(exc)
        raise SourceServiceError(
            f"Tavily request failed ({exc.response.status_code}): {detail}"
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceServiceError(f"Tavily request failed: {exc}")


# ============================================================
# TAVILY SEARCH
# ============================================================

async def tavily_search(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    include_answer: bool = False,
) -> dict:

    payload = {
        "api_key": _key(),
        "query": query,

        # BASIC is substantially cheaper/faster than ADVANCED.
        "search_depth": os.getenv(
            "TAVILY_SEARCH_DEPTH",
            "basic",
        ),

        "include_answer": bool(include_answer),
        # Tavily expects a boolean here. Requesting raw page text gives the
        # parser more evidence when the search snippet is too short.
        "include_raw_content": True,
        "chunks_per_source": 3,
        "topic": "general",
        "language": "en",

        # Return more independent results from the one paid search.
        # Tavily documents 0..20 as the valid max_results range.
        "max_results": min(max(1, int(max_results)), 20),
    }

    # Do not send include_domains here. Tavily's include_domains parameter is
    # a restriction, whereas LandWise needs the whole web plus a short list
    # of preferred portals. The caller puts the preferred domains into the
    # natural-language query instead, so one search can return broader web
    # evidence without silently excluding other sources.

    return await _post(
        TAVILY_SEARCH_URL,
        payload,
        timeout=float(
            os.getenv(
                "TAVILY_TIMEOUT",
                "12",
            )
        ),
    )


# ============================================================
# TAVILY EXTRACT
# ============================================================

async def tavily_extract(
    urls: list[str],
    max_urls: int = 3,
) -> dict:

    urls = list(
        dict.fromkeys(
            u for u in urls if u
        )
    )[
        :max(
            1,
            min(
                int(max_urls),
                3,
            ),
        )
    ]

    if not urls:
        return {
            "results": [],
            "failed_results": [],
        }

    payload = {
        "api_key": _key(),
        "urls": urls,
        "extract_depth": "basic",
        "format": "text",
    }

    return await _post(
        TAVILY_EXTRACT_URL,
        payload,
        timeout=float(
            os.getenv(
                "TAVILY_EXTRACT_TIMEOUT",
                "12",
            )
        ),
    )


# ============================================================
# DIRECT URL FETCH
# ============================================================

async def fetch_url(
    url: str,
) -> tuple[str, str]:

    if (
        "youtube.com" in url
        or "youtu.be" in url
    ):
        return await youtube_transcript(url)

    try:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                8.0,
                connect=3.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent":
                    "Mozilla/5.0 LandWiseAI/2.0"
            },
        ) as client:

            response = await client.get(url)

            response.raise_for_status()

            content_type = response.headers.get(
                "content-type",
                "",
            )

            if (
                "text/html" not in content_type
                and "text/plain" not in content_type
            ):
                return "", ""

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            for tag in soup(
                [
                    "script",
                    "style",
                    "noscript",
                ]
            ):
                tag.decompose()

            title = (
                soup.title.get_text(
                    " ",
                    strip=True,
                )
                if soup.title
                else ""
            )

            text = soup.get_text(
                " ",
                strip=True,
            )

            return title, text[:30000]

    except Exception:
        return "", ""


# ============================================================
# URL COLLECTION
# ============================================================

async def collect_from_urls(
    urls: list[str],
    requested_property_type: str,
    bhk: str | None,
    fallback_location: str,
    extract_limit: int = 3,
) -> tuple[list[dict], list[str]]:

    urls = list(
        dict.fromkeys(
            u for u in urls if u
        )
    )[:6]

    if not urls:
        return [], []

    # --------------------------------------------------------
    # IMPORTANT:
    # Don't automatically use Tavily Extract for every URL.
    # First use the search snippets.
    # --------------------------------------------------------

    async def process_url(url):

        try:

            title, content = await fetch_url(url)

            if not content:
                return []

            observations = extract_observations(
                url,
                title,
                content,
                requested_property_type,
                bhk,
            )

            return [
                to_dict(x)
                for x in observations[:5]
            ]

        except Exception:
            return []

    results = await asyncio.gather(
        *(
            process_url(url)
            for url in urls
        ),
        return_exceptions=False,
    )

    all_observations = []
    usable = []

    for url, observations in zip(
        urls,
        results,
    ):

        if observations:

            usable.append(url)

            all_observations.extend(
                observations
            )

    # --------------------------------------------------------
    # Only if direct page parsing failed, use Tavily Extract
    # on a MAXIMUM of 3 URLs.
    # --------------------------------------------------------

    if not all_observations:

        try:

            extracted = await tavily_extract(
                urls,
                max_urls=extract_limit,
            )

            for item in extracted.get(
                "results",
                [],
            ):

                url = item.get("url")

                content = item.get(
                    "raw_content",
                    "",
                )

                if not url or not content:
                    continue

                observations = extract_observations(
                    url,
                    urlparse(url).path.rsplit(
                        "/",
                        1,
                    )[-1],
                    content,
                    requested_property_type,
                    bhk,
                )

                if observations:

                    usable.append(url)

                    all_observations.extend(
                        to_dict(x)
                        for x in observations[:5]
                    )

        except Exception:
            pass

    return (
        all_observations[:30],
        list(dict.fromkeys(usable)),
    )


# ============================================================
# HISTORICAL SEARCH (ONE TAVILY CALL)
# ============================================================

async def search_historical_prices(location: str, years: list[int] | None = None) -> tuple[dict, list[dict]]:
    """One Tavily search + free direct-page reads for historical evidence.

    Tavily is used once. The seven requested portals are preferred, but the
    search is not restricted to them, so other relevant public web evidence
    can also surface. Direct HTTP reads of returned URLs do not consume Tavily
    search credits.
    """
    from app.services.forecast_service import parse_historical_text
    if not years:
        current_year = datetime.now().year
        years = list(range(current_year - 4, current_year))
    year_text = ", ".join(str(y) for y in years)
    domains = ["assetlyhq.com", "baanknet.com", "housing.com", "olx.in", "99acres.com", "instagram.com", "1acre.in"]
    domain_text = ", ".join(domains)
    query = (
        f'"{location}" land plot price history for {year_text}. '
        'Find actual dated land/plot listings, auction records, market reports, or published price evidence. '
        'For each year, identify the year and either an explicit price per sq ft/sq yard or a total price together with land area. '
        f'Prioritize these public sources when relevant: {domain_text}. Also search the wider public web. '
        'Do not invent missing years; exclude flats, apartments, houses and rentals.'
    )
    response = await tavily_search(query, max_results=20, include_answer=False)
    result_items = [r for r in response.get("results", []) if r.get("url")]

    # Parse Tavily snippets/raw content first, then directly read returned pages
    # where publicly accessible. Neither step creates another Tavily search.
    candidates: list[tuple[str, str]] = []
    answer = response.get("answer") or ""
    
    if answer:
        candidates.append(
            (
                answer,
                "",
            )
        )



    for r in result_items:
        url = r.get("url") or ""
        text = " ".join([r.get("title") or "", r.get("content") or "", r.get("raw_content") or ""])
        candidates.append((text, url))

    async def read_result(r):
        url = r.get("url") or ""
        title, content = await fetch_url(url)
        if not content:
            return "", url
        return f"{title}\n{content}", url

    fetched = await asyncio.gather(*(read_result(r) for r in result_items[:20]), return_exceptions=False)
    candidates.extend(fetched)

    points = []
    for text, url in candidates:
        if not text:
            continue

        domain = (
            urlparse(url)
            .netloc
            .lower()
            .removeprefix("www.")
            if url
            else ""
        )

        try:
            # First try structured historical tables.
            parsed = parse_historical_text(
                text,
                location,
                domain,
                url,
            )

            # Then use the more flexible year -> price parser.
            parsed.extend(
                extract_year_price_pairs(
                    text,
                    location,
                    domain,
                    url,
                )
            )

            points.extend(parsed)

        except Exception:
            continue

    allowed = set(years)
    unique = {}
    for p in points:
        if p.year not in allowed:
            continue
        # One source may expose several listings for a year; retain them so
        # the yearly aggregation can use independent observations.
        key = (p.year, round(p.price_per_sqft, 4), p.source_domain, p.source_url, p.evidence[:180])
        unique[key] = p
    historical = list(unique.values())

    return {
        "results": result_items[:20],
        "answer": response.get("answer") or "",
        "query": query,
        "years": years,
        "usage": response.get("usage", {}),
    }, [p.__dict__ for p in historical]


# ============================================================
# NORMAL PROPERTY SEARCH
# ============================================================

async def search_and_extract(
    location: str,
    property_type: str,
    bhk: str | None = None,
    property_status: str | None = None,
) -> tuple[dict, list[dict]]:
    """One broad Tavily search for current comparable land evidence.

    The seven requested domains are preferred, not exclusive. Returned URLs
    are also fetched directly when publicly accessible to improve extraction.
    """
    p = property_type.replace("_", " ")
    bhk_text = f" {bhk}" if bhk else ""
    status_text = f" {property_status}" if property_status else ""
    preferred = [
        "assetlyhq.com", "baanknet.com", "housing.com", "olx.in",
        "99acres.com", "instagram.com", "1acre.in",
    ]
    current_query = (
        f'"{location}" current land plot sale asking price{bhk_text}{status_text}. '
        'Find actual public listings with BOTH an explicit total price and explicit land area, '
        'or an explicit price per sq ft/sq yard. Exclude flats, houses and rentals. '
        f'Prioritize these sources when relevant: {", ".join(preferred)}. Also search the wider public web.'
    )
    response = await tavily_search(current_query, max_results=20, include_answer=False)
    selected = [x for x in response.get("results", []) if x.get("url")]
    observations: list[dict] = []

    async def process_result(item):
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("content") or item.get("snippet") or ""
        raw_content = item.get("raw_content") or ""
        combined = " ".join(x for x in (title, snippet, raw_content) if x)
        out = []
        try:
            out.extend(to_dict(x) for x in extract_observations(url, title, combined, property_type, bhk)[:20])
        except Exception:
            pass
        fetched_title, fetched_content = await fetch_url(url)
        if fetched_content:
            try:
                out.extend(to_dict(x) for x in extract_observations(url, fetched_title or title, fetched_content, property_type, bhk)[:20])
            except Exception:
                pass

        # Location validation must use the whole returned result/page, not the
        # short evidence window attached to an individual price-area pair.
        # Otherwise valid listings are discarded when the locality appears in
        # the title but not beside the numeric values.
        full_text = " ".join(x for x in (title, snippet, raw_content, fetched_title, fetched_content) if x)
        norm_full = "".join(ch.lower() for ch in full_text if ch.isalnum())
        norm_loc = "".join(ch.lower() for ch in location if ch.isalnum())
        tokens = [
            "".join(ch.lower() for ch in token if ch.isalnum())
            for token in location.replace(",", " ").split()
            if len(token.strip()) >= 4
        ]
        score = 1.0 if norm_loc and norm_loc in norm_full else (0.9 if any(t and t in norm_full for t in tokens) else 0.35)
        for row in out:
            row["location_match"] = score
        return out

    batches = await asyncio.gather(*(process_result(item) for item in selected[:20]), return_exceptions=False)
    for batch in batches:
        observations.extend(batch)

    unique = {}
    for observation in observations:
        key = (
            observation.get("source_url"),
            round(float(observation.get("price") or 0), 2),
            round(float(observation.get("area") or 0), 3),
            observation.get("area_unit"),
            round(float(observation.get("canonical_price_per_sqft") or 0), 5),
        )
        unique[key] = observation
    return {"results": selected[:20], "query": current_query, "usage": response.get("usage", {})}, list(unique.values())[:200]


# ============================================================
# AFFORDABILITY SEARCH
# ============================================================

async def search_affordability_options(
    location: str,
    property_type: str,
    property_status: str | None = None,
) -> tuple[dict, list[dict]]:

    p = property_type.replace(
        "_",
        " ",
    )

    status_text = (
        f" {property_status}"
        if property_status
        else ""
    )

    bhks = [
        "1 BHK",
        "2 BHK",
        "3 BHK",
        "4 BHK",
        "5 BHK",
    ]

    preferred = [
        "99acres.com",
        "housing.com",
        "magicbricks.com",
        "nobroker.in",
        "1acre.in",
    ]

    # --------------------------------------------------------
    # IMPORTANT CHANGE:
    #
    # OLD:
    # 5 BHK × 5 queries = 25 Tavily searches
    #
    # NEW:
    # 5 BHK × 1 query = 5 Tavily searches
    # --------------------------------------------------------

    async def search_one_bhk(
        bhk: str,
    ):

        query = (
            f'"{bhk}" '
            f"{p}{status_text} "
            f"{location} "
            f"sale price area"
            )

        try:

            return await tavily_search(
                query,
                max_results=3,
                include_domains=preferred,
            )

        except Exception:

            return {
                "results": []
            }

    responses = await asyncio.gather(
        *(
            search_one_bhk(bhk)
            for bhk in bhks
        ),
        return_exceptions=False,
    )

    selected = []

    # --------------------------------------------------------
    # Attach the BHK that generated each search result.
    # --------------------------------------------------------

    for bhk, response in zip(
        bhks,
        responses,
    ):

        for item in response.get(
            "results",
            [],
        ):

            if not item.get("url"):
                continue

            item = dict(item)

            item["_requested_bhk"] = bhk

            selected.append(item)

    # --------------------------------------------------------
    # Global URL deduplication
    # --------------------------------------------------------

    unique = {}

    for item in selected:

        url = item.get("url")

        if url:
            unique.setdefault(
                url,
                item,
            )

    selected = list(
        unique.values()
    )[:15]

    observations = []

    # --------------------------------------------------------
    # Parse search snippets.
    # NO Tavily Extract here initially.
    # --------------------------------------------------------

    for item in selected:

        url = item.get("url")

        title = (
            item.get("title")
            or ""
        )

        content = (
            item.get("content")
            or item.get("snippet")
            or ""
        )

        if not content:
            continue

        try:

            obs = extract_observations(
                url,
                title,
                content,
                property_type,
                None,
            )

            observations.extend(
                to_dict(x)
                for x in obs[:5]
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # Price-only evidence is useful for residential
        # affordability.
        # ----------------------------------------------------

        requested_bhk = item.get(
            "_requested_bhk"
        )

        if requested_bhk:

            try:

                price_only = (
                    extract_residential_price_only(
                        url,
                        title,
                        content,
                        property_type,
                        requested_bhk,
                    )
                )

                observations.extend(
                    price_only
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # Deduplicate observations
    # --------------------------------------------------------

    unique_obs = {}

    for observation in observations:

        key = (
            observation.get(
                "source_url"
            ),
            round(
                float(
                    observation.get(
                        "price"
                    )
                    or 0
                ),
                2,
            ),
            observation.get(
                "bhk"
            ),
            round(
                float(
                    observation.get(
                        "canonical_price_per_sqft"
                    )
                    or 0
                ),
                5,
            ),
        )

        unique_obs[key] = observation

    observations = list(
        unique_obs.values()
    )[:100]

    observations = [
        o
        for o in observations
        if o.get(
            "property_type"
        ) in {
            property_type,
            "flat",
            "villa",
            "independent_house",
        }
    ]

    raw = {
        "results": selected,
        "query": (
            f"5 targeted BHK searches "
            f"for {location}"
        ),
    }

    return raw, observations