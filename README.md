# LandWise AI — Evidence-First Property Price Intelligence

LandWise AI estimates current property prices from live web evidence discovered by Tavily. It deliberately separates **source discovery**, **content extraction**, **deterministic price/area parsing**, **normalization**, **comparables**, and **historical ML**.

## Critical methodology

The application does **not** feed URLs or arbitrary web numbers directly into an ML model. It also does not use Gemini/OpenAI/Claude.

```text
User location/property
        ↓
Tavily Search
        ↓
Candidate URLs
        ↓
Tavily Extract (selected URLs only)
        ↓
Deterministic property observation parser
        ↓
price + area + unit + source validation
        ↓
canonical ₹/sq ft
        ↓
┌───────────────────────────────┐
│ Current comparable estimator  │ ← primary realtime answer
└───────────────────────────────┘
        ↓
Tavily year-wise historical prompt
        ↓
4 completed annual ₹/sq-ft points
        ↓
Bayesian Ridge ML forecast
        ↓
Next 5 years
```

### Why this is different from the previous implementation

The old implementation had two serious modeling problems:

1. It used `canonical_price_per_sqft` as both the **target and an input feature**, which is target leakage.
2. It converted price-per-unit in the wrong direction. For example, `₹4,004/sq ft` must equal `₹174,414,240/acre`, not `₹0.09/acre`.

Both are fixed in this version.

## Source handling

Tavily Search is used to discover current candidate sources. Tavily's documentation recommends a two-step pattern when detailed content is needed: search first, then extract only selected relevant URLs; extracting raw content from every search result increases latency.

The application therefore:

- searches for recent property listings
- selects relevant property portals/auction/classified sources
- extracts only selected pages
- rejects malformed numbers
- requires explicit price evidence and a nearby area/unit before creating a total-price observation
- accepts explicit statements such as `₹950 per sq yard`
- never treats an Instagram discovery page or unrelated numeric text as a price label

## Historical ML forecast

For land/plot searches, the history pipeline is Tavily-only. It sends this exact prompt:

```text
according to year wise give me past 4 years land prices per sq ft data in {Location} in tabular form
```

The four completed calendar years are extracted and normalized to INR/sq ft. A small-sample **Bayesian Ridge regression on log(price_per_sqft)** then predicts the next five years. A leave-one-out MAPE diagnostic is returned with the model; it is a diagnostic, not a guarantee of future market accuracy.

Google Search and Google AI Overview are not used by the land price/history/forecast flow.

## Affordability UX update (v5.1)
- Land/Plot affordability returns purchasable area in sq ft, sq yd, sq m, acre, hectare, cent, gunta, marla and bigha (bigha is approximate/jurisdiction-dependent).
- Flat/Apartment, Villa and Independent House affordability no longer ask the user for BHK. The system evaluates 1–5 BHK scenarios for the same budget using current evidence.
- Residential affordability retains Property Status (Ready to Move, Under Construction, Resale) as a search constraint.
- Commercial affordability returns practical categories: Office, Shop, Commercial Floor and Warehouse.
- The Price tab behavior is intentionally unchanged.

## Accounts, landing page and search history (v5.3)

- **Landing page.** A marketing page is shown first, with "Log in" and "Sign up" calls to action. The estimator itself now requires an account.
- **Login / signup.** Passwords are hashed with salted PBKDF2-HMAC-SHA256 (260k iterations) — no plaintext storage. Sessions are JWTs (`pyjwt`), valid for 30 days by default (`JWT_EXPIRE_MINUTES`), sent as a `Bearer` token.
- **No more `market_observations` collection.** MongoDB now has a single `users` collection. Each user document is:
  ```json
  {
    "_id": "uuid",
    "name": "...",
    "email": "...",
    "password_hash": "...",
    "created_at": "...",
    "search_history": [
      {
        "id": "uuid",
        "type": "property_price | affordability | source_ingest",
        "request": { ... the request body ... },
        "response": { ... the full API response ... },
        "observations": [ ... raw evidence rows collected for this search ... ],
        "created_at": "..."
      }
    ]
  }
  ```
  The last 200 searches per user are kept. `GET /auth/history` lists them; `DELETE /auth/history/{id}` removes one.
- **Historical ML data** is reconstructed on demand by aggregating the `observations` embedded in every user's `search_history` (a two-stage `$unwind` over the `users` collection), instead of reading a separate collection. A local `data/users.json` file is used as an automatic fallback whenever MongoDB isn't reachable, so the app keeps working in dev without a DB.
- **Protected endpoints.** `/property-price`, `/affordability` and `/ingest-sources` all require a valid `Authorization: Bearer <token>` header; the frontend attaches this automatically once you're logged in.

## ML / price-accuracy fix (v5.3)

