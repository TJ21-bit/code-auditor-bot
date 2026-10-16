from typing import Optional, List, Dict
from pydantic import BaseModel


class AuditRequest(BaseModel):
    repo:            str
    branch:          str = "main"
    paths:           Optional[List[str]] = None
    project_name:    Optional[str] = None       # human-readable name shown on dashboard
    park_to_jira:    bool = False
    park_to_sheet:   bool = False
    notify_owners:   bool = True
    assigned_to:     Optional[str] = None
    owner_overrides: Optional[Dict[str, str]] = None

    class Config:
        extra = "ignore"