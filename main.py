import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Shoeproduct, Review, Cart, Order, Promocode

app = FastAPI(title="Shoe Store API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers
class ObjectIdStr(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        try:
            return str(ObjectId(str(v)))
        except Exception:
            raise ValueError("Invalid ObjectId")

def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    if doc.get("_id"):
        doc["id"] = str(doc.pop("_id"))
    # Convert ObjectId and non-JSON types
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc


@app.get("/")
def root():
    return {"message": "Shoe Store Backend is running"}


# ---------------- Products ----------------
@app.get("/api/products")
def list_products(
    q: Optional[str] = None,
    brand: Optional[str] = None,
    style: Optional[str] = None,
    size: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = Query(24, ge=1, le=200),
):
    filter_q: Dict[str, Any] = {"in_stock": True}
    if q:
        filter_q["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"brand": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"tags": {"$regex": q, "$options": "i"}},
        ]
    if brand:
        filter_q["brand"] = {"$regex": f"^{brand}$", "$options": "i"}
    if style:
        filter_q["style"] = {"$regex": f"^{style}$", "$options": "i"}
    if size is not None:
        filter_q["sizes"] = size
    price_filter = {}
    if min_price is not None:
        price_filter["$gte"] = float(min_price)
    if max_price is not None:
        price_filter["$lte"] = float(max_price)
    if price_filter:
        filter_q["price"] = price_filter

    cursor = db["shoeproduct"].find(filter_q).limit(limit)
    products = [serialize_doc(p) for p in cursor]
    return {"items": products, "count": len(products)}


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    try:
        oid = ObjectId(product_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    prod = db["shoeproduct"].find_one({"_id": oid})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    # attach reviews summary
    reviews = list(db["review"].find({"product_id": product_id}))
    reviews_serialized = [serialize_doc(r) for r in reviews]
    prod = serialize_doc(prod)
    prod["reviews"] = reviews_serialized
    prod["rating"] = prod.get("rating", {"average": 0, "count": 0})
    return prod


# ---------------- Reviews ----------------
class ReviewCreate(BaseModel):
    product_id: str
    rating: int
    comment: Optional[str] = None
    author_name: Optional[str] = None

@app.post("/api/reviews")
def create_review(payload: ReviewCreate):
    # Validate product exists
    try:
        _ = ObjectId(payload.product_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    prod = db["shoeproduct"].find_one({"_id": ObjectId(payload.product_id)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    review = Review(
        product_id=payload.product_id,
        rating=payload.rating,
        comment=payload.comment,
        author_name=payload.author_name,
    )
    review_id = create_document("review", review)

    # Update product rating summary
    rlist = list(db["review"].find({"product_id": payload.product_id}))
    if rlist:
        avg = sum(int(r.get("rating", 0)) for r in rlist) / len(rlist)
        db["shoeproduct"].update_one(
            {"_id": ObjectId(payload.product_id)},
            {"$set": {"rating": {"average": round(avg, 2), "count": len(rlist)}}},
        )

    return {"id": review_id}


# ---------------- Cart ----------------
class CartItem(BaseModel):
    product_id: str
    name: str
    price: float
    size: int
    qty: int = 1
    image: Optional[str] = None

class CartOwner(BaseModel):
    owner_type: str  # user | session
    owner_id: str

@app.get("/api/cart")
def get_cart(owner_type: str, owner_id: str):
    cart = db["cart"].find_one({"owner_type": owner_type, "owner_id": owner_id})
    if not cart:
        return {"owner_type": owner_type, "owner_id": owner_id, "items": [], "total": 0.0}
    cart = serialize_doc(cart)
    total = sum(item.get("price", 0) * item.get("qty", 1) for item in cart.get("items", []))
    cart["total"] = round(total, 2)
    return cart

@app.post("/api/cart/add")
def add_to_cart(owner: CartOwner, item: CartItem):
    # Ensure product exists
    try:
        _ = ObjectId(item.product_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")

    cart = db["cart"].find_one({"owner_type": owner.owner_type, "owner_id": owner.owner_id})
    if not cart:
        cart_model = Cart(owner_type=owner.owner_type, owner_id=owner.owner_id, items=[item.model_dump()])
        _id = create_document("cart", cart_model)
    else:
        # merge if same product+size exists
        items = cart.get("items", [])
        merged = False
        for it in items:
            if it.get("product_id") == item.product_id and it.get("size") == item.size:
                it["qty"] = int(it.get("qty", 1)) + int(item.qty)
                merged = True
                break
        if not merged:
            items.append(item.model_dump())
        db["cart"].update_one({"_id": cart["_id"]}, {"$set": {"items": items}})
        _id = str(cart["_id"])
    return {"id": _id}

@app.post("/api/cart/remove")
def remove_from_cart(owner: CartOwner, product_id: str, size: int):
    cart = db["cart"].find_one({"owner_type": owner.owner_type, "owner_id": owner.owner_id})
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    items = [it for it in cart.get("items", []) if not (it.get("product_id") == product_id and it.get("size") == size)]
    db["cart"].update_one({"_id": cart["_id"]}, {"$set": {"items": items}})
    return {"ok": True}

@app.post("/api/cart/clear")
def clear_cart(owner: CartOwner):
    db["cart"].delete_one({"owner_type": owner.owner_type, "owner_id": owner.owner_id})
    return {"ok": True}


# ---------------- Checkout / Orders ----------------
class CheckoutPayload(BaseModel):
    owner_type: str
    owner_id: str
    user_id: Optional[str] = None
    shipping_address: Optional[dict] = None
    payment_method: Optional[str] = None  # credit_card | paypal | etc
    promo_code: Optional[str] = None

@app.post("/api/checkout")
def checkout(payload: CheckoutPayload):
    cart = db["cart"].find_one({"owner_type": payload.owner_type, "owner_id": payload.owner_id})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")

    items = cart.get("items", [])
    subtotal = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
    discount = 0.0
    if payload.promo_code:
        code = db["promocode"].find_one({"code": payload.promo_code, "active": True})
        if code:
            if code.get("discount_type") == "amount":
                discount = float(code.get("value", 0))
            else:
                discount = subtotal * float(code.get("value", 0)) / 100.0
    total = max(0.0, subtotal - discount)

    order = Order(
        user_id=payload.user_id,
        items=items,
        total_amount=round(total, 2),
        status="processing",
        shipping_address=payload.shipping_address,
    )
    order_id = create_document("order", order)

    # Simulate payment success
    db["order"].update_one({"_id": ObjectId(order_id)}, {"$set": {"payment": {"method": payload.payment_method, "status": "paid", "transaction_id": f"TXN-{order_id[-6:]}"}, "status": "confirmed"}})

    # Clear cart
    db["cart"].delete_one({"_id": cart["_id"]})

    return {"order_id": order_id, "status": "confirmed"}


@app.get("/api/orders")
def list_orders(user_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    filt: Dict[str, Any] = {}
    if user_id:
        filt["user_id"] = user_id
    cursor = db["order"].find(filt).sort("created_at", -1).limit(limit)
    return [serialize_doc(o) for o in cursor]


# ---------------- Seed sample data ----------------
@app.post("/api/seed")
def seed_products():
    existing = db["shoeproduct"].count_documents({})
    if existing > 0:
        return {"message": "Products already exist", "count": existing}

    samples = [
        {
            "name": "AirFlex Runner",
            "brand": "Aero",
            "description": "Lightweight running shoes with breathable mesh.",
            "price": 89.99,
            "sizes": [7, 8, 9, 10, 11, 12],
            "style": "sneaker",
            "images": [
                "https://images.unsplash.com/photo-1528702748617-c64d49f918af?q=80&w=1200&auto=format&fit=crop",
            ],
            "in_stock": True,
            "stock_by_size": {str(s): 20 for s in [7, 8, 9, 10, 11, 12]},
            "tags": ["running", "men"],
        },
        {
            "name": "CloudStride Pro",
            "brand": "Nimbus",
            "description": "Cushioned everyday sneakers for all-day comfort.",
            "price": 109.0,
            "sizes": [5,6,7,8,9,10],
            "style": "sneaker",
            "images": [
                "https://images.unsplash.com/photo-1542291026-7eec264c27ff?q=80&w=1200&auto=format&fit=crop",
            ],
            "in_stock": True,
            "stock_by_size": {str(s): 15 for s in [5,6,7,8,9,10]},
            "tags": ["women", "lifestyle"],
        },
        {
            "name": "Urban Trek Boot",
            "brand": "Trailforge",
            "description": "Rugged leather boots built for city and trail.",
            "price": 139.5,
            "sizes": [7,8,9,10,11],
            "style": "boot",
            "images": [
                "https://images.unsplash.com/photo-1519741497674-611481863552?q=80&w=1200&auto=format&fit=crop",
            ],
            "in_stock": True,
            "stock_by_size": {str(s): 10 for s in [7,8,9,10,11]},
            "tags": ["men", "leather"],
        },
    ]
    ids = []
    for s in samples:
        model = Shoeproduct(**s)
        ids.append(create_document("shoeproduct", model))

    return {"inserted": len(ids), "ids": ids}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, "name", None) or "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
