from src.exceptions import Conflict, Unauthorized


class InvalidCredentials(Unauthorized):
    code = "invalid_credentials"
    message = "Invalid email or password"


class EmailAlreadyExists(Conflict):
    code = "email_exists"
    message = "Email already exists"


class InvalidRefreshToken(Unauthorized):
    code = "invalid_refresh_token"
    message = "Invalid refresh token"


class AuthenticationRequired(Unauthorized):
    code = "unauthorized"
    message = "Authentication required"


class InvalidAccessToken(Unauthorized):
    code = "invalid_token"
    message = "Invalid or expired token"