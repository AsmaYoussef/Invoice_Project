from schema import Base
from database import engine

print("Connecting to MySQL in Docker...")
try:
    # This command talks to Docker and creates the tables
    Base.metadata.create_all(bind=engine)
    print("✅ Success! Tables (Invoices, Products, Anomalies, etc.) created.")
except Exception as e:
    print(f"❌ Error: {e}")