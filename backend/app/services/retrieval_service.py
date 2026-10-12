"""Local TF-IDF RAG: private saved searches plus operator-curated documents.

No embedding API or hosted vector database is needed. Exact search selection
wins; lexical retrieval is intentionally modest and can miss paraphrases.
"""
import json
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def rank(query, records, limit=5):
    if not records:
        return []
    try:
        matrix = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), sublinear_tf=True).fit_transform([r['text'] for r in records] + [query])
        scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    except ValueError:
        return []
    return [records[int(i)] for i in scores.argsort()[::-1][:limit] if scores[i] >= 0.035]


def search_record(row):
    req, result = row.get('request', {}), row.get('response', {})
    fields = ['estimated_total_price', 'price_per_unit', 'unit', 'currency', 'confidence',
              'average_price_per_sqft', 'min_price', 'max_price', 'source_summary',
              'budget', 'affordable_area', 'affordable_area_unit', 'notes', 'options',
              'historical_prices', 'forecast_prices']
    context = {'searched_at': row.get('created_at'), 'type': row.get('type'), 'request': req,
               'result': {k: result[k] for k in fields if k in result}}
    return {'id': 'search:' + row['id'], 'kind': 'saved_search',
            'title': f"{req.get('location', 'Property')} • {row.get('created_at', '')}",
            'urls': [u for u in result.get('sources', []) if isinstance(u, str) and u.startswith(('https://', 'http://'))][:5],
            'text': json.dumps(context, ensure_ascii=False, default=str)[:10000]}


def retrieve(db, uid, question, history, selected_search_id=None):
    # Never aggregate observations across accounts for personal context.
    user = db.users.find_one({'_id': uid}, {'search_history': 1}) or {}
    rows = [r for r in user.get('search_history', []) if r.get('type') in ('property_price', 'affordability')]
    records = [search_record(r) for r in rows]
    docs = [{k: d[k] for k in ('id', 'kind', 'title', 'text', 'urls')} for d in
            db.knowledge_chunks.find({}, {'_id': 0}).sort('id', 1).limit(2000)]
    selected = next((r for r in records if r['id'] == 'search:' + str(selected_search_id)), None)
    if selected_search_id and not selected:
        # Do not silently substitute another property if its selected source was removed.
        return [], 'The selected saved search is no longer available. Ask the user to select another search.'
    hints = ' '.join(m['content'][:1000] for m in history[-4:] if m['role'] == 'user')
    matches = rank(question, records + docs)
    if not matches or re.search(r'\b(it|its|that|this|those|same)\b', question.lower()):
        matches += rank(question + ' ' + hints, records + docs, 3)
    if re.search(r'\b(latest|last|recent)\b', question.lower()) and records and not selected:
        matches.insert(0, records[0])
    if selected:
        matches.insert(0, selected)
    unique = {r['id']: r for r in matches}
    return list(unique.values())[:5], ''

def wants_estimation_list(question: str) -> bool:
    text = question.lower()

    list_words = ("list", "show", "display")
    record_words = (
        "estimation", "estimate", "search", "history",
        "valuation", "affordability",
    )

    return (
        any(word in text for word in list_words)
        and any(word in text for word in record_words)
    )


def indian_number(value) -> str:
    number = f"{float(value):.0f}"
    sign = "-" if number.startswith("-") else ""
    number = number.lstrip("-")

    if len(number) <= 3:
        return sign + number

    last_three = number[-3:]
    remaining = number[:-3]
    groups = []

    while remaining:
        groups.insert(0, remaining[-2:])
        remaining = remaining[:-2]

    return sign + ",".join(groups + [last_three])


def list_saved_estimations(db, user_id: str) -> str:
    user = db.users.find_one(
        {"_id": user_id},
        {"search_history": 1},
    ) or {}

    records = [
        item
        for item in user.get("search_history", [])
        if item.get("type") in ("property_price", "affordability")
    ]

    if not records:
        return (
            "You do not have any saved estimations in this account yet. "
            "Run a property or affordability search first."
        )

    lines = [
        f"You have **{len(records)} saved estimations** "
        "(newest first):"
    ]

    for index, item in enumerate(records, start=1):
        request = item.get("request") or {}
        result = item.get("response") or {}

        location = request.get("location") or result.get(
            "location", "Location unavailable"
        )
        property_type = str(
            request.get("property_type")
            or result.get("property_type")
            or "property"
        ).replace("_", " ")

        saved_date = str(item.get("created_at") or "")[:10]
        details = []

        if item.get("type") == "property_price":
            area = request.get("area")
            unit = request.get("area_unit") or "sq ft"

            if area is not None:
                details.append(f"{float(area):g} {unit}")

            total = result.get("estimated_total_price")
            rate = result.get("price_per_unit")
            currency = result.get("currency") or "INR"
            symbol = "₹" if currency == "INR" else f"{currency} "

            if total is not None:
                details.append(
                    f"estimated total **{symbol}{indian_number(total)}**"
                )
            elif rate is not None:
                rate_unit = result.get("unit") or unit
                details.append(
                    f"estimated rate **{symbol}{indian_number(rate)} "
                    f"per {rate_unit}**"
                )
            else:
                details.append("price unavailable")
        else:
            budget = request.get("budget")
            if budget is not None:
                currency = request.get("currency") or "INR"
                symbol = "₹" if currency == "INR" else f"{currency} "
                details.append(
                    f"affordability budget **{symbol}{indian_number(budget)}**"
                )

            area = result.get("affordable_area")
            if area is not None:
                unit = result.get("affordable_area_unit") or "sq ft"
                details.append(f"approximately {float(area):,.2f} {unit}")

        if saved_date:
            details.append(f"saved on {saved_date}")

        lines.append(
            f"{index}. **{location}** — {property_type}; "
            + "; ".join(details)
            + "."
        )

    lines.append(
        "These are saved results, not updated market prices. "
        "Your account retains up to 200 search-history entries."
    )

    return "\n\n".join(lines)