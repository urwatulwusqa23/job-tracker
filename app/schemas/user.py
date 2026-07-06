from pydantic import BaseModel, Field


class UserUpdate(BaseModel):
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
