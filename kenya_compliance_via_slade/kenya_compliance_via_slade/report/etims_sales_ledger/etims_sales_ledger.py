# Copyright (c) 2026, Navari Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    validate_filters(filters)

    columns = get_columns(filters)
    data = get_data(filters)
    chart = get_chart(data)
    report_summary = get_report_summary(data)

    return columns, data, None, chart, report_summary


def validate_filters(filters):
    if filters.get("from_date") and filters.get("to_date"):
        if filters.get("from_date") > filters.get("to_date"):
            frappe.throw(_("From Date must be before To Date"))


def get_columns(filters):
    filters = filters or {}
    show_details = filters.get("show_details")

    base_columns = [
        {
            "label": _("Sales Invoice"),
            "fieldname": "sales_invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 150,
        },
        {
            "label": _("Customer"),
            "fieldname": "customer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 180,
        },
        {
            "label": _("Invoice Date"),
            "fieldname": "invoice_date",
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "label": _("ERP Invoice"),
            "fieldname": "erp_invoice_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("ERP Tax"),
            "fieldname": "erp_tax_amount",
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "label": _("ERP Credit"),
            "fieldname": "erp_credit_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
    ]

    etims_columns = [
        {
            "label": _("Type"),
            "fieldname": "type",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Signed"),
            "fieldname": "is_signed",
            "fieldtype": "Check",
            "width": 80,
        },
        {
            "label": _("Reference"),
            "fieldname": "reference_number",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": _("SCU No"),
            "fieldname": "scu_invoice_number",
            "fieldtype": "Data",
            "width": 150,
        },
    ]

    summary_columns = [
        {
            "label": _("eTIMS Invoice"),
            "fieldname": "etims_invoice_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("eTIMS Credit"),
            "fieldname": "etims_credit_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("eTIMS VAT"),
            "fieldname": "etims_total_tax",
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "label": _("Difference"),
            "fieldname": "difference",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Tax Difference"),
            "fieldname": "tax_difference",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Status"),
            "fieldname": "reconciliation_status",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": _("Indent"),
            "fieldname": "indent",
            "fieldtype": "Int",
            "hidden": 1,
        },
        {
            "label": _("Parent"),
            "fieldname": "parent",
            "fieldtype": "Data",
            "hidden": 1,
        },
        {
            "label": _("Group"),
            "fieldname": "is_group",
            "fieldtype": "Check",
            "hidden": 1,
        },
    ]

    columns = base_columns

    if show_details:
        columns.extend(etims_columns)

    columns.extend(summary_columns)

    return columns


def get_data(filters):
    Ledger = DocType("eTIMS Sales Ledger Entry")
    SI = DocType("Sales Invoice")

    query = (
        frappe.qb.from_(Ledger)
        .select(
            Ledger.sales_invoice,
            Ledger.invoice_date,
            Ledger.type,
            Ledger.total_amount,
            Ledger.total_vat,
            Ledger.customer_name,
            Ledger.reference_number,
            Ledger.scu_invoice_number,
            Ledger.is_signed,
        )
        .where(Ledger.company == filters.get("company"))
        .where(
            Ledger.invoice_date.between(
                filters.get("from_date"),
                filters.get("to_date"),
            )
        )
    )

    if filters.get("sales_invoice"):
        query = query.where(Ledger.sales_invoice == filters.get("sales_invoice"))

    if filters.get("customer"):
        query = query.where(Ledger.customer_name == filters.get("customer"))

    if filters.get("type"):
        query = query.where(Ledger.type == filters.get("type"))

    if filters.get("is_signed"):
        query = query.where(
            Ledger.is_signed == (1 if filters.get("is_signed") == "Yes" else 0)
        )

    rows = query.run(as_dict=True)

    grouped = {}

    for r in rows:
        key = r.sales_invoice or "UNKNOWN"

        if key not in grouped:
            erp = (
                frappe.db.get_value(
                    "Sales Invoice",
                    key,
                    [
                        "customer",
                        "posting_date",
                        "grand_total",
                        "total_taxes_and_charges",
                    ],
                    as_dict=True,
                )
                or {}
            )

            credit = (
                frappe.qb.from_(SI)
                .select(Sum(SI.grand_total).as_("total"))
                .where(SI.is_return == 1)
                .where(SI.return_against == key)
                .run(as_dict=True)[0]
                .total
                or 0
            )

            grouped[key] = {
                "sales_invoice": key,
                "customer": erp.get("customer"),
                "invoice_date": erp.get("posting_date"),
                "erp_invoice_amount": flt(erp.get("grand_total")),
                "erp_tax_amount": flt(erp.get("total_taxes_and_charges")),
                "erp_credit_amount": flt(credit),
                "etims_invoice_amount": 0,
                "etims_credit_amount": 0,
                "etims_total_tax": 0,
                "difference": 0,
                "tax_difference": 0,
                "indent": 0,
                "parent": "",
                "is_group": 1,
            }

        if r.type == "Sales Invoice":
            grouped[key]["etims_invoice_amount"] += flt(r.total_amount)
        else:
            grouped[key]["etims_credit_amount"] += flt(r.total_amount)

        grouped[key]["etims_total_tax"] += flt(r.total_vat)

        grouped[key].setdefault("children", []).append(
            {
                "sales_invoice": "",
                "customer": r.customer_name,
                "invoice_date": r.invoice_date,
                "type": r.type,
                "is_signed": r.is_signed,
                "reference_number": r.reference_number,
                "scu_invoice_number": r.scu_invoice_number,
                "etims_invoice_amount": flt(r.total_amount)
                if r.type == "Sales Invoice"
                else 0,
                "etims_credit_amount": flt(r.total_amount)
                if r.type == "Credit Note"
                else 0,
                "etims_total_tax": flt(r.total_vat),
                "difference": 0,
                "tax_difference": 0,
                "indent": 1,
                "parent": key,
                "is_group": 0,
            }
        )

    result = []

    total_erp_invoice = 0
    total_erp_credit = 0
    total_erp_tax = 0
    total_etims_invoice = 0
    total_etims_credit = 0
    total_etims_tax = 0
    total_difference = 0

    for key, row in grouped.items():
        etims_total = flt(row["etims_invoice_amount"]) + flt(row["etims_credit_amount"])

        erp_total = flt(row["erp_invoice_amount"]) + flt(row["erp_credit_amount"])

        row["difference"] = etims_total - erp_total
        row["tax_difference"] = flt(row["etims_total_tax"]) - flt(row["erp_tax_amount"])

        if key == "UNKNOWN":
            row["reconciliation_status"] = "Missing in ERPNext"
        elif abs(row["difference"]) > 1:
            row["reconciliation_status"] = "Amount Mismatch"
        else:
            row["reconciliation_status"] = "Matched"

        total_erp_invoice += flt(row["erp_invoice_amount"])
        total_erp_credit += flt(row["erp_credit_amount"])
        total_erp_tax += flt(row["erp_tax_amount"])
        total_etims_invoice += flt(row["etims_invoice_amount"])
        total_etims_credit += flt(row["etims_credit_amount"])
        total_etims_tax += flt(row["etims_total_tax"])
        total_difference += flt(row["difference"])

        children = row.pop("children", [])

        result.append(row)
        result.extend(children)

    result.append(
        {
            "sales_invoice": "TOTAL",
            "customer": "",
            "invoice_date": "",
            "erp_invoice_amount": total_erp_invoice,
            "erp_tax_amount": total_erp_tax,
            "erp_credit_amount": total_erp_credit,
            "etims_invoice_amount": total_etims_invoice,
            "etims_credit_amount": total_etims_credit,
            "etims_total_tax": total_etims_tax,
            "difference": total_difference,
            "tax_difference": total_etims_tax - total_erp_tax,
            "reconciliation_status": "",
            "indent": 0,
            "parent": "",
            "is_group": 1,
        }
    )

    return result


def get_chart(data):
    total_erp_invoice = 0
    total_etims_invoice = 0
    total_erp_credit = 0
    total_etims_credit = 0
    total_difference = 0

    for d in data:
        if d.get("sales_invoice") == "TOTAL":
            total_erp_invoice = flt(d.get("erp_invoice_amount"))
            total_etims_invoice = flt(d.get("etims_invoice_amount"))
            total_erp_credit = flt(d.get("erp_credit_amount"))
            total_etims_credit = flt(d.get("etims_credit_amount"))
            total_difference = flt(d.get("difference"))

    return {
        "data": {
            "labels": [
                "ERP Invoice",
                "eTIMS Invoice",
                "ERP Credit",
                "eTIMS Credit",
                "Difference",
            ],
            "datasets": [
                {
                    "name": "Amounts",
                    "values": [
                        total_erp_invoice,
                        total_etims_invoice,
                        total_erp_credit,
                        total_etims_credit,
                        total_difference,
                    ],
                }
            ],
        },
        "type": "bar",
        "height": 300,
        "barOptions": {
            "stacked": 0,
        },
    }


def get_report_summary(data):
    total_erp_invoice = 0
    total_etims_invoice = 0
    total_erp_credit = 0
    total_etims_credit = 0
    total_difference = 0

    for d in data:
        if d.get("sales_invoice") == "TOTAL":
            total_erp_invoice = flt(d.get("erp_invoice_amount"))
            total_etims_invoice = flt(d.get("etims_invoice_amount"))
            total_erp_credit = flt(d.get("erp_credit_amount"))
            total_etims_credit = flt(d.get("etims_credit_amount"))
            total_difference = flt(d.get("difference"))

    return [
        {
            "value": total_erp_invoice,
            "label": _("Total ERP Invoices"),
            "datatype": "Currency",
        },
        {
            "value": total_etims_invoice,
            "label": _("Total eTIMS Invoices"),
            "datatype": "Currency",
        },
        {
            "value": total_erp_credit + total_etims_credit,
            "label": _("Total Credit Notes"),
            "datatype": "Currency",
        },
        {
            "value": total_difference,
            "label": _("Total Difference"),
            "datatype": "Currency",
            "indicator": "Red" if abs(total_difference) > 1 else "Green",
        },
    ]