The previous version blended a fixed 15% ML correction into every estimate regardless of how good the model actually was. This is now gated on real validation accuracy:

- The historical model is only trusted when its held-out validation shows **R² > 0.15** and **MAPE < 45%**. Otherwise the estimate is comparable-evidence only.
- Even a trusted model's prediction is **clamped to 0.5×–2× the comparable-evidence price** before blending, so a bad extrapolation on sparse historical data can never dominate the final number.
- The blend weight now scales with the model's validated R² (5%–30%) instead of a hard-coded 15%.
- `model_used` in the API response now reports the actual validated R² / MAPE that were used, instead of a static string.

## Run

```bat
cd backend
conda activate LLM
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

Frontend:

```bat
cd frontend
npm install
npm run dev
```

## Test the parser

```bat
cd backend
python -m pytest
```

The parser includes tests for:

- `₹950 per sq yard`
- `₹15 lakh for 166 sq yd`
- unrelated numbers/dates
- sq ft → acre conversion

It also includes tests for password hashing, JWT issuance, the local user-store
fallback (create user / search history / historical-observation aggregation),
and the ML confidence-gating logic.

## Important limitations

- Web listings are generally asking prices, not guaranteed transaction prices.
- A locality with little public evidence should return low confidence or no result rather than a fabricated estimate.
- Social-media discovery URLs are not automatically valid training labels. Public accessibility and platform terms determine what can be extracted.
- Bigha is jurisdiction-dependent and is therefore only an approximate unit in the current implementation.
- The current production normalization is INR-only.
- The ML historical dataset now starts empty after this upgrade (it used to live in `market_observations`); it will rebuild automatically as logged-in users run searches, and ML corrections stay disabled until there is enough validated data.

## Tavily reference

Tavily's current guidance describes `include_raw_content` as a way to retrieve parsed page content, but also recommends a two-step search/extraction flow when accuracy and control matter.


## Land history + ML flow

For a land search, the backend uses Tavily for both the current comparable evidence and the requested historical series. The history query is sent exactly as:

```text
according to year wise give me past 4 years land prices per sq ft data in {Location} in tabular form
```

The four completed calendar years are extracted, validated as INR/sq ft, and passed to a Bayesian Ridge model on log price. The model produces the next five years and reports a leave-one-out MAPE diagnostic. Google Search and Google AI Overview are not used by this flow.

### Setup

Install Python dependencies:

```bat
cd backend
pip install -r requirements.txt
```

Install frontend dependencies separately:

```bat
cd frontend
npm install
npm run build
```

For a local LandWise installation, the expected flow is:

1. Log in.
2. Select **Land / Plot**.
3. Enter a location and optional area.
4. Click **Analyze property**.
5. LandWise sends the current-price search and the exact four-year history prompt to Tavily.
6. The history parser extracts year/value pairs and normalizes them to INR/sq ft.
7. Bayesian Ridge ML forecasts the next five years from the extracted annual series.
8. The result and research data are saved under the logged-in user's `search_history`.

### Forecast methodology

The historical series contains only four completed annual observations, so a high-capacity model would overfit. LandWise uses Bayesian Ridge regression on log-transformed price/sq-ft values, reports leave-one-out MAPE as a diagnostic, and applies a wide growth guardrail to prevent runaway extrapolation from noisy web data. The output is a model estimate, not a guaranteed future market price.

### Data-source limitation

Tavily discovers and returns web evidence; it does not guarantee that every locality has a reliable four-year historical table. If fewer than three usable annual values can be extracted, the API returns the history it found and marks the ML forecast as unavailable rather than inventing missing prices.

## Gmail SMTP OTP authentication

Signup and forgot-password use a 6-digit email OTP through Gmail SMTP. OTPs expire after 10 minutes, are hashed at rest, and are invalidated after successful use or too many failed attempts.

Set these values in `backend/.env`:

```env
GMAIL_SMTP_HOST=smtp.gmail.com
GMAIL_SMTP_PORT=587
GMAIL_SMTP_USERNAME=your_gmail_address@gmail.com
GMAIL_SMTP_APP_PASSWORD=your_16_character_google_app_password
GMAIL_FROM_EMAIL=your_gmail_address@gmail.com
OTP_HASH_SECRET=your_long_random_secret
OTP_EXPIRE_MINUTES=10
OTP_MAX_ATTEMPTS=5
```

Use a Google **App Password**, not your normal Gmail password. The Gmail account must have 2-Step Verification enabled before an App Password can be created.

Authentication flow:
- Signup -> OTP email -> verify OTP -> account activated -> logged in
- Forgot password -> OTP email -> OTP + new password -> password reset
- Login/signup/reset password fields include an eye button to show/hide the password.
