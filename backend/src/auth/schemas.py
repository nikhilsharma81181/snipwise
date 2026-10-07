from pydantic import EmailStr, Field

from src.schemas import CamelModel
from src.users.schemas import UserOut


class SignupRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(max_length=128)


class RefreshRequest(CamelModel):
    refresh_token: str


class TokenPair(CamelModel):
    access_token: str
    refresh_token: str


class LoginResponse(TokenPair):
    user: UserOut
