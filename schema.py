from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base, engine

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(255))
    role = Column(String(50), default="ACCOUNTANT") 
    is_active = Column(Boolean, default=True)

class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    matricule_fiscal = Column(String(50), unique=True)
    address = Column(String(255))
    invoices = relationship("Invoice", back_populates="vendor")

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(100))
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    total_ht = Column(Float)
    total_tva = Column(Float)
    total_ttc = Column(Float)
    document_type = Column(String(50))
    status = Column(String(50), default="PENDING")
    validated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    vendor = relationship("Vendor", back_populates="invoices")
    products = relationship("Product", back_populates="invoice")
    anomalies = relationship("Anomaly", back_populates="invoice")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    code = Column(String(100))
    designation = Column(String(255))
    quantite = Column(Float)
    prix_unitaire = Column(Float, nullable=True)
    invoice = relationship("Invoice", back_populates="products")

class Anomaly(Base):
    __tablename__ = "anomalies"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    anomaly_type = Column(String(50))
    description = Column(String(255))
    is_resolved = Column(Boolean, default=False)
    invoice = relationship("Invoice", back_populates="anomalies")

# Create tables in MySQL
Base.metadata.create_all(bind=engine)