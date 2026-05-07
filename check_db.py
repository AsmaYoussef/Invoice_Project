from database import SessionLocal
from schema import Invoice, Vendor, Product

db = SessionLocal()

print("\n=== SAVED INVOICES ===")
invoices = db.query(Invoice).all()
for inv in invoices:
    print(f"ID: {inv.id} | N°: {inv.invoice_number} | Total TTC: {inv.total_ttc} | Status: {inv.status}")

print("\n=== SAVED VENDORS ===")
vendors = db.query(Vendor).all()
for v in vendors:
    print(f"MF: {v.matricule_fiscal} | Name: {v.name}")

print("\n=== SAVED PRODUCTS ===")
products = db.query(Product).all()
for p in products:
    print(f"Designation: {p.designation} | Qty: {p.quantite}")