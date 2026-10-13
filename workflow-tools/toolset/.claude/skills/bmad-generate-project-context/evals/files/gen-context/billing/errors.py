# billing/errors.py
# UNOBVIOUS RULE: low-level exceptions are NEVER allowed to escape the
# repository layer. Every repository method is decorated with @wrap_db_error,
# which catches the driver's exceptions and re-raises them as a domain
# AppError carrying a stable machine-readable `code`. Callers handle AppError,
# never psycopg.Error.
import functools
import psycopg


class AppError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code  # stable string, e.g. "db_unavailable"


def wrap_db_error(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except psycopg.OperationalError as e:
            raise AppError("db_unavailable", str(e)) from e
        except psycopg.Error as e:
            raise AppError("db_error", str(e)) from e

    return inner
