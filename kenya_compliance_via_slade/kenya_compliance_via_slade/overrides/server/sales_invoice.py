import frappe
from erpnext.setup.utils import get_exchange_rate
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import add_to_date, flt, getdate

from ...utils import (
    apply_item_taxes_and_codes,
    get_settings,
)
from .shared_overrides import generic_invoices_on_submit_override


def on_submit(doc: Document, method: str = None) -> None:
    company_name = (
        doc.company
        # or frappe.defaults.get_user_default("Company")
        # or frappe.get_value("Company", {}, "name")
    )
    settings_doc = get_settings(company_name=company_name)
    if not settings_doc:
        return

    apply_item_taxes_and_codes(doc)

    if (
        doc.sent_to_etims == 0
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

    if doc.doctype == "Sales Invoice" and doc.sent_to_etims:
        frappe.throw(
            "This invoice has already been <b>submitted</b> to eTIMS and cannot be <span style='color:red'>Canceled.</span>\n"
            "If you need to make adjustments, please create a Credit Note instead."
        )
    elif doc.doctype == "Purchase Invoice" and doc.sent_to_etims:
        frappe.throw(
            "This invoice has already been <b>submitted</b> to eTIMS and cannot be <span style='color:red'>Canceled.</span>.\nIf you need to make adjustments, please create a Debit Note instead."
        )


@frappe.whitelist()
def get_single_invoice_reconciliation(invoice_name):
    if not invoice_name:
        frappe.throw("Invoice name is required")

    invoice = frappe.get_cached_doc("Sales Invoice", invoice_name)
    company_currency = frappe.db.get_value(
        "Company", invoice.company, "default_currency"
    )
    currency = invoice.currency

    posting_date = getdate(invoice.posting_date)
    creation_date = getdate(invoice.creation) if invoice.creation else None

    if creation_date and creation_date < posting_date:
        from_date = creation_date
    else:
        from_date = add_to_date(posting_date, months=-3)

    to_date = getdate(add_to_date(posting_date, days=1))

    erp_data = _get_erp_amounts(invoice, company_currency, currency, from_date, to_date)
    etims_data = _get_etims_data(invoice, from_date, to_date)

    return _calculate_reconciliation_summary(
        invoice, erp_data, etims_data, from_date, to_date, company_currency, currency
    )


def _get_erp_amounts(invoice, company_currency, currency, from_date, to_date):
    SI = DocType("Sales Invoice")

    conversion_rate = 1.0
    if currency != "KES" and company_currency != "KES":
        conversion_rate = get_exchange_rate(currency, "KES", invoice.posting_date)

    if currency == "KES":
        invoice_amount = flt(invoice.grand_total)
        invoice_tax = flt(invoice.total_taxes_and_charges)
    elif company_currency == "KES":
        invoice_amount = flt(invoice.base_grand_total)
        invoice_tax = flt(invoice.base_total_taxes_and_charges)
    else:
        invoice_amount = flt(invoice.grand_total) * conversion_rate
        invoice_tax = flt(invoice.total_taxes_and_charges) * conversion_rate

    in_period = getdate(from_date) <= getdate(invoice.posting_date) <= getdate(to_date)
    invoice_period_amount = invoice_amount if in_period else 0
    invoice_tax_period = invoice_tax if in_period else 0

    credit_notes = frappe.get_all(
        "Sales Invoice",
        filters={"is_return": 1, "return_against": invoice.name, "docstatus": 1},
        fields=[
            "name",
            "grand_total",
            "base_grand_total",
            "total_taxes_and_charges",
            "base_total_taxes_and_charges",
            "posting_date",
            "currency",
        ],
    )

    credit_amount_all = 0
    credit_amount_period = 0
    credit_tax_period = 0

    for cn in credit_notes:
        if cn.currency == "KES":
            cn_amount = flt(cn.grand_total)
            cn_tax = flt(cn.total_taxes_and_charges)
        elif company_currency == "KES":
            cn_amount = flt(cn.base_grand_total)
            cn_tax = flt(cn.base_total_taxes_and_charges)
        else:
            cn_rate = get_exchange_rate(cn.currency, "KES", cn.posting_date)
            cn_amount = flt(cn.grand_total) * cn_rate
            cn_tax = flt(cn.total_taxes_and_charges) * cn_rate

        credit_amount_all += cn_amount

        if getdate(from_date) <= getdate(cn.posting_date) <= getdate(to_date):
            credit_amount_period += cn_amount
            credit_tax_period += cn_tax

    return {
        "invoice_amount": invoice_amount,
        "invoice_period_amount": invoice_period_amount,
        "invoice_tax": invoice_tax,
        "invoice_tax_period": invoice_tax_period,
        "credit_amount_all": credit_amount_all,
        "credit_amount_period": credit_amount_period,
        "credit_tax_period": credit_tax_period,
        "from_date": from_date,
        "to_date": to_date,
    }


def _get_etims_data(invoice, from_date, to_date):
    Ledger = DocType("eTIMS Sales Ledger Entry")
    reference_number = invoice.return_against if invoice.is_return else invoice.name

    query = (
        frappe.qb.from_(Ledger)
        .select(
            Ledger.name,
            Ledger.sales_invoice,
            Ledger.invoice_date,
            Ledger.type,
            Ledger.total_gross_amount,
            Ledger.total_vat,
            Ledger.customer_name,
            Ledger.reference_number,
            Ledger.scu_invoice_number,
            Ledger.is_signed,
        )
        .where(Ledger.company == invoice.company)
        .where(
            (Ledger.sales_invoice == invoice.name)
            | (Ledger.reference_number == reference_number)
        )
        .where(Ledger.invoice_date.between(from_date, to_date))
    )

    entries = query.run(as_dict=True)

    etims_invoice_amount = 0
    etims_credit_amount = 0
    etims_tax_amount = 0
    etims_credit_tax = 0
    details = []

    for entry in entries:
        if entry.type == "Sales Invoice":
            etims_invoice_amount += flt(entry.total_gross_amount)
            etims_tax_amount += flt(entry.total_vat)
        elif entry.type == "Credit Note":
            etims_credit_amount += abs(flt(entry.total_gross_amount))
            etims_credit_tax += abs(flt(entry.total_vat))

        details.append(
            {
                "invoice_date": entry.invoice_date,
                "customer": entry.customer_name,
                "type": entry.type,
                "reference_number": entry.reference_number,
                "scu_invoice_number": entry.scu_invoice_number,
                "is_signed": entry.is_signed,
                "amount": flt(entry.total_gross_amount)
                if entry.type == "Sales Invoice"
                else -abs(flt(entry.total_gross_amount)),
                "tax": flt(entry.total_vat)
                if entry.type == "Sales Invoice"
                else -abs(flt(entry.total_vat)),
            }
        )

    if invoice.is_return and not details:
        details.append(
            {
                "invoice_date": invoice.posting_date,
                "customer": invoice.customer_name,
                "type": "Credit Note (Unmatched)",
                "reference_number": "Not Found on eTIMS",
                "scu_invoice_number": "",
                "is_signed": 0,
                "amount": -abs(flt(invoice.grand_total)),
                "tax": -abs(flt(invoice.total_taxes_and_charges)),
            }
        )

    return {
        "invoice_amount": etims_invoice_amount,
        "credit_amount": etims_credit_amount,
        "tax_amount": etims_tax_amount,
        "credit_tax": etims_credit_tax,
        "details": details,
        "total_entries": len(details),
    }


def _calculate_reconciliation_summary(
    invoice, erp_data, etims_data, from_date, to_date, company_currency, currency
):
    erp_invoice = erp_data["invoice_period_amount"]
    erp_credit = erp_data["credit_amount_period"]
    erp_tax = erp_data["invoice_tax_period"]

    if invoice.is_return:
        erp_invoice = 0
        erp_credit = -abs(flt(invoice.grand_total))
        erp_tax = -abs(flt(invoice.total_taxes_and_charges))

        if (
            etims_data["details"]
            and etims_data["details"][0]["type"] != "Credit Note (Unmatched)"
        ):
            etims_credit = -etims_data["credit_amount"]
        else:
            etims_credit = 0
        etims_invoice = 0
    else:
        etims_invoice = etims_data["invoice_amount"]
        etims_credit = -etims_data["credit_amount"]

    invoice_diff = erp_invoice - etims_invoice
    credit_diff = erp_credit - etims_credit

    erp_net = erp_invoice + erp_credit
    etims_net = etims_invoice + etims_credit
    net_diff = erp_net - etims_net

    invoice_diff_pct = (abs(invoice_diff) / erp_invoice * 100) if erp_invoice > 0 else 0
    credit_diff_pct = (
        (abs(credit_diff) / abs(erp_credit) * 100) if erp_credit != 0 else 0
    )
    net_diff_pct = (abs(net_diff) / abs(erp_net) * 100) if abs(erp_net) > 0 else 0

    has_significant_mismatch = (
        invoice_diff_pct > 0.5 or credit_diff_pct > 0.5 or net_diff_pct > 0.5
    )

    tax_diff = etims_data["tax_amount"] - erp_tax
    tax_diff_pct = (abs(tax_diff) / abs(erp_tax) * 100) if erp_tax != 0 else 0

    return {
        "has_significant_mismatch": has_significant_mismatch,
        "invoice_diff_percent": invoice_diff_pct,
        "credit_diff_percent": credit_diff_pct,
        "net_diff_percent": net_diff_pct,
        "tax_diff_percent": tax_diff_pct,
        "erp_invoice_amount": erp_invoice,
        "erp_credit_amount": erp_credit,
        "erp_tax_amount": erp_tax,
        "erp_net_amount": erp_net,
        "etims_invoice_amount": etims_invoice,
        "etims_credit_amount": etims_credit,
        "etims_tax_amount": etims_data["tax_amount"],
        "etims_net_amount": etims_net,
        "invoice_difference": invoice_diff,
        "credit_difference": credit_diff,
        "net_difference": net_diff,
        "tax_difference": tax_diff,
        "from_date": from_date,
        "to_date": to_date,
        "total_etims_entries": etims_data["total_entries"],
        "details": etims_data["details"],
        "sent_to_etims": invoice.sent_to_etims,
    }
