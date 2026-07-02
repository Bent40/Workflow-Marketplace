# billing/repository.py
# UNOBVIOUS RULE: ALL database access in this codebase goes through a
# Repository class. Application/service code must NEVER import `psycopg`,
# open a connection, or write raw SQL outside this module. New persistence
# belongs in a Repository method, not inline in a service.
import psycopg
from billing.errors import wrap_db_error

_POOL = None


def _conn():
    # Connections are leased from the module-level pool, never created ad hoc.
    if _POOL is None:
        raise RuntimeError("call init_pool() during app startup before any query")
    return _POOL.getconn()


class InvoiceRepository:
    @wrap_db_error
    def get(self, invoice_id):
        with _conn().cursor() as cur:
            cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
            return cur.fetchone()

    @wrap_db_error
    def insert(self, customer_id, amount_cents):
        # Money is ALWAYS an integer number of cents. Floats/Decimals for
        # currency are forbidden anywhere in the codebase.
        assert isinstance(amount_cents, int), "amount must be integer cents"
        with _conn().cursor() as cur:
            cur.execute(
                "INSERT INTO invoices (customer_id, amount_cents) "
                "VALUES (%s, %s) RETURNING id",
                (customer_id, amount_cents),
            )
            return cur.fetchone()[0]
