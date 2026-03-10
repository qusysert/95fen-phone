from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ProductPrice(BaseModel):
    current: Optional[float] = None
    original: Optional[float] = None
    discount_percent: Optional[float] = None
    currency: str = "CNY"


class ProductSpecs(BaseModel):
    size: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = None
    authenticity: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class Product(BaseModel):
    product_id: Optional[str] = None
    source_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    price: ProductPrice = Field(default_factory=ProductPrice)
    specs: ProductSpecs = Field(default_factory=ProductSpecs)
    image_urls: list[str] = Field(default_factory=list)
    local_images: list[str] = Field(default_factory=list)
    seller_name: Optional[str] = None
    seller_id: Optional[str] = None
    scraped_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    scrape_method: str = "phone_scraper"
    raw_data: Optional[dict] = None
