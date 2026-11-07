"""Request-owned evaluation evidence, independent of the UI reasoning toggle."""
import json
import os
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter

from .context import context_fields
from .formatters import sanitize
from .logger import SafeRotatingHandler, current_config, get_logger
import logging

log = get_logger(__name__)
_writer_lock = RLock()
_writer = None
_writer_settings = None


def _write_record(record):
    global _writer, _writer_settings
    config = current_config()
    with _writer_lock:
        settings = (config.directory, config.max_bytes, config.evaluation_backup_count)
        if _writer_settings != settings:
            if _writer:
                _writer.close()
            config.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Do not swallow evaluation write failures: caller reports missing evidence.
            _writer = SafeRotatingHandler(
                config.directory / f"rag_runs.{os.getpid()}.jsonl",
                maxBytes=config.max_bytes, backupCount=config.evaluation_backup_count,
                encoding="utf-8", delay=True,
            )
            _writer_settings = settings
        payload = json.dumps(sanitize(record), ensure_ascii=False, default=str)
        entry = logging.LogRecord("evaluation", logging.INFO, "", 0, payload, (), None)
        # Direct write preserves errors instead of logging.Handler swallowing them.
        if _writer.shouldRollover(entry):
            _writer.doRollover()
        if _writer.stream is None:
            _writer.stream = _writer._open()
        _writer.stream.write(payload + "\n")
        _writer.flush()


class EvaluationRecorder:
    def __init__(self, query, configuration, history=None):
        config = current_config()
        self.enabled = config.evaluation_enabled
        self.started = perf_counter()
        self.lock = RLock()
        self.finished = False
        self.record = dict(
            schema_version=1, timestamp=datetime.now(timezone.utc).isoformat(),
            **context_fields(), configuration=configuration,
            app_version=config.app_version, environment=config.environment,
            input=query if self.enabled else None,
            conversation_history=history if self.enabled else None,
            retrieval_context=[], retrieval_calls=[], tools_called=[],
        )

    def retrieval(self, call):
        if self.enabled:
            with self.lock:
                self.record["retrieval_calls"].append(call)
                self.record["retrieval_context"].extend(call["passages"])

    def tool(self, call):
        if self.enabled:
            with self.lock:
                self.record["tools_called"].append(call)

    def finish(self, output=None, status="success", stage=None, error_type=None):
        with self.lock:
            if self.finished:
                return
            self.finished = True
            if not self.enabled:
                return
            self.record.update(actual_output=output, status=status, stage=stage,
                               error_type=error_type,
                               duration_ms=round((perf_counter() - self.started) * 1000, 2))
            try:
                _write_record(self.record)
            except Exception:
                log.exception("evaluation.capture_failed")


def to_test_case(record, expected_output=None):
    """Convert one successful capture after DeepEval is installed separately."""
    if record.get("status") != "success" or record.get("actual_output") is None:
        raise ValueError("Only completed successful runs can become answer test cases")
    from deepeval.test_case import LLMTestCase
    return LLMTestCase(
        input=record["input"], actual_output=record["actual_output"],
        retrieval_context=record["retrieval_context"], expected_output=expected_output,
    )
