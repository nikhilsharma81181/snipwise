from pydantic import EmailStr, Field

from src.schemas import CamelModel
from src.users.schemas import UserOut


class SignupRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(max_length=128)


class LoginResponse(CamelModel):
    access_token: str
    user: UserOut


class AccessTokenResponse(CamelModel):
    access_token: str
