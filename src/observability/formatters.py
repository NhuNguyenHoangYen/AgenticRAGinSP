"""JSON event serialization and best-effort secret redaction."""
import json
import logging
import os
import re
from datetime import datetime, timezone


def sanitize(value):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if re.search(r"api.?key|secret|password|authorization|access_token|mongodb_uri|connection_string", str(k), re.I)
                else sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if re.search(r"API_KEY|SECRET|PASSWORD|TOKEN", key) and len(secret) >= 6:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(mongodb(?:\+srv)?://)[^/\s]*@", r"\1[REDACTED]@", value, flags=re.I)
        value = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", value, flags=re.I)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
        return value
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def format(self, record):
        data = dict(getattr(record, "fields", {}))
        data.update(
            schema_version=1,
            timestamp=datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            level=record.levelname, event=record.getMessage(),
            message=getattr(record, "event_message", record.getMessage()),
            module=record.name, service="agentic-rag",
            environment=self.config.environment, app_version=self.config.app_version,
        )
        if record.exc_info:
            data.update(error_type=record.exc_info[0].__name__,
                        error_message=str(record.exc_info[1]),
                        stack_trace=self.formatException(record.exc_info))
        return json.dumps(sanitize(data), ensure_ascii=False, default=str)
