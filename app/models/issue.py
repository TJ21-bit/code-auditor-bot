from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from app.db.database import Base


class Severity(str, Enum):
    critical = "critical"
    warning  = "warning"
    info     = "info"


class IssueStatus(str, Enum):
    open        = "open"
    in_progress = "in_progress"
    resolved    = "resolved"
    escalated   = "escalated"


class IssueORM(Base):
    __tablename__ = "issues"

    id             = Column(String, primary_key=True)
    title          = Column(String, nullable=False)
    description    = Column(Text)
    fix_suggestion = Column(Text)
    severity       = Column(String, default="warning")
    category       = Column(String, default="General")
    status         = Column(String, default="open")

    # Source
    repo         = Column(String)
    file_path    = Column(String)
    line_number  = Column(String)
    language     = Column(String)
    commit_sha   = Column(String)   # job_id tag
    project_name = Column(String)   # human-readable audit name

    # Assignment
    owner_name  = Column(String)
    owner_email = Column(String)

    # Parking
    jira_ticket_id  = Column(String)
    jira_ticket_url = Column(String)
    sheet_row_index = Column(Integer)
    parked_to_jira  = Column(Boolean, default=False)
    parked_to_sheet = Column(Boolean, default=False)

    # Follow-up
    created_at      = Column(DateTime, default=datetime.utcnow)
    deadline_at     = Column(DateTime)
    last_followup_at = Column(DateTime)
    followup_count  = Column(Integer, default=0)
    resolved_at     = Column(DateTime)
    resolution_note  = Column(Text)


class IssueOut(BaseModel):
    id:             str
    title:          str
    description:    Optional[str] = None
    fix_suggestion: Optional[str] = None
    severity:       str
    category:       str
    status:         str
    repo:           Optional[str] = None
    file_path:      Optional[str] = None
    line_number:    Optional[str] = None
    language:       Optional[str] = None
    owner_name:     Optional[str] = None
    owner_email:    Optional[str] = None
    jira_ticket_id:  Optional[str] = None
    jira_ticket_url: Optional[str] = None
    parked_to_jira:  bool = False
    parked_to_sheet: bool = False
    created_at:      Optional[datetime] = None
    deadline_at:     Optional[datetime] = None
    followup_count:  int = 0
    commit_sha:      Optional[str] = None
    project_name:    Optional[str] = None
    resolution_note: Optional[str] = None

    class Config:
        from_attributes = True


class IssueUpdate(BaseModel):
    status:          Optional[str] = None
    owner_name:      Optional[str] = None
    owner_email:     Optional[str] = None
    resolution_note: Optional[str] = None