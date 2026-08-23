"""
Modèle SQLAlchemy pour les utilisateurs.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from src.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)  
    username = Column(String(50), unique=True, index=True, nullable=False)  
    hashed_password = Column(String(255), nullable=False)  
    role = Column(String(10), default="USER", nullable=False)  
    fcm_token = Column(String(500), nullable=True)  
    is_active = Column(Boolean, default=True)  
    notifications_enabled = Column(Boolean, default=True)  
    preferred_assets = Column(  
        String(200),  
        default="EUR/USD,GBP/USD,USD/JPY,XAU/USD",  
    )  
    created_at = Column(DateTime, default=func.now())
