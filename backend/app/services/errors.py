class ServiceError(Exception):
    default_detail = "Service error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class AuthenticationError(ServiceError):
    default_detail = "Authentication failed"


class ConflictError(ServiceError):
    default_detail = "Conflict"


class NotFoundError(ServiceError):
    default_detail = "Not found"


class PermissionDeniedError(ServiceError):
    default_detail = "Permission denied"
