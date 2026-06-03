class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, code: str = "NOT_FOUND", message: str = "Resource not found"):
        super().__init__(code, message, 404)


class UnauthorizedError(AppError):
    def __init__(self, code: str = "UNAUTHORIZED", message: str = "Unauthorized"):
        super().__init__(code, message, 401)


class ForbiddenError(AppError):
    def __init__(self, code: str = "FORBIDDEN", message: str = "Forbidden"):
        super().__init__(code, message, 403)
