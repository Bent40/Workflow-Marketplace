# billing/service.py
# Example service. Note it goes ONLY through InvoiceRepository and works in
# integer cents — converting from the dollars it receives at the boundary.
from billing.repository import InvoiceRepository

_repo = InvoiceRepository()


def charge_customer(customer_id, amount_dollars):
    # Convert at the boundary; everything below the service layer is cents.
    amount_cents = round(amount_dollars * 100)
    return _repo.insert(customer_id, amount_cents)


def get_invoice(invoice_id):
    return _repo.get(invoice_id)
