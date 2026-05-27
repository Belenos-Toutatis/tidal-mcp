"""
Robustness layer for tidalapi: rate limiting, retry, timeout, persistent logging.

This module patches the HTTP layer (tidalapi.request.Requests.request and the
underlying requests.Session) without altering the architecture of server.py.

Configuration via environment variables:
    TIDAL_MCP_LOG_LEVEL    DEBUG / INFO / WARN / ERROR (default: INFO)
"""

import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout


# =============================================================================
# Configuration
# =============================================================================

REQUEST_TIMEOUT_SECONDS = 15.0
RATE_LIMIT_DELAY_SECONDS = 0.05  # 50ms between API calls
MAX_ATTEMPTS = 3                 # total attempts including first
BACKOFF_DELAYS = [1, 2, 4]       # seconds between retries

LOG_FILE_NAME = "tidal-mcp.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_BACKUP_COUNT = 3


# =============================================================================
# Logging
# =============================================================================

_logger: Optional[logging.Logger] = None


def _setup_logger(project_root: Path) -> logging.Logger:
    """Configure rotating-file logger. Idempotent."""
    logger = logging.getLogger("tidal-mcp")

    if getattr(logger, "_tidal_mcp_configured", False):
        return logger

    level_name = os.environ.get("TIDAL_MCP_LOG_LEVEL", "INFO").upper()
    # Normalize WARN -> WARNING for Python's logging module
    if level_name == "WARN":
        level_name = "WARNING"
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    log_file = project_root / LOG_FILE_NAME
    handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger._tidal_mcp_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger() -> logging.Logger:
    """Return the configured logger (or a default if setup hasn't run yet)."""
    return _logger or logging.getLogger("tidal-mcp")


# =============================================================================
# Rate limiting
# =============================================================================

_last_request_time = 0.0
_rate_limit_lock = threading.Lock()


def _rate_limit() -> None:
    """Enforce minimum delay between API calls (thread-safe)."""
    global _last_request_time
    with _rate_limit_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < RATE_LIMIT_DELAY_SECONDS:
            time.sleep(RATE_LIMIT_DELAY_SECONDS - elapsed)
        _last_request_time = time.monotonic()


# =============================================================================
# Token refresh
# =============================================================================

def _refresh_token(tidal_session, save_callback: Optional[Callable[[], None]]) -> bool:
    """Attempt to refresh the OAuth token. Returns True on success."""
    log = get_logger()
    try:
        refresh_token = tidal_session.refresh_token
        if not refresh_token:
            log.error("Token refresh aborted: no refresh_token available")
            return False

        ok = tidal_session.token_refresh(refresh_token)
        if ok:
            log.info("Token refreshed successfully")
            if save_callback is not None:
                try:
                    save_callback()
                except Exception as e:
                    log.warning(f"Failed to persist refreshed session: {e}")
            return True

        log.error("Token refresh returned False")
        return False
    except Exception as e:
        log.error(f"Token refresh raised exception: {e}", exc_info=True)
        return False


# =============================================================================
# Patches
# =============================================================================

def _extract_status(exc: BaseException) -> Optional[int]:
    """Pull HTTP status code from any exception that carries a response."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        return getattr(resp, "status_code", None)
    return None


def _patch_underlying_session(request_session: requests.Session) -> None:
    """Add a default timeout to the underlying requests.Session.request method."""
    if getattr(request_session, "_tidal_mcp_patched", False):
        return

    original = request_session.request

    def request_with_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)
        return original(method, url, **kwargs)

    request_session.request = request_with_timeout  # type: ignore[method-assign]
    request_session._tidal_mcp_patched = True  # type: ignore[attr-defined]


def _patch_tidal_request(
    tidal_session,
    save_session_callback: Optional[Callable[[], None]],
) -> None:
    """Wrap tidalapi.Requests.request with retry, rate limit, and logging."""
    requests_obj = tidal_session.request
    if getattr(requests_obj, "_tidal_mcp_patched", False):
        return

    original_request = requests_obj.request

    def patched_request(*args, **kwargs):
        log = get_logger()
        method = args[0] if args else kwargs.get("method", "?")
        path = args[1] if len(args) > 1 else kwargs.get("path", "?")
        label = f"{method} {path}"

        last_exc: Optional[BaseException] = None

        for attempt in range(MAX_ATTEMPTS):
            _rate_limit()
            start = time.monotonic()
            try:
                response = original_request(*args, **kwargs)
                duration_ms = int((time.monotonic() - start) * 1000)
                status = getattr(response, "status_code", None)
                log.debug(f"{label} - {duration_ms}ms - HTTP {status}")
                return response

            except Exception as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                last_exc = exc
                status = _extract_status(exc)

                # 401: try a single token refresh on the first attempt
                if status == 401 and attempt == 0:
                    log.warning(
                        f"{label} - HTTP 401 after {duration_ms}ms, refreshing token"
                    )
                    if _refresh_token(tidal_session, save_session_callback):
                        continue  # retry without counting this as a backoff attempt
                    log.error(f"{label} - token refresh failed; aborting")
                    raise

                # Retryable conditions
                is_network_error = isinstance(
                    exc, (RequestsConnectionError, RequestsTimeout)
                )
                is_retryable_status = status in (429, 503)

                if (is_network_error or is_retryable_status) and attempt < MAX_ATTEMPTS - 1:
                    delay = BACKOFF_DELAYS[attempt]
                    reason = f"HTTP {status}" if status else type(exc).__name__
                    log.warning(
                        f"{label} - {reason} after {duration_ms}ms, "
                        f"retry {attempt + 1}/{MAX_ATTEMPTS} in {delay}s"
                    )
                    time.sleep(delay)
                    continue

                # Out of retries or non-retryable error: log and re-raise
                attempts_done = attempt + 1
                if is_network_error or is_retryable_status:
                    log.error(
                        f"{label} - failed after {attempts_done} attempt(s) "
                        f"({duration_ms}ms): {exc}",
                        exc_info=True,
                    )
                else:
                    reason = f"HTTP {status}" if status else type(exc).__name__
                    log.error(
                        f"{label} - {reason} after {duration_ms}ms "
                        f"(not retryable): {exc}"
                    )
                raise

        # Safety net (should not be reached)
        if last_exc:
            raise last_exc

    requests_obj.request = patched_request  # type: ignore[method-assign]
    requests_obj._tidal_mcp_patched = True  # type: ignore[attr-defined]


# =============================================================================
# Public API
# =============================================================================

def apply_robustness(
    tidal_session,
    project_root: Path,
    save_session_callback: Optional[Callable[[], None]] = None,
) -> None:
    """
    Initialize logging and apply HTTP-layer patches to a tidalapi.Session.

    Idempotent — safe to call multiple times.
    """
    global _logger
    _logger = _setup_logger(project_root)

    level = logging.getLevelName(_logger.level)
    _logger.info(
        f"Robustness layer initializing (level={level}, "
        f"timeout={REQUEST_TIMEOUT_SECONDS}s, "
        f"rate_limit={int(RATE_LIMIT_DELAY_SECONDS * 1000)}ms, "
        f"max_attempts={MAX_ATTEMPTS})"
    )

    _patch_underlying_session(tidal_session.request_session)
    _patch_tidal_request(tidal_session, save_session_callback)

    _logger.info("Robustness layer applied")
