from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Connect to the MySQL database running inside Docker
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://pfe_user:pfepassword@localhost:3306/invoice_intelligence"

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base must be defined here so all models can import it
from sqlalchemy.orm import declarative_base
Base = declarative_base()