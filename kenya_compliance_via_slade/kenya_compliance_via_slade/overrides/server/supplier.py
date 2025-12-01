import frappe
from frappe import _
from frappe.model.document import Document

from ...apis.apis import send_branch_customer_details
from ...utils import get_active_settings


def before_save(doc: Document, method: str = None) -> None:
    if not doc.has_value_changed("tax_id") or doc.is_new():
        return
    submit_details(doc)


def after_insert(doc: Document, method: str = None) -> None:
    submit_details(doc)


def validate(doc: Document, method: str = None) -> None:
    if getattr(doc, "require_tax_id", False):
        if not getattr(doc, "tax_id", None):
            frappe.throw(_("Tax ID is required"))


def submit_details(doc: Document) -> None:
    active_settings = get_active_settings()
    if not active_settings:
        return
    for setting in active_settings:
        send_branch_customer_details(doc.name, setting.name, False)
