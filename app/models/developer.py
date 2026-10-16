from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, String, Boolean, DateTime
from app.db.database import Base


class DeveloperORM(Base):
    __tablename__ = "developers"

    email      = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    role       = Column(String, default="Developer")
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_notified_at = Column(DateTime, nullable=True)


class DeveloperCreate(BaseModel):
    email: str
    name:  str
    role:  Optional[str] = "Developer"


class DeveloperOut(BaseModel):
    email:    str
    name:     str
    role:     str
    active:   bool
    created_at: Optional[datetime] = None
    last_notified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeveloperUpdate(BaseModel):
    name:   Optional[str] = None
    role:   Optional[str] = None
    active: Optional[bool] = None