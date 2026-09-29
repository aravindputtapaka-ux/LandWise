import asyncio
import os
from urllib.parse import urlparse

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
                    "User-Agent": "LandWiseAI/2.0"
                },
            )

            response.raise_for_status()

            return response.json()

    except (
        httpx.HTTPError,
        ValueError,
    ) as exc:

        raise SourceServiceError(
            f"Tavily request failed: {exc}"
        )


# ============================================================
# TAVILY SEARCH
# ============================================================

async def tavily_search(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    search_depth: str | None = None,
    include_answer: bool = False,
) -> dict:

    payload = {
        "api_key": _key(),
        "query": query,

        # BASIC is substantially cheaper/faster than ADVANCED.
        "search_depth": search_depth or os.getenv(
            "TAVILY_SEARCH_DEPTH",
            "basic",
        ),

        "include_answer": include_answer,
        "include_raw_content": False,

        "max_results": min(
            max_results,
            10,
        ),
    }

    if include_domains:
        payload["include_domains"] = (
            include_domains
        )

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
# NORMAL PROPERTY SEARCH
# ============================================================

async def search_and_extract(
    location: str,
    property_type: str,
    bhk: str | None = None,
    property_status: str | None = None,
) -> tuple[dict, list[dict]]:

    p = property_type.replace(
        "_",
        " ",
    )

    bhk_text = (
        f" {bhk}"
        if bhk
        else ""
    )

    status_text = (
        f" {property_status}"
        if property_status
        else ""
    )

    # --------------------------------------------------------
    # ONE primary query
    # --------------------------------------------------------

    primary_query = (
        f"{p}{bhk_text}"
        f"{status_text} "
        f"{location} "
        f"price area "
        f"sq ft sq yard "
        f"recent property listing"
    )

    preferred = [
        "99acres.com",
        "housing.com",
        "1acre.in",
        "magicbricks.com",
        "nobroker.in",
    ]

    # --------------------------------------------------------
    # PRIMARY SEARCH
    # --------------------------------------------------------

    response = await tavily_search(
        primary_query,
        max_results=5,
        include_domains=preferred,
    )

    selected = []

    for item in response.get(
        "results",
        [],
    ):

        if item.get("url"):
            selected.append(item)

    # --------------------------------------------------------
    # Parse Tavily snippets FIRST.
    # This often eliminates the need for Extract.
    # --------------------------------------------------------

    observations = []

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
                bhk,
            )

            observations.extend(
                to_dict(x)
                for x in obs[:5]
            )

        except Exception:
            continue

    # --------------------------------------------------------
    # FALLBACK:
    # Only search again if the first query produced
    # insufficient price+area evidence.
    # --------------------------------------------------------

    if len(observations) < 2:

        fallback_query = (
            f"{p}{bhk_text} "
            f"{location} "
            f"property asking price "
            f"price per sq ft"
        )

        try:

            fallback = await tavily_search(
                fallback_query,
                max_results=5,
                include_domains=preferred,
            )

            for item in fallback.get(
                "results",
                [],
            ):

                url = item.get("url")

                if not url:
                    continue

                if any(
                    r.get("url") == url
                    for r in selected
                ):
                    continue

                selected.append(item)

                content = (
                    item.get("content")
                    or item.get("snippet")
                    or ""
                )

                try:

                    obs = extract_observations(
                        url,
                        item.get("title", ""),
                        content,
                        property_type,
                        bhk,
                    )

                    observations.extend(
                        to_dict(x)
                        for x in obs[:5]
                    )

                except Exception:
                    continue

        except Exception:
            pass

    # If the preferred property portals have no usable evidence for a small
    # locality, make one Tavily-wide search instead of returning an empty price.
    # This is still Tavily-only and the parser continues to require explicit
    # price + area evidence before accepting an observation.
    if len(observations) < 2:
        broad_query=(
            f"{p}{bhk_text} {location} land plot property price "
            f"rate per sq ft sale listing"
        )
        try:
            broad=await tavily_search(broad_query,max_results=8)
            for item in broad.get("results",[]):
                url=item.get("url")
                if not url:
                    continue
                content=item.get("content") or item.get("snippet") or ""
                if not content:
                    continue
                try:
                    obs=extract_observations(url,item.get("title", ""),content,property_type,bhk)
                    observations.extend(to_dict(x) for x in obs[:5])
                    selected.append(item)
                except Exception:
                    continue
        except Exception:
            pass

    # --------------------------------------------------------
    # DEDUPLICATE OBSERVATIONS
    # --------------------------------------------------------

    unique = {}

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
            round(
                float(
                    observation.get(
                        "area"
                    )
                    or 0
                ),
                3,
            ),
            observation.get(
                "area_unit"
            ),
        )

        unique[key] = observation

    observations = list(
        unique.values()
    )[:40]

    raw = {
        "results": selected[:10],
        "query": primary_query,
    }

    return raw, observations


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