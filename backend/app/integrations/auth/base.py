from dataclasses import dataclass


class AuthError(Exception):
    pass


@dataclass
class AuthResult:
    username: str
    display_name: str
    email: str | None = None
    avatar_url: str | None = None
    is_admin: bool = False
