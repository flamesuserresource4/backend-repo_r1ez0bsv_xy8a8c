"""
Database Schemas for Shoe E-commerce

Define MongoDB collection schemas using Pydantic models.
Each model class name maps to a collection name in lowercase.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

# Users
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Unique email address")
    password_hash: str = Field(..., description="Hashed password (server-side hashed)")
    addresses: List[dict] = Field(default_factory=list, description="Saved shipping addresses")
    payment_methods: List[dict] = Field(default_factory=list, description="Saved payment methods tokens (if any)")
    is_active: bool = Field(True)
    role: str = Field("customer", description="customer | admin")

# Products (Shoes)
class Shoeproduct(BaseModel):
    name: str
    brand: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    sizes: List[int] = Field(default_factory=list, description="Available sizes")
    style: Optional[str] = Field(None, description="sneaker, boot, sandal, etc.")
    images: List[str] = Field(default_factory=list)
    in_stock: bool = True
    stock_by_size: dict = Field(default_factory=dict)
    rating: dict = Field(default_factory=lambda: {"average": 0.0, "count": 0})
    tags: List[str] = Field(default_factory=list)

# Reviews
class Review(BaseModel):
    product_id: str
    user_id: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    author_name: Optional[str] = None

# Cart (per user or session)
class Cart(BaseModel):
    owner_type: str = Field(..., description="user|session")
    owner_id: str = Field(..., description="user_id or session_id")
    items: List[dict] = Field(default_factory=list)

# Orders
class Order(BaseModel):
    user_id: Optional[str] = None
    items: List[dict] = Field(default_factory=list)
    total_amount: float = 0.0
    status: str = Field("pending")
    shipping_address: Optional[dict] = None
    payment: dict = Field(default_factory=lambda: {"method": None, "status": "pending", "transaction_id": None})
    tracking: dict = Field(default_factory=lambda: {"carrier": None, "tracking_number": None, "status": "processing"})

# Promo Codes
class Promocode(BaseModel):
    code: str
    discount_type: str = Field("percentage", description="percentage|amount")
    value: float = Field(..., ge=0)
    active: bool = True
    description: Optional[str] = None
