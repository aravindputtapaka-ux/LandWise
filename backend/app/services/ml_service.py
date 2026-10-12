from __future__ import annotations
import math
from statistics import median
from typing import Any

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline


class PriceModel:
    """Optional historical model.

    Critical rule: the target price-per-sqft is NEVER a model feature.
    Current Tavily observations are comparables, not training labels.
    The model is trained only when a sufficiently large historical dataset
    with location/property features exists.
    """

    def __init__(self):
        self.model = None
        self.metrics: dict[str, Any] = {"status": "not_trained"}
        self.feature_columns = [
            "log_area_sqft", "latitude", "longitude", "source_quality",
            "source_type", "property_type", "bhk_num"
        ]

    @staticmethod
    def _row(r: dict) -> dict:
        area_sqft = float(r.get("area_sqft") or 0)
        if area_sqft <= 0:
            return {}
        bhk = r.get("bhk") or ""
        digits = "".join(ch for ch in str(bhk) if ch.isdigit())
        return {
            "log_area_sqft": math.log1p(area_sqft),
            "latitude": float(r.get("latitude") or 0),
            "longitude": float(r.get("longitude") or 0),
            "source_quality": float(r.get("source_quality") or 0.5),
            "source_type": str(r.get("source_type") or "website"),
            "property_type": str(r.get("property_type") or "land"),
            "bhk_num": float(digits or 0),
        }

    def fit(self, historical_rows: list[dict]) -> None:
        rows=[]
        for r in historical_rows:
            target=float(r.get("canonical_price_per_sqft") or 0)
            x=self._row(r)
            if target > 0 and x:
                rows.append((x,target))
        unique_locations={(round(x["latitude"],3),round(x["longitude"],3)) for x,_ in rows}
        # These thresholds intentionally stay conservative: a model trained on
        # too little or too geographically narrow data overfits and produces
        # confident-looking but inaccurate predictions. It's better to fall
        # back to pure comparable evidence than to ship a bad model.
        if len(rows) < 40 or len(unique_locations) < 4:
            self.metrics={"status":"insufficient_historical_data","rows":len(rows),"unique_locations":len(unique_locations)}
            return

        def vector(x):
            return [x["log_area_sqft"],x["latitude"],x["longitude"],x["source_quality"],x["source_type"],x["property_type"],x["bhk_num"]]
        X=[vector(x) for x,_ in rows]
        y=np.log1p([target for _,target in rows])
        categorical=[4,5]
        numeric=[0,1,2,3,6]
        pre=ColumnTransformer([
            ("cat",OneHotEncoder(handle_unknown="ignore",sparse_output=False),categorical),
            ("num","passthrough",numeric),
        ])
        self.model=Pipeline([
            ("prep",pre),
            ("model",HistGradientBoostingRegressor(max_iter=180,learning_rate=0.05,max_leaf_nodes=15,l2_regularization=2.0,random_state=42)),
        ])
        groups=[f"{x["latitude"]:.3f},{x["longitude"]:.3f}" for x,_ in rows]
        splitter=GroupShuffleSplit(n_splits=1,test_size=0.2,random_state=42)
        tr_idx,te_idx=next(splitter.split(X,y,groups=groups))
        Xtr=[X[i] for i in tr_idx]; Xte=[X[i] for i in te_idx]
        ytr=np.asarray([y[i] for i in tr_idx]); yte=np.asarray([y[i] for i in te_idx])
        self.model.fit(Xtr,ytr)
        pred=np.expm1(self.model.predict(Xte)); actual=np.expm1(yte)
        self.metrics={
            "status":"trained", "rows":len(rows), "unique_locations":len(unique_locations),
            "mape":float(mean_absolute_percentage_error(actual,pred)),
            "mae":float(mean_absolute_error(actual,pred)),
            "r2":float(r2_score(actual,pred)),
        }

    def predict(self, *, area_sqft: float, latitude: float, longitude: float,
                source_quality: float, property_type: str, bhk: str|None) -> float|None:
        if self.model is None or area_sqft <= 0:
            return None
        digits="".join(ch for ch in str(bhk or "") if ch.isdigit())
        row=[
            math.log1p(area_sqft), float(latitude or 0), float(longitude or 0),
            float(source_quality or 0.5), "property_portal", property_type, float(digits or 0)
        ]
        value=float(np.expm1(self.model.predict([row])[0]))
        return value if math.isfinite(value) and value > 0 else None


def robust_ppsf(rows: list[dict]) -> float|None:
    """Weighted median of validated comparable observations.

    This is the primary real-time estimator because it uses actual current
    listing evidence and does not hallucinate a value when evidence is poor.
    """
    pairs=[]
    for r in rows:
        if r.get("source_type") == "guidance_value":
            continue
        v=float(r.get("canonical_price_per_sqft") or 0)
        if not math.isfinite(v) or v <= 0 or v > 1e7:
            continue
        w=max(0.03,min(1.0,float(r.get("source_quality") or 0.5)*float(r.get("location_match") or 1.0)))
        pairs.append((v,w))
    if not pairs:
        return None
    pairs.sort(key=lambda x:x[0])
    total=sum(w for _,w in pairs); acc=0
    for v,w in pairs:
        acc+=w
        if acc >= total/2:
            return float(v)
    return float(median(v for v,_ in pairs))


def forecast_price_series(historical: list[dict], horizon: int = 5, start_year: int | None = None) -> list[dict]:
    """Forecast future INR/sq-ft from the extracted year-wise history.

    This is deliberately a small, transparent time-series model because the
    Google prompt supplies only four annual observations. With four points,
    a simple linear trend is easier to inspect than a high-capacity model.
    It must never be presented as a guaranteed market price.
    """
    clean = []
    for row in historical or []:
        try:
            year = int(row["year"])
            price = float(row["price_per_sqft"])
            if 1900 <= year <= 2100 and math.isfinite(price) and price > 0:
                clean.append((year, price))
        except (KeyError, TypeError, ValueError):
            continue

    clean = sorted(dict(clean).items())
    if len(clean) < 2:
        return []

    x = np.asarray([y for y, _ in clean], dtype=float)
    y = np.asarray([p for _, p in clean], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)

    # Historical annual percentage change is useful as a transparent metric.
    changes = []
    for (_, prev), (_, cur) in zip(clean, clean[1:]):
        if prev > 0:
            changes.append((cur / prev - 1.0) * 100.0)

    last_year = int(max(x))
    first_forecast_year = int(start_year) if start_year is not None else last_year + 1
    out = []
    for step in range(horizon):
        year = first_forecast_year + step
        predicted = max(0.0, float(slope * year + intercept))
        out.append({
            "year": year,
            "predicted_price_per_sqft": round(predicted, 2),
        })

    return out
