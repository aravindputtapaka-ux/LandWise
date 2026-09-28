# LandWise — Land Price Analysis & Forecasting Platform

> **Land intelligence for smarter property decisions.**

LandWise is a full-stack property-market intelligence platform that discovers public land and property-price evidence from the web, validates and normalizes comparable observations to **INR per square foot**, analyzes historical price trends, evaluates affordability, and forecasts future land-price trends using a conservative local machine-learning/statistical model.

The platform is designed around an **evidence-first** principle: it does not manufacture a property price when the available public evidence is insufficient.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [How LandWise Works](#how-LandWise-works)
- [Two-Search Data Pipeline](#two-search-data-pipeline)
- [Historical Price Forecasting](#historical-price-forecasting)
- [Current Price Estimation](#current-price-estimation)
- [Data Sources](#data-sources)
- [Accuracy and Data-Quality Safeguards](#accuracy-and-data-quality-safeguards)
- [Property Types](#property-types)
- [Affordability Analysis](#affordability-analysis)
- [Technology Stack](#technology-stack)
- [Project Architecture](#project-architecture)
- [API Overview](#api-overview)
- [Installation](#installation)
- [Running the Backend](#running-the-backend)
- [Running the Frontend](#running-the-frontend)
- [Testing](#testing)
- [Environment Variables](#environment-variables)
- [Example Workflow](#example-workflow)
- [Important Methodology](#important-methodology)
- [Limitations](#limitations)
- [Security and Responsible Data Use](#security-and-responsible-data-use)
- [Future Enhancements](#future-enhancements)

---

## Overview

LandWise separates **web discovery, content extraction, deterministic parsing, normalization, current comparable estimation, historical analysis, and forecasting**.

It does not feed arbitrary web numbers directly into a model.

```text
User
  │
  │ Location + property details
  ▼
Tavily Search
  │
  ├── Historical evidence search
  │
  └── Current comparable search
  │
  ▼
Candidate public sources
  │
  ▼
Content extraction
  │
  ▼
Deterministic price/area parser
  │
  ├── Price
  ├── Area
  ├── Unit
  ├── Year/date
  ├── Location
  └── Source
  │
  ▼
Validation + normalization
  │
  ▼
Canonical INR / sq ft
  │
  ├──────────────────────────────┐
  │                              │
  ▼                              ▼
Current comparable estimator   Historical dataset
  │                              │
  │                              ▼
  │                         Local forecasting
  │                              │
  │                         2026 / 2027 / 2028
  │                              │
  └──────────────┬───────────────┘
                 ▼
             LandWise Result
```

---

# Key Features

### 1. Current Land Price Estimation

- Searches current public property-market evidence.
- Requires explicit **price + area** evidence.
- Converts different units to INR/sq ft.
- Rejects location-mismatched records.
- Removes obvious parser outliers.
- Uses a robust comparable estimator rather than inventing a price.

### 2. Historical Land Price Analysis

- Searches for dated historical land/plot evidence.
- Targets the previous four completed years.
- Preserves the original source and evidence.
- Converts historical observations to INR/sq ft.
- Aggregates multiple observations from the same year using the median.
- Never fabricates missing years.

### 3. Future Price Forecasting

The historical series is passed to a local forecasting model.

With a small four-year dataset, LandWise uses a conservative **log-linear time-series regression** instead of a high-capacity model that would overfit a tiny dataset.

The prediction itself requires **zero additional Tavily calls**.

### 4. Historical Growth Analysis

The API can provide:

- Historical CAGR
- Historical year-over-year growth
- Forecast year-over-year growth
- Historical yearly prices
- Forecast yearly prices
- Forecast model name/status

### 5. Property-Type Support

LandWise supports:

- Land / Plot
- Flat / Apartment
- Villa
- Independent House
- Commercial

### 6. Affordability

Users can evaluate what they can purchase for a given budget.

Land/plot affordability can return equivalent purchasable areas in:

- sq ft
- sq yd
- sq m
- acre
- hectare
- cent
- gunta
- marla
- bigha

Bigha is jurisdiction-dependent and is therefore treated as approximate.

For residential property:

- Flat / Apartment
- Villa
- Independent House

the system evaluates 1–5 BHK scenarios for the same budget.

Residential affordability can retain:

- Ready to Move
- Under Construction
- Resale

as property-status constraints.

Commercial affordability supports practical categories such as:

- Office
- Shop
- Commercial Floor
- Warehouse

---

# Two-Search Data Pipeline

For a normal `/property-price` request without manually supplied source URLs, LandWise makes **at most two Tavily Search API calls**.

### Search 1 — Historical Evidence

One `basic` Tavily search is used to find dated historical land/plot prices for the requested location.

The goal is to obtain evidence for the four completed years available in the requested historical window.

### Search 2 — Current Comparables

One `basic` Tavily search is used to find current land/plot listings containing explicit:

```text
Total Price + Area
```

The values are then normalized to INR/sq ft.

### ML Forecast

The forecast is calculated locally.

```text
Tavily calls for prediction = 0
```

Therefore:

```text
Normal request
    │
    ├── Historical search → 1 Tavily credit
    │
    ├── Current search    → 1 Tavily credit
    │
    └── Local forecast    → 0 Tavily credits
```

The intended maximum is therefore **2 Tavily search calls per normal location request**.

---

# Data Sources

LandWise prioritizes the following requested public property domains while still allowing the wider public web to contribute evidence:

```text
assetlyhq.com
baanknet.com
housing.com
olx.in
99acres.com
instagram.com
1acre.in
```

The search configuration prioritizes these domains rather than treating them as the only possible sources.

This allows LandWise to:

```text
Preferred property sources
          +
Other relevant public web sources
          ↓
Broader evidence pool
```

Returned public URLs can be fetched directly where accessible. Direct HTTP reads do not consume Tavily Search credits.

LandWise does not bypass:

- CAPTCHAs
- authentication
- paywalls
- access restrictions
- robots restrictions

---

# Current Price Estimation

The current market estimate is based on validated comparable observations.

A valid observation should contain enough evidence to establish:

```text
Location
Price
Area
Unit
Property type/context
Source
```

Examples of supported evidence include:

```text
₹950 per sq yard
```

or:

```text
₹15 lakh for 166 sq yd
```

The second example can be normalized as:

```text
₹15,00,000 / converted area
```

and represented as INR/sq ft.

The current estimator uses a robust median-based approach and limits the contribution of repeated observations from a single source page.

### Important distinction

A current listing is **market evidence**, not a guaranteed transaction price.

LandWise therefore does not present an asking price as if it were a confirmed sale price.

---

# Historical Price Forecasting

Historical observations are represented conceptually as:

```json
{
  "year": 2025,
  "price_per_sqft": 1250,
  "source": "99acres.com",
  "source_url": "...",
  "price_type": "asking"
}
```

A historical series might look like:

```text
2022 → ₹500 / sq ft
2023 → ₹600 / sq ft
2024 → ₹720 / sq ft
2025 → ₹850 / sq ft
```

The local forecasting model can then estimate:

```text
2026 → forecast
2027 → forecast
2028 → forecast
```

### Small-data model

Because only four historical years may be available for a locality, LandWise uses:

```text
Log-linear time-series regression
```

rather than a high-capacity model trained on only a handful of observations.

### Missing years

LandWise never does this:

```text
2022 → ₹900
2023 → ₹900  ← fabricated
2024 → ₹900  ← fabricated
2025 → ₹900
```

If a historical year is not supported by evidence, it remains missing.

### Confidence

Two distinct historical years can mathematically support a trend, but such a forecast is marked **low confidence**.

With fewer than two valid historical years:

```text
Forecast = unavailable
```

The system does not manufacture a prediction.

---

# Accuracy and Data-Quality Safeguards

LandWise uses several safeguards to reduce misleading property-price outputs.

### Current data

- Only fresh observations from the current request are used for the displayed current estimate.
- Old database observations are not mixed into today's current estimate.
- Price and area must be explicit.
- Values are normalized to INR/sq ft.
- Location-mismatched observations are rejected.
- Obvious parser outliers are rejected.
- Multiple observations from the same source are controlled to reduce source domination.

### Historical data

- A year-specific price/area relationship is required.
- Missing years are never invented.
- Multiple valid observations for one year are aggregated by median.
- Historical source and URL are preserved where available.
- Current/undated observations are not silently converted into historical records.

### Model integrity

The previous implementation had two major modeling issues:

1. `canonical_price_per_sqft` was used as both a target and an input feature, creating target leakage.
2. Unit conversion in one direction was incorrect.

These issues were identified and the architecture was changed so the price-per-sq-ft target is not used as a model feature.

For a broader historical ML model, features can include:

- Area
- Latitude
- Longitude
- Source quality
- Source type
- Property type
- BHK

The price-per-sq-ft target itself is never used as an input feature.

There is no hard-coded claim such as “98% accuracy”. Validation metrics should come from actual evaluation data.

---

# Property Types

```text
land
flat
villa
independent_house
commercial
```

The application uses property-type-specific rules so that unrelated property classes do not contaminate a land-price estimate.

For example:

```text
Land request
    ✗ apartment listing
    ✗ rental listing
    ✗ villa listing

    ✓ land/plot listing
```

---

# Technology Stack

## Backend

- Python
- FastAPI
- Pydantic
- scikit-learn
- MongoDB
- HTTPX / asynchronous HTTP
- Tavily Search API

## Frontend

- React
- TypeScript
- Vite
- Tailwind CSS

## Data / ML

- Deterministic property-price parser
- Unit normalization
- Statistical aggregation
- scikit-learn
- Log-linear time-series regression
- Historical CAGR
- YoY growth calculations

## Database

MongoDB is used for application data and historical observations where configured.

---

# Project Architecture

A typical project structure:

```text
LandWise/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── services/
│   │   │   ├── source_service.py
│   │   │   ├── forecast_service.py
│   │   │   └── ...
│   │   └── ...
│   │
│   ├── requirements.txt
│   ├── .env.example
│   └── ...
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   └── ...
│   │
│   ├── package.json
│   ├── .env.example
│   └── ...
│
└── README.md
```

---

# API Overview

The main property-price flow is:

```http
POST /property-price
```

The health endpoint:

```http
GET /health
```

Swagger/OpenAPI documentation:

```text
http://127.0.0.1:8000/docs
```

Other application endpoints can include authentication and affordability functionality depending on the deployed version.

## Property Price Response

The property-price response can expose:

```text
historical_data
historical_years
forecast
historical_cagr_percent
historical_yoy_growth_percent
forecast_yoy_growth_percent
forecast_model
```

Current comparable information can include normalized price information and supporting source observations.

---

# Installation

## Prerequisites

Install:

- Python 3.x
- Node.js and npm
- MongoDB / MongoDB Atlas
- Tavily API key

---

# Running the Backend

### Windows

```bat
cd backend

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
```

Edit `.env` and configure:

```env
TAVILY_API_KEY=your_tavily_api_key
MONGODB_URI=your_mongodb_connection_string
```

Then start FastAPI:

```bat
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Alternative:

```bat
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify:

```text
http://127.0.0.1:8000/health
```

Open API documentation:

```text
http://127.0.0.1:8000/docs
```

---

# Running the Frontend

Open another terminal:

```bat
cd frontend

npm install

copy .env.example .env

npm run dev
```

Open the Vite URL shown in the terminal, commonly:

```text
http://localhost:5173
```

The frontend should communicate with FastAPI on:

```text
http://127.0.0.1:8000
```

If a Vite environment variable is used:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Restart Vite after changing `.env`.

---

# Testing

Run backend tests:

```bat
cd backend
python -m pytest
```

Parser tests cover cases including:

```text
₹950 per sq yard
₹15 lakh for 166 sq yd
unrelated numbers/dates
sq ft → acre conversion
```

A direct forecasting test can use a simple historical series:

```text
2022 → ₹500
2023 → ₹600
2024 → ₹720
2025 → ₹850
```

The important verification is that the pipeline produces:

```text
historical_years = [2022, 2023, 2024, 2025]
forecast_model = forecast_ready
forecast = next three years
```

---

# Example Workflow

Suppose the user searches for:

```text
Location: Kodada
Property type: Land
Area: 2400 sq ft
```

LandWise performs:

### Step 1 — Historical search

```text
Tavily Search #1
```

The search looks for dated historical land/plot price evidence.

Potential normalized result:

```text
2022 → ₹500/sq ft
2023 → ₹600/sq ft
2024 → ₹720/sq ft
2025 → ₹850/sq ft
```

### Step 2 — Current comparable search

```text
Tavily Search #2
```

The system looks for current listings containing:

```text
price + area
```

and converts each valid observation to:

```text
₹/sq ft
```

### Step 3 — Validate

Invalid records are removed:

```text
missing price       → reject
missing area        → reject
wrong location      → reject
unrelated property  → reject
obvious outlier     → reject
undated history     → reject
```

### Step 4 — Current estimate

Validated current comparables are aggregated into a robust market estimate.

### Step 5 — Forecast

Historical prices are passed to the local model:

```text
2022
2023
2024
2025
  ↓
local forecast
  ↓
2026
2027
2028
```

### Step 6 — Result

The application can present:

```text
Current market evidence
Historical prices
Historical CAGR
Historical YoY growth
2026 forecast
2027 forecast
2028 forecast
Forecast model
Confidence/data-quality information
Source evidence
```

---

# Important Methodology

## Evidence first

LandWise does not assume that a number appearing on a webpage is a property price.

A number must be associated with relevant property-price context.

For example:

```text
₹950 per sq yard
```

is potentially valid land-price evidence.

But:

```text
Posted on 2024
Area 2400 sq ft
```

does not automatically mean:

```text
₹2400/sq ft
```

The parser must identify an actual price relationship.

---

## Price-unit normalization

Different sources may use:

```text
sq ft
sq yd
sq m
acre
hectare
cent
gunta
marla
bigha
```

LandWise converts supported measurements to a canonical:

```text
INR / sq ft
```

This allows observations from different sources to be compared.

Bigha is jurisdiction-dependent and therefore remains approximate.

---

## Asking price vs transaction price

Public property portals generally expose **asking prices**, auction prices, or advertised values.

They are not necessarily completed transaction prices.

Therefore:

```text
Observed asking price
        ≠
Guaranteed sale price
```

LandWise treats the values as market evidence rather than guaranteed transaction values.

---

# What LandWise Does Not Do

LandWise does not:

- invent missing historical years
- manufacture prices from unrelated numbers
- use price-per-sq-ft as an ML input when it is the target
- claim a fixed accuracy percentage without validation
- treat all web numbers as property prices
- mix old database observations into a fresh current estimate
- bypass CAPTCHAs
- bypass login systems
- bypass paywalls
- scrape restricted/private content
- treat an inaccessible social-media page as automatically valid evidence
- use Gemini/OpenAI/Claude as the price prediction engine

---

# Security and Responsible Data Use

## API keys

Never commit:

```text
.env
```

or real API credentials to Git.

Use:

```text
.env.example
```

for configuration templates.

At minimum:

```env
TAVILY_API_KEY=
MONGODB_URI=
```

## Public data

LandWise is designed around publicly accessible web evidence.

Source availability and extraction behavior can change over time. A source being listed as a preferred domain does not guarantee that its pages will always be publicly accessible or contain suitable historical evidence.

Respect applicable:

- robots.txt
- website terms
- rate limits
- authentication requirements
- copyright restrictions
- platform policies

---

# Limitations

### Historical data availability

Small localities may not have four years of publicly accessible, dated land-price evidence.

In that situation:

```text
Insufficient historical evidence
```

is preferable to a fabricated forecast.

### Web listing bias

Most property portals expose asking prices rather than completed transaction prices.

### Sparse historical data

A forecast based on only two historical years can be calculated, but should be treated as low confidence.

### Bigha conversion

Bigha differs by region, so it is approximate in the current implementation.

### INR focus

The current production normalization is INR-based.

### Source changes

Websites can change:

- page structure
- URLs
- access rules
- content
- availability

Therefore extraction results can vary between searches.

### Forecast uncertainty

A machine-learning/statistical forecast is an estimate based on historical evidence. It is not a guarantee of future land prices.

---

# Future Enhancements

Potential future improvements include:

- Larger validated historical datasets
- More independent source coverage
- Location-level historical databases
- Better geospatial normalization
- District/mandal/locality hierarchy
- More robust time-series models when sufficient data exists
- Confidence intervals for forecasts
- Automated source-quality scoring
- Historical listing archiving
- Price heatmaps
- Location comparison
- Market trend dashboards
- More regional unit-conversion rules
- Transaction-price datasets where legally and publicly available

---

# Product Vision

LandWise is designed to evolve from a land-price estimator into a broader property-market intelligence platform.

```text
                    LandWise
                     │
       ┌─────────────┼─────────────┐
       │             │             │
   Current Price  Historical    Affordability
       │             │             │
       │          Trends/ML      Budget
       │             │             │
       └─────────────┼─────────────┘
                     │
              Property Insights
                     │
            Smarter Land Decisions
```

---

# Repository Description

**Land price analysis, historical market trends, valuation, and future price forecasting platform.**

## Tagline

**Land intelligence for smarter property decisions.**

---

# License

Add the appropriate license for your project and repository before publishing.
=======
# LandWise
A land price analysis and forecasting platform that collects public property-market data, analyzes historical land prices, and predicts future price trends.
