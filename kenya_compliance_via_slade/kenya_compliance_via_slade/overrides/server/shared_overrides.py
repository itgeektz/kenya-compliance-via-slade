from typing import Literal

import frappe
from frappe.model.document import Document

from ...apis.api_builder import EndpointsBuilder
from ...apis.process_request import process_request
from ...apis.remote_response_status_handlers import (
    sales_information_submission_on_error,
    sales_information_submission_on_success,
)

# from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME
from ...utils import (
    analyze_etims_eligibility,
    build_invoice_payload,
    build_verification_url,
    generate_and_attach_qr_code,
    get_etims_id,
    get_settings,
    validate_kra_pin,
)

endpoints_builder = EndpointsBuilder()


def generic_invoices_on_submit_override(
    doc: Document, invoice_type: Literal["Sales Invoice", "POS Invoice"]
) -> None:
    """Defines a function to handle sending of Sales information from relevant invoice documents

    Args:
        doc (Document): The doctype object or record
        invoice_type (Literal["Sales Invoice", "POS Invoice"]):
        The Type of the invoice. Either Sales, or POS
    """
    company_name = (
        doc.company
        # or frappe.defaults.get_user_default("Company")
        # or frappe.get_value("Company", {}, "name")
    )

    if doc.tax_id:
        validate_kra_pin(doc.tax_id)

    settings_doc = get_settings(company_name=company_name)
    if (
        doc.prevent_etims_submission
        or (hasattr(doc, "etr_invoice_number") and doc.etr_invoice_number)
        or doc.status == "Credit Note Issued"
        or not settings_doc
    ):
        return

    customer_slade_id = get_etims_id("Customer", doc.customer, settings_doc.name)
    if not customer_slade_id:
        frappe.msgprint(
            f"Customer {doc.customer} is not registered. Cannot send invoice to eTims."
        )
        return

    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        slade_id = get_etims_id("Item", item_doc.get("name"), settings_doc.name)
        if not slade_id:
            from ...apis.apis import perform_item_registration

            perform_item_registration(item_doc.name, settings_doc.name)
            frappe.msgprint(
                f"Item {item.item_code} is not registered. Cannot send invoice to eTims."
            )
            return

    if doc.is_return:
        return_invoice = frappe.get_doc(invoice_type, doc.return_against)
        if not return_invoice.sent_to_etims:
            frappe.msgprint(
                f"Return against invoice {doc.return_against} was not Sent to eTims. Cannot process return."
            )
            return

        from ...apis.apis import submit_credit_note

        slade_id = frappe.db.get_value("Sales Invoice", doc.return_against, "etims_id")
        request_data = {
            "document_name": doc.name,
            "id": slade_id,
        }
        frappe.enqueue(
            process_request,
            queue="default",
            is_async=True,
            request_data=request_data,
            route_key="SaleSearchReq",
            handler_function=submit_credit_note,
            doctype=invoice_type,
            document_name=doc.name,
            settings_name=settings_doc.name,
        )

    else:
        payload = build_invoice_payload(doc, settings_doc.name)

        payload["invoice_type"] = invoice_type

        frappe.enqueue(
            process_request,
            enqueue_after_commit=True,
            request_data=payload,
            route_key="SalesInvoiceSaveReq",
            handler_function=sales_information_submission_on_success,
            request_method="POST",
            doctype=invoice_type,
            document_name=doc.name,
            settings_name=settings_doc.name,
            company=company_name,
            error_callback=sales_information_submission_on_error,
        )


def validate(doc: Document, method: str) -> None:
    if doc.tax_id:
        validate_kra_pin(doc.tax_id)


def before_submit(doc: Document, method: str) -> None:
    if doc.doctype == "Sales Invoice":
        response = analyze_etims_eligibility(doc.name)

        if response.get("eligible"):
            url = build_verification_url(doc)

            if not doc.get("etims_verification_url"):
                doc.etims_verification_url = url

            if not doc.etims_qr_image:
                image_url = generate_and_attach_qr_code(
                    doc.etims_verification_url, doc.name, doc.doctype
                )
                doc.etims_qr_image = image_url
