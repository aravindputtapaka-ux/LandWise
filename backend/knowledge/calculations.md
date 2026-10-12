# How LandWise calculates property prices

LandWise estimates property prices using comparable property evidence.
An estimate is not a guaranteed selling price or a formal valuation.

## Step 1: Collect comparable evidence

The application searches for property evidence relevant to the requested
location and property type. It extracts usable price and area information.
It can also use previously stored comparable observations.

## Step 2: Normalize area and price

Properties may use different area units, such as square feet, square yards
or acres. LandWise converts supported areas into square feet so that
comparable prices can be evaluated on a common basis.

Price per square foot = Property price / Property area in square feet.

Example:
A property listed at ₹30,00,000 with an area of 1,500 sq ft has a rate
of ₹2,000 per sq ft.

This example is illustrative and is not a current market quote.

## Step 3: Calculate a representative comparable rate

LandWise removes duplicate observations and applies filtering to reduce
the influence of extreme values when enough observations are available.

It then uses a robust comparable-price calculation to obtain a
representative rate. This is not simply the price of one listing.

The estimate depends on the quality and relevance of the source evidence.

## Step 4: Calculate the requested property's total estimate

Estimated total price =
Final estimated price per square foot × Requested area in square feet.

Example:
For 1,200 sq ft at an estimated ₹2,000 per sq ft:

Estimated total price = 1,200 × ₹2,000 = ₹24,00,000.

This is an illustrative calculation, not a quote for a particular location.

## Land and non-land estimates

For land, the current estimate uses the comparable rate.
Historical forecasts are calculated separately.

For non-land properties, the application may apply a limited historical
machine-learning correction when the model passes its validation checks.
Otherwise, the comparable evidence determines the estimate.

# How land affordability is calculated

Land affordability answers:
"Approximately how much land could this budget buy?"

Affordable area in square feet =
Budget / Estimated price per square foot.

Example:
Budget = ₹30,00,000.
Estimated rate = ₹2,000 per sq ft.

Affordable area = ₹30,00,000 / ₹2,000 = 1,500 sq ft.

The application may display this area in other supported units.

The result is approximate. Taxes, registration, brokerage, development
costs and legal due diligence may be excluded.

# How residential affordability is calculated

For flats, villas and independent houses, LandWise examines available
listing evidence for different BHK categories.

It compares the user's budget with a typical listing price for each
category using the median of the available relevant prices.

If the budget meets or exceeds that typical price, the category may be
shown as affordable.

This does not confirm that a particular property is available for purchase.

When usable price-per-square-foot evidence exists, LandWise can also
estimate the area supported by the budget.

If listings provide a total price but no usable area, the system can
compare total prices without inventing a price per square foot.

# How commercial affordability is calculated

Commercial affordability estimates the area supported by a budget
using comparable commercial price-per-square-foot evidence.

Estimated area = Budget / Estimated price per square foot.

The application groups evidence into categories such as office, shop,
commercial floor and warehouse where matching evidence is available.

The current implementation may use broader commercial observations
when category-specific observations are unavailable. Therefore, a
category result is not always based exclusively on that category.

# Historical prices and forecasts

Historical prices describe past observations.
Forecast prices are predictions generated from historical data.

A forecast is not a guaranteed future price.

The land-price forecast is separate from the current comparable-price
estimate and does not replace it.

# Confidence and limitations

Confidence describes the amount of supporting evidence under the
application's rules. It is not a probability that an estimate is correct.

A saved estimate represents the result recorded when that search ran.
It must not be described as today's price unless a fresh search was run.

Actual transaction prices can differ because of the precise location,
road access, approvals, property condition, negotiations and other factors.

The assistant should identify missing information rather than invent it.