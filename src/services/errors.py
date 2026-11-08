"""Domain failures; HTTP translation belongs to the API layer."""


class ServiceError(Exception):
    code = "service_error"


class ChatNotFound(ServiceError):
    code = "chat_not_found"

    def __init__(self):
        super().__init__("Chat not found")


class AttachmentInconsistent(ServiceError):
    code = "attachment_inconsistent"

    def __init__(self):
        super().__init__("An attached document is unavailable; repair the attachment record")


class WorkflowError(ServiceError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details
