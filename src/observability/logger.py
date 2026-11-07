"""Short structured calls over standard logging with safe rotating handlers."""
import logging
import os
import sys
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from threading import RLock
from time import perf_counter

from .config import LoggingConfig
from .context import context_fields
from .formatters import JsonFormatter

_lock = RLock()
_config = None
_reserved = {"schema_version", "timestamp", "level", "event", "module", "service",
             "environment", "app_version", "user_id", "chat_id", "request_id", "turn_id",
             "ingestion_id", "document_id", "attempt", "retry_of_request_id"}


class SafeRotatingHandler(RotatingFileHandler):
    """Restrict new files and emit at most one fallback notice on write failure."""
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding)

    def handleError(self, record):
        if not getattr(self, "_failure_reported", False):
            self._failure_reported = True
            sys.stderr.write("AgenticRAG: a log file write failed; check LOG_DIR and disk space.\n")


def configure_logging(config=None):
    global _config
    config = config or LoggingConfig.from_env()
    with _lock:
        if _config == config:
            return config
        parent = logging.getLogger("agentic_rag")
        formatter = JsonFormatter(config)
        handlers = []
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(config.level)
        handlers.append(console)
        try:
            config.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            # PID suffixes prevent independent processes rotating the same file.
            for name, level in (("app", config.level), ("error", logging.ERROR)):
                handler = SafeRotatingHandler(
                    config.directory / f"{name}.{os.getpid()}.jsonl",
                    maxBytes=config.max_bytes, backupCount=config.backup_count,
                    encoding="utf-8", delay=True,
                )
                handler.setFormatter(formatter)
                handler.setLevel(level)
                handlers.append(handler)
        except OSError:
            sys.stderr.write("AgenticRAG: file logging unavailable; using console logging.\n")
        for handler in parent.handlers[:]:
            parent.removeHandler(handler)
            handler.close()
        parent.setLevel(config.level)
        parent.propagate = False
        for handler in handlers:
            parent.addHandler(handler)
        _config = config
        return config


def current_config():
    return _config or configure_logging()


class AppLogger:
    def __init__(self, name):
        self.logger = logging.getLogger("agentic_rag." + name)

    def _write(self, level, event, message=None, exc_info=False, **fields):
        current_config()
        fields = {key: value for key, value in fields.items() if key not in _reserved}
        fields.update(context_fields())
        self.logger.log(level, event, exc_info=exc_info,
                        extra={"fields": fields, "event_message": message or event})

    def debug(self, event, **fields):
        self._write(logging.DEBUG, event, **fields)

    def info(self, event, **fields):
        self._write(logging.INFO, event, **fields)

    def warning(self, event, **fields):
        self._write(logging.WARNING, event, **fields)

    def error(self, event, **fields):
        self._write(logging.ERROR, event, **fields)

    def exception(self, event, **fields):
        self._write(logging.ERROR, event, exc_info=True, **fields)

    def critical(self, event, **fields):
        self._write(logging.CRITICAL, event, **fields)

    @contextmanager
    def operation(self, event, **fields):
        """Record successful stage timing; the outer boundary handles failures."""
        started = perf_counter()
        self.info(event + ".started", **fields)
        yield
        self.info(event + ".completed", duration_ms=round((perf_counter() - started) * 1000, 2), **fields)


def get_logger(name):
    return AppLogger(name)
