import frappe
from frappe import _
from frappe.utils import now


def get_context(context):
    frappe.local.response["headers"] = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }

    context.cache_buster = now()

    args = frappe.local.form_dict
    invoice_id = args.get("id")
    verification_key = args.get("key")

    context.invoice_id = invoice_id
    context.verification_key = verification_key

    if not invoice_id or not verification_key:
        context.error = _("Invalid verification link.")
        return

    try:
        response = frappe.get_attr(
            "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.check_invoice_submission_status"
        )(id=invoice_id, key=verification_key)

        if not response:
            context.error = _("Unable to verify invoice.")
            return

        if isinstance(response, dict) and response.get("error"):
            context.error = response.get("error")
            return

        if isinstance(response, dict) and response.get("etims_qr_code_url"):
            context.redirect_url = response.get("etims_qr_code_url")
            return

        context.invoice = response

    except Exception:
        context.error = _("Unable to verify invoice.")
