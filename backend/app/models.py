from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

PROPERTY_TYPES = ["land", "flat", "villa", "independent_house", "commercial"]
LAND_UNITS = ["sq ft", "sq yd", "sq m", "acre", "hectare", "cent", "gunta", "marla", "bigha"]


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class VerifySignupRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)


class ResendOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field("signup", pattern="^(signup|reset)$")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)


class OtpResponse(BaseModel):
    message: str
    email: EmailStr
    expires_in_seconds: int = 600


class AuthResponse(BaseModel):
    token: str
    user: "UserPublic"


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    created_at: Optional[str] = None


class SearchHistoryItem(BaseModel):
    id: str
    type: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    created_at: str


class PropertyPriceRequest(BaseModel):
    property_type: str = Field("land")
    location: str = Field(..., min_length=2)
    bhk: Optional[str] = None
    area: Optional[float] = Field(None, gt=0)
    area_unit: Optional[str] = "sq ft"
    property_status: Optional[str] = None
    currency: str = Field("INR", min_length=3, max_length=3)
    source_urls: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("property_type")
    @classmethod
    def validate_property_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in PROPERTY_TYPES:
            raise ValueError(f"property_type must be one of {PROPERTY_TYPES}")
        return v

class AffordabilityRequest(BaseModel):
    location: str = Field(..., min_length=2)
    budget: float = Field(..., gt=0)
    currency: str = Field("INR", min_length=3, max_length=3)
    property_type: str = "land"
    bhk: Optional[str] = None
    property_status: Optional[str] = None

class SourceIngestRequest(BaseModel):
    location: str = Field(..., min_length=2)
    urls: List[str] = Field(..., min_length=1, max_length=30)
    property_type: str = "land"
    bhk: Optional[str] = None

class PropertyObservation(BaseModel):
    source_url: str
    source_domain: str
    source_type: str
    source_quality: float = 0.5
    location: Optional[str] = None
    price: float
    currency: str = "INR"
    area: Optional[float] = None
    area_unit: Optional[str] = None
    price_per_unit: Optional[float] = None
    canonical_price_per_sqft: Optional[float] = None
    property_type: str = "land"
    bhk: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    evidence: Optional[str] = None

class PriceInfo(BaseModel):
    location: str
    property_type: str = "land"
    bhk: Optional[str] = None
    property_status: Optional[str] = None
    price_per_unit: float
    unit: str
    currency: str
    estimated_total_price: Optional[float] = None
    source_summary: str
    sources: List[str] = Field(default_factory=list)
    source_count: int = 0
    observation_count: int = 0
    confidence: Optional[str] = None
    average_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    average_price_per_sqft: Optional[float] = None
    typical_area_min: Optional[float] = None
    typical_area_max: Optional[float] = None
    sample_size: Optional[int] = None
    market_trend: Optional[str] = None
    model_used: Optional[str] = None
    ml_metrics: Dict[str, Any] = Field(default_factory=dict)
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    historical_prices: List[Dict[str, Any]] = Field(default_factory=list)
    forecast_prices: List[Dict[str, Any]] = Field(default_factory=list)
    historical_query: Optional[str] = None
    historical_sources: List[str] = Field(default_factory=list)

class AffordabilityOption(BaseModel):
    category: str
    label: str
    available: bool
    estimated_price: Optional[float] = None
    estimated_price_per_sqft: Optional[float] = None
    estimated_area_sqft: Optional[float] = None
    estimated_area_display: Optional[Dict[str, float]] = None
    property_status: Optional[str] = None
    source_count: int = 0
    observation_count: int = 0
    confidence: Optional[str] = None
    note: Optional[str] = None

class AffordabilityResponse(BaseModel):
    location: str
    property_type: str
    budget: float
    currency: str
    price_per_unit: Optional[float] = None
    unit: Optional[str] = None
    affordable_area: Optional[float] = None
    affordable_area_unit: Optional[str] = None
    equivalent: Dict[str, float] = Field(default_factory=dict)
    options: List[AffordabilityOption] = Field(default_factory=list)
    property_status: Optional[str] = None
    notes: str
    sources: List[str] = Field(default_factory=list)
