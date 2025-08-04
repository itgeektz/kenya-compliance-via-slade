from typing import Literal

import frappe
from frappe.model.document import Document

from ...apis.api_builder import EndpointsBuilder
from ...apis.process_request import process_request
from ...apis.remote_response_status_handlers import (
    sales_information_submission_on_success,
    sales_information_submission_on_error,
)
# from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME
from ...utils import build_invoice_payload, get_invoice_reference_number, get_settings, get_slade360_id

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

    settings_doc = get_settings(company_name=company_name)
    if doc.prevent_etims_submission or (hasattr(doc, "etr_invoice_number") and doc.etr_invoice_number) or doc.status == "Credit Note Issued":
        return


    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        slade_id =  get_slade360_id("Item", item_doc.get("name"), settings_doc.name)
        if not slade_id:
            from ...apis.apis import perform_item_registration

            perform_item_registration(item_doc.name, settings_doc.name)
            frappe.msgprint(
                f"Item {item.item_code} is not registered. Cannot send invoice to eTims."
            )
            return


    if doc.is_return:
        return_invoice = frappe.get_doc(invoice_type, doc.return_against)
        if not return_invoice.custom_successfully_submitted:
            frappe.msgprint(
                f"Return against invoice {doc.return_against} was not successfully submitted. Cannot process return."
            )
            return
        
        from ...apis.apis import submit_credit_note
        reference_number = get_invoice_reference_number(return_invoice)
        request_data = {
            "document_name": doc.name,
            "company": company_name,
            "reference_number": reference_number,
        }
        frappe.enqueue(
            process_request,
            queue="default",
            is_async=True,
            request_data=request_data,
            route_key="TrnsSalesSaveWrReq",
            handler_function=submit_credit_note,
            doctype=invoice_type,
            settings_name=settings_doc.name,
        )
        
    else:
        payload = build_invoice_payload(doc)
        additional_context = {
            "invoice_type": invoice_type,
        }
        process_request(
            payload,
            "SalesInvoiceSaveReq",
            lambda response, **kwargs: sales_information_submission_on_success(
                response=response,
                **additional_context,
                **kwargs,
            ),
            request_method="POST",
            doctype=invoice_type,
            settings_name=settings_doc.name,
            company=company_name,
            error_callback=sales_information_submission_on_error,
        )


def validate(doc: Document, method: str) -> None:
    pass
    # vendor = ""
    # doc.custom_scu_id = get_curr_env_etims_settings(
    #     frappe.defaults.get_user_default("Company"), vendor, doc.branch
    # ).scu_id

    # item_taxes = get_itemised_tax_breakup_data(doc)

    # taxes_breakdown = defaultdict(list)
    # taxable_breakdown = defaultdict(list)
    # tax_head = doc.taxes[0].description

    # for index, item in enumerate(doc.items):
    #     taxes_breakdown[item.custom_taxation_type_code].append(
    #         item_taxes[index][tax_head]["tax_amount"]
    #     )
    #     taxable_breakdown[item.custom_taxation_type_code].append(
    #         item_taxes[index]["taxable_amount"]
    #     )

    # update_tax_breakdowns(doc, (taxes_breakdown, taxable_breakdown))


# def update_tax_breakdowns(invoice: Document, mapping: tuple) -> None:
#     invoice.custom_tax_a = round(sum(mapping[0]["A"]), 2)
#     invoice.custom_tax_b = round(sum(mapping[0]["B"]), 2)
#     invoice.custom_tax_c = round(sum(mapping[0]["C"]), 2)
#     invoice.custom_tax_d = round(sum(mapping[0]["D"]), 2)
#     invoice.custom_tax_e = round(sum(mapping[0]["E"]), 2)

#     invoice.custom_taxbl_amount_a = round(sum(mapping[1]["A"]), 2)
#     invoice.custom_taxbl_amount_b = round(sum(mapping[1]["B"]), 2)
#     invoice.custom_taxbl_amount_c = round(sum(mapping[1]["C"]), 2)
#     invoice.custom_taxbl_amount_d = round(sum(mapping[1]["D"]), 2)
#     invoice.custom_taxbl_amount_e = round(sum(mapping[1]["E"]), 2)
