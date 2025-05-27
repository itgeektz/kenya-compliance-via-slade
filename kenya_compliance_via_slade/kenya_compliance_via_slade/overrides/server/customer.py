import frappe
from frappe import _
from frappe.model.document import Document

from ...apis.apis import send_branch_customer_details
from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME


def on_update(doc: Document, method: str = None) -> None:

    if not frappe.db.exists(SETTINGS_DOCTYPE_NAME, {"is_active": 1}):
        return

    if not doc.custom_details_submitted_successfully:
        send_branch_customer_details(doc.name)
        

def validate(doc: Document, method: str = None) -> None:
    if getattr(doc, "require_tax_id", False):
        if not getattr(doc, "tax_id", None):
            frappe.throw(_("Tax ID is required"))
