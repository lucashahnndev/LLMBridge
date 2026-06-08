from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    password: str = Field(..., min_length=1)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class AdminProfileResponse(BaseModel):
    authenticated: bool = True


class AdminLogoutResponse(BaseModel):
    revoked: bool = True
