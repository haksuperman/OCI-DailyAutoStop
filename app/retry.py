from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.config import RetrySettings

T = TypeVar("T")


def call_with_retry(
    func: Callable[[], T],
    retry: RetrySettings,
    logger: logging.Logger,
    operation_name: str,
) -> T:
    last_error: Exception | None = None

    for attempt in range(1, retry.max_attempts + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt >= retry.max_attempts:
                break
            delay = min(retry.base_delay_seconds * (2 ** (attempt - 1)), retry.max_delay_seconds)
            jitter = random.uniform(0, delay * 0.2)
            wait_seconds = delay + jitter
            logger.warning(
                "Retrying operation",
                extra={
                    "operation_name": operation_name,
                    "attempt": attempt,
                    "max_attempts": retry.max_attempts,
                    "wait_seconds": round(wait_seconds, 2),
                    "error": str(exc),
                },
            )
            time.sleep(wait_seconds)

    assert last_error is not None
    raise last_error
