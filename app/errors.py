"""可公开的领域异常，不把 SQL 或内部堆栈返回到浏览器。"""


class DomainError(Exception):
    def __init__(self, message, status=400, code="INVALID_INPUT"):
        self.message = message
        self.status = status
        self.code = code
        super().__init__(message)


def conflict(message):
    return DomainError(message, 409, "CONFLICT")
