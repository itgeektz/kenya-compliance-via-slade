import frappe
from frappe import _
from frappe.model.document import Document

from ...apis.apis import send_branch_customer_details
from ...utils import get_active_settings, validate_kra_pin


def after_save(doc: Document, method: str = None) -> None:
    if doc.is_new():
        return
    submit_details(doc)


def after_insert(doc: Document, method: str = None) -> None:
    submit_details(doc)


def validate(doc: Document, method: str = None) -> None:
    if getattr(doc, "require_tax_id", False) and not getattr(doc, "tax_id", None):
        frappe.throw(_("Tax ID is required"))

    tax_id = (getattr(doc, "tax_id", None) or "").strip()
    if not tax_id:
        return

    validate_kra_pin(tax_id)

    tax_id_lower = tax_id.lower()

    existing = frappe.get_all(
        "Customer",
        filters={
            "name": ["!=", doc.name or ""],
            "tax_id": ["like", tax_id_lower],
        },
        fields=["name", "tax_id"],
        limit_page_length=1,
    )

    existing = [c for c in existing if (c.get("tax_id") or "").lower() == tax_id_lower]

    if existing:
        links = ", ".join(
            f'<a href="/app/customer/{c.get("name")}" target="_blank">{c.get("name")}</a>'
            for c in existing
        )
        frappe.throw(
            f"""
            Tax ID <strong>{tax_id}</strong> is already used by Customer(s) {links}.
            """,
            title="Duplicate Tax ID",
        )


def submit_details(doc: Document) -> None:
    if doc.tax_id:
        validate_kra_pin(doc.tax_id)

    active_settings = get_active_settings()
    if not active_settings:
        return
    for setting in active_settings:
        send_branch_customer_details(doc.name, setting.name)
