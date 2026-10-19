"""Доменные ошибки. Превращаются в HTTP-ответы в app/main.py."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class Forbidden(DomainError):
    status_code = 403


class Unauthorized(DomainError):
    status_code = 401


class Unprocessable(DomainError):
    status_code = 422


class TooManyRequests(DomainError):
    status_code = 429
