"""
Seed the database with demo products and coupons.

Run once on first startup — idempotent (skips if products already exist).
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from backend.models import Coupon, Product

DEMO_PRODUCTS = [
    # Electronics (8)
    {"name": "Wireless Earbuds Pro", "description": "Premium wireless earbuds with active noise cancellation, 30hr battery life, and IPX5 water resistance.", "price_paise": 99900, "category": "electronics", "stock_count": 50},
    {"name": "Smart Watch X1", "description": "Feature-packed smartwatch with heart rate monitor, GPS, sleep tracking, and 7-day battery.", "price_paise": 149900, "category": "electronics", "stock_count": 35},
    {"name": "Portable Bluetooth Speaker", "description": "Compact 20W speaker with deep bass, 12hr playtime, and IPX7 waterproof rating.", "price_paise": 49900, "category": "electronics", "stock_count": 80},
    {"name": "USB-C Fast Charger 65W", "description": "GaN technology charger with 3 ports (2 USB-C + 1 USB-A). Charges laptops and phones.", "price_paise": 29900, "category": "electronics", "stock_count": 120},
    {"name": "Noise-Cancelling Headphones", "description": "Over-ear headphones with hybrid ANC, 40hr battery, and Hi-Res Audio certification.", "price_paise": 199900, "category": "electronics", "stock_count": 25},
    {"name": "Wireless Mouse Ergonomic", "description": "Vertical ergonomic mouse with 4000 DPI sensor, silent clicks, and 3-device Bluetooth switching.", "price_paise": 129900, "category": "electronics", "stock_count": 60},
    {"name": "Webcam 4K HDR", "description": "Ultra HD webcam with auto-focus, built-in ring light, and dual noise-cancelling mics.", "price_paise": 79900, "category": "electronics", "stock_count": 45},
    {"name": "Power Bank 20000mAh", "description": "Dual USB-C/A fast charging power bank with digital display. Charges 3 devices simultaneously.", "price_paise": 159900, "category": "electronics", "stock_count": 90},
    # Accessories (7)
    {"name": "Leather Laptop Sleeve 15\"", "description": "Genuine leather sleeve with magnetic closure. Fits up to 15.6-inch laptops.", "price_paise": 199000, "category": "accessories", "stock_count": 40},
    {"name": "Wireless Charging Pad", "description": "15W fast wireless charger compatible with all Qi-enabled devices. LED indicator.", "price_paise": 129000, "category": "accessories", "stock_count": 100},
    {"name": "Phone Case MagSafe", "description": "Slim clear case with MagSafe compatibility. Shock-absorbing corners.", "price_paise": 79000, "category": "accessories", "stock_count": 200},
    {"name": "Screen Protector 3-Pack", "description": "Tempered glass screen protectors with oleophobic coating. Includes alignment kit.", "price_paise": 34900, "category": "accessories", "stock_count": 300},
    {"name": "Cable Organizer Pouch", "description": "Water-resistant pouch with elastic loops for cables, chargers, and small gadgets.", "price_paise": 89000, "category": "accessories", "stock_count": 150},
    {"name": "AirPods Case Premium", "description": "Silicone shockproof case with carabiner clip. Fits AirPods Pro 2nd gen.", "price_paise": 39900, "category": "accessories", "stock_count": 250},
    {"name": "Laptop Stand Adjustable", "description": "Aluminum alloy laptop stand with 6-angle adjustment. Foldable for travel.", "price_paise": 149900, "category": "accessories", "stock_count": 75},
    # Home & Lifestyle (7)
    {"name": "Smart LED Bulb (Pack of 4)", "description": "WiFi-enabled RGBW bulbs. Voice control via Alexa/Google. 16 million colors.", "price_paise": 249000, "category": "home", "stock_count": 60},
    {"name": "Aroma Diffuser with Oils", "description": "Ultrasonic diffuser with 3 essential oils. 7 LED colors, auto shut-off.", "price_paise": 179000, "category": "home", "stock_count": 45},
    {"name": "Desk Organizer Bamboo", "description": "Sustainable bamboo desk organizer with phone stand, pen holder, and cable slot.", "price_paise": 129000, "category": "home", "stock_count": 70},
    {"name": "LED Desk Lamp Touch", "description": "Touch-control LED desk lamp with 5 brightness levels, 3 color temps, and USB charging port.", "price_paise": 109900, "category": "home", "stock_count": 55},
    {"name": "Mini Projector Portable", "description": "1080p portable projector with WiFi & Bluetooth. 200\" display, built-in speakers.", "price_paise": 299900, "category": "home", "stock_count": 30},
    {"name": "Robot Vacuum Cleaner", "description": "Smart robot vacuum with LiDAR navigation, 2hr runtime, self-emptying dock.", "price_paise": 499900, "category": "home", "stock_count": 20},
    {"name": "Espresso Machine Compact", "description": "Semi-automatic espresso machine with 15-bar pump, milk frother, 1.2L water tank.", "price_paise": 399900, "category": "home", "stock_count": 25},
    # Fitness (6)
    {"name": "Resistance Bands Set", "description": "5-piece set with different resistance levels. Includes door anchor and carry bag.", "price_paise": 69000, "category": "fitness", "stock_count": 90},
    {"name": "Yoga Mat Premium 6mm", "description": "Non-slip TPE yoga mat with alignment lines. Includes carrying strap.", "price_paise": 149000, "category": "fitness", "stock_count": 55},
    {"name": "Shaker Bottle 700ml", "description": "BPA-free shaker with mixing ball and storage compartment. Leak-proof lid.", "price_paise": 44900, "category": "fitness", "stock_count": 180},
    {"name": "Jump Rope Speed", "description": "Adjustable speed rope with ball bearings. Foam grip handles. 3m length.", "price_paise": 39900, "category": "fitness", "stock_count": 110},
    {"name": "Adjustable Dumbbells 20kg", "description": "Space-saving adjustable dumbbells with 5 weight settings per dumbbell (2-20kg).", "price_paise": 349900, "category": "fitness", "stock_count": 30},
    {"name": "Foam Roller High-Density", "description": "EVA foam roller for muscle recovery. 45cm length with textured surface.", "price_paise": 79900, "category": "fitness", "stock_count": 65},
    # Stationery (5)
    {"name": "Mechanical Keyboard Switches", "description": "Pack of 36 Gateron Brown switches. Compatible with hot-swap keyboards.", "price_paise": 89000, "category": "stationery", "stock_count": 65},
    {"name": "Fountain Pen Classic", "description": "Brass-body fountain pen with fine nib. Includes converter and 2 ink cartridges.", "price_paise": 119000, "category": "stationery", "stock_count": 40},
    {"name": "Notebook Dot Grid A5", "description": "160gsm paper, 192 pages, lay-flat binding. Acid-free, fountain-pen friendly.", "price_paise": 59000, "category": "stationery", "stock_count": 200},
    {"name": "Gel Pen Set 24 Colors", "description": "Fine-point gel pens with vibrant colors. Quick-dry ink, won't bleed through paper.", "price_paise": 49900, "category": "stationery", "stock_count": 120},
    {"name": "Sticky Notes Variety Pack", "description": "400 sticky notes in 12 colors and 6 sizes. Strong adhesive, repositionable.", "price_paise": 29900, "category": "stationery", "stock_count": 300},
    # Clothing & Fashion (6)
    {"name": "Polarized Sunglasses UV400", "description": "Lightweight titanium-frame sunglasses with UV400 protection. Includes hard case.", "price_paise": 149900, "category": "clothing", "stock_count": 40},
    {"name": "Canvas Backpack Anti-Theft", "description": "30L waterproof backpack with hidden zippers, USB charging port, and laptop compartment.", "price_paise": 179900, "category": "clothing", "stock_count": 55},
    {"name": "Running Shoes Lightweight", "description": "Breathable mesh running shoes with responsive cushioning and reflective details.", "price_paise": 249900, "category": "clothing", "stock_count": 35},
    {"name": "Cotton T-Shirt Organic", "description": "100% organic cotton crew-neck t-shirt. Pre-shrunk, sustainable dyes. Unisex fit.", "price_paise": 59900, "category": "clothing", "stock_count": 150},
    {"name": "Bamboo Fiber Towel Set", "description": "3-piece antibacterial towel set (bath, hand, face). Ultra-soft, quick-dry.", "price_paise": 99900, "category": "clothing", "stock_count": 80},
    {"name": "Winter Beanie Merino Wool", "description": "100% merino wool beanie with fleece lining. One size fits all.", "price_paise": 49900, "category": "clothing", "stock_count": 100},
    # Kitchen (5)
    {"name": "Stainless Steel Water Bottle", "description": "Double-wall vacuum insulated bottle. Keeps cold 24hr, hot 12hr. 750ml BPA-free.", "price_paise": 69900, "category": "kitchen", "stock_count": 110},
    {"name": "Knife Set 8-Piece", "description": "German stainless steel knives with acacia wood block. Includes chef's, santoku, bread knife.", "price_paise": 299900, "category": "kitchen", "stock_count": 25},
    {"name": "Air Fryer 4.5L Digital", "description": "1400W air fryer with 8 preset programs. Touch screen, dishwasher-safe basket.", "price_paise": 349900, "category": "kitchen", "stock_count": 40},
    {"name": "Silicone Baking Mat Set", "description": "3-piece set (half sheet, quarter sheet, round). Non-stick, oven-safe to 260°C.", "price_paise": 39900, "category": "kitchen", "stock_count": 95},
    {"name": "Electric Kettle 1.7L", "description": "Variable temperature electric kettle with keep-warm function. 1500W rapid boil.", "price_paise": 129900, "category": "kitchen", "stock_count": 60},
    # Personal Care (5)
    {"name": "Electric Toothbrush", "description": "Sonic electric toothbrush with 5 modes, 3-minute timer, and 4 replacement heads.", "price_paise": 149900, "category": "personal_care", "stock_count": 70},
    {"name": "Hair Trimmer Pro", "description": "Cordless hair trimmer with 20 length settings, self-sharpening blades, 90min runtime.", "price_paise": 99900, "category": "personal_care", "stock_count": 55},
    {"name": "Skincare Mini Fridge", "description": "4L portable beauty fridge with warm & cool modes. Compact, whisper-quiet.", "price_paise": 179900, "category": "personal_care", "stock_count": 30},
    {"name": "Beard Grooming Kit", "description": "6-piece kit: trimmer, scissors, comb, balm, oil, and travel pouch.", "price_paise": 129900, "category": "personal_care", "stock_count": 40},
    {"name": "UV Sanitizer Box", "description": "UV-C sanitizer for phones, keys, and masks. 3-minute cycle, USB-C powered.", "price_paise": 69900, "category": "personal_care", "stock_count": 85},
    # Books & Media (5)
    {"name": "Kindle Paperwhite Cover", "description": "Premium PU leather cover for Kindle Paperwhite. Auto sleep/wake, hand strap.", "price_paise": 59900, "category": "books", "stock_count": 100},
    {"name": "Wireless Book Light", "description": "Clip-on LED book light with 3 brightness levels and warm/cool modes. 60hr battery.", "price_paise": 34900, "category": "books", "stock_count": 130},
    {"name": "Journal Leather Bound", "description": "A5 genuine leather journal with 240 lined pages. Ribbon bookmark, elastic closure.", "price_paise": 79900, "category": "books", "stock_count": 60},
    {"name": "Portable Book Stand", "description": "Adjustable aluminum book stand with page holders. Collapses flat for travel.", "price_paise": 89900, "category": "books", "stock_count": 45},
    {"name": "Reading Glasses Blue Light", "description": "Blue-light blocking reading glasses with flexible TR90 frame. 3 magnification strengths.", "price_paise": 49900, "category": "books", "stock_count": 75},
    # Pet Supplies (3)
    {"name": "Interactive Cat Toy", "description": "Automatic rotating laser toy with 3 speed settings. USB rechargeable, auto-off timer.", "price_paise": 69900, "category": "pets", "stock_count": 70},
    {"name": "Dog Harness No-Pull", "description": "Adjustable padded harness with reflective stitching and front/back D-rings. Sizes S-XL.", "price_paise": 59900, "category": "pets", "stock_count": 85},
    {"name": "Pet Water Fountain 2L", "description": "Quiet pump water fountain with triple filtration. Encourages healthy hydration.", "price_paise": 89900, "category": "pets", "stock_count": 50},
    # Garden & Outdoor (3)
    {"name": "Solar Garden Lights 10-Pack", "description": "Stainless steel solar path lights with warm white LEDs. Auto on/off at dusk/dawn.", "price_paise": 79900, "category": "garden", "stock_count": 60},
    {"name": "Herb Garden Kit Indoor", "description": "Self-watering herb garden with 6 seed pods, LED grow light, and soil-free hydroponics.", "price_paise": 199900, "category": "garden", "stock_count": 35},
    {"name": "Grilling Tools Set 12-Piece", "description": "Stainless steel BBQ set with carrying case. Spatula, tongs, fork, skewers, and more.", "price_paise": 129900, "category": "garden", "stock_count": 40},
]

DEMO_COUPONS = [
    {"code": "SAVE10", "discount_percent": 10, "max_uses": 100},
    {"code": "FLAT20", "discount_percent": 20, "max_uses": 50},
    {"code": "WELCOME15", "discount_percent": 15, "max_uses": 200},
    {"code": "MEGA25", "discount_percent": 25, "max_uses": 30},
    {"code": "FIRST50", "discount_percent": 50, "max_uses": 10},
]


def seed_database(db: DBSession) -> None:
    """Seed products and coupons if they don't already exist."""
    existing = db.query(Product).count()
    if existing > 0:
        return  # Already seeded

    for p in DEMO_PRODUCTS:
        db.add(Product(**p))

    for c in DEMO_COUPONS:
        db.add(Coupon(**c))

    db.commit()
    print(f"Seeded {len(DEMO_PRODUCTS)} products and {len(DEMO_COUPONS)} coupons.")
