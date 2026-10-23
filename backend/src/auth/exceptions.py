from src.exceptions import ErrorSpec

INVALID_CREDENTIALS = ErrorSpec("invalid_credentials", 401, "Invalid email or password")
EMAIL_EXISTS = ErrorSpec("email_exists", 409, "Email already exists")
INVALID_REFRESH_TOKEN = ErrorSpec("invalid_refresh_token", 401, "Invalid refresh token")
AUTHENTICATION_REQUIRED = ErrorSpec("unauthorized", 401, "Authentication required")
INVALID_ACCESS_TOKEN = ErrorSpec("invalid_token", 401, "Invalid or expired token")
SIGNUP_CLOSED = ErrorSpec("signup_closed", 403, "Sign-ups are closed for the beta")
