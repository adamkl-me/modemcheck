"""
Common Pydantic schemas used across the API.
"""
from typing import Optional, Any, Dict
from pydantic import BaseModel


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = False
    error: str
    details: Optional[Dict[str, Any]] = None


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""
    offset: int = 0
    limit: int = 100

    class Config:
        json_schema_extra = {
            "example": {
                "offset": 0,
                "limit": 100
            }
        }
