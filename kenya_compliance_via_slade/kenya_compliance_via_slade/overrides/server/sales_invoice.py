import frappe
from frappe.model.document import Document

from .shared_overrides import generic_invoices_on_submit_override
from ...utils import calculate_tax, get_settings


def on_submit(doc: Document, method: str = None) -> None:
    company_name = (
        doc.company
        # or frappe.defaults.get_user_default("Company")
        # or frappe.get_value("Company", {}, "name")
    )
    settings_doc = get_settings(company_name=company_name)
    if not settings_doc:
        return
        
    calculate_tax(doc)
    
    if (
        doc.custom_successfully_submitted == 0
        and doc.prevent_etims_submission == 0
        and doc.is_opening == "No"
        and settings_doc.sales_auto_submission_enabled
    ):
        try:
            generic_invoices_on_submit_override(doc, "Sales Invoice")
        except frappe.ValidationError as e:
            frappe.log_error(
                "Sales Invoice Submission Error",
                f"Error in Sales Invoice submission: {str(e)}",
            )


def before_cancel(doc: Document, method: str = None) -> None:
    """Disallow cancelling of submitted invoice to eTIMS."""

    if doc.doctype == "Sales Invoice" and doc.custom_successfully_submitted:
        frappe.throw(
            "This invoice has already been <b>submitted</b> to eTIMS and cannot be <span style='color:red'>Canceled.</span>\n"
            "If you need to make adjustments, please create a Credit Note instead."
        )
    elif doc.doctype == "Purchase Invoice" and doc.custom_submitted_successfully:
        frappe.throw(
            "This invoice has already been <b>submitted</b> to eTIMS and cannot be <span style='color:red'>Canceled.</span>.\nIf you need to make adjustments, please create a Debit Note instead."
        )


@frappe.whitelist()
def send_invoice_details(name: str) -> None:
    doc = frappe.get_doc("Sales Invoice", name)
    if doc.is_opening == "Yes":
        return
    generic_invoices_on_submit_override(doc, "Sales Invoice")
