"""
Pydantic schemas for API key management.
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class APIKeyCreate(BaseModel):
    """Schema for creating a new API key."""
    name: str = Field(..., min_length=1, max_length=255)

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Production Client - Office Router"
            }
        }


class APIKeyCreateResponse(BaseModel):
    """Schema for API key creation response."""
    success: bool
    message: Optional[str] = None
    api_key: Optional[str] = None  # Only returned once on creation
    name: Optional[str] = None
    error: Optional[str] = None


class APIKeyResponse(BaseModel):
    """Schema for API key response (without the actual key)."""
    api_key_preview: str  # First/last 4 chars only
    name: str
    created_at: datetime
    last_used: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class APIKeyListResponse(BaseModel):
    """Schema for API key list response."""
    success: bool
    api_keys: List[APIKeyResponse]


class APIKeyToggleRequest(BaseModel):
    """Schema for toggling API key active status."""
    api_key_preview: str = Field(..., description="Preview of API key (first+last 4 chars)")
    is_active: bool


class APIKeyDeleteRequest(BaseModel):
    """Schema for deleting an API key."""
    api_key_preview: str = Field(..., description="Preview of API key (first+last 4 chars)")
