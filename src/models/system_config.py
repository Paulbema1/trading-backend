from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timezone
from src.core.database import Base

class SystemConfig(Base):
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True, default=1)
    main_timeframe = Column(String(10), nullable=False, default="1h")
    confirmation_timeframe = Column(String(10), nullable=False, default="4h")
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
