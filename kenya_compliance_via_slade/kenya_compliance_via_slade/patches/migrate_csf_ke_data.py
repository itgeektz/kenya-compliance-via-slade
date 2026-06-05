import frappe

from ..utils import (
    build_verification_url,
)


def execute():
    migrate_etims_id_mapping()

    migrate_doctype_fields(
        "Item",
        {
            "custom_prevent_etims_registration": "prevent_etims_registration",
            "custom_submission_tries": "submission_tries",
            "custom_taxation_type": "taxation_type",
            "custom_taxation_type_name": "taxation_type_name",
            "custom_item_classification": "item_classification",
            "custom_item_classification_code": "item_classification_code",
            "custom_etims_country_of_origin": "etims_country_of_origin",
            "custom_etims_country_of_origin_code": "etims_country_of_origin_code",
            "custom_packaging_unit": "packaging_unit",
            "custom_unit_of_quantity_code": "unit_of_quantity_code",
            "custom_unit_of_quantity": "unit_of_quantity",
            "custom_packaging_unit_code": "packaging_unit_code",
            "custom_item_type": "item_type",
            "custom_product_type": "product_type",
            "custom_item_type_name": "item_type_name",
            "custom_product_type_name": "product_type_name",
        },
        "eTims Item Field Migration Failed",
    )

    migrate_doctype_fields(
        "Item Group",
        {
            "custom_prevent_etims_registration": "prevent_etims_registration",
            "custom_taxation_type": "taxation_type",
            "custom_taxation_type_name": "taxation_type_name",
            "custom_item_classification": "item_classification",
            "custom_item_classification_code": "item_classification_code",
            "custom_etims_country_of_origin": "etims_country_of_origin",
            "custom_etims_country_of_origin_code": "etims_country_of_origin_code",
            "custom_packaging_unit": "packaging_unit",
            "custom_unit_of_quantity_code": "unit_of_quantity_code",
            "custom_unit_of_quantity": "unit_of_quantity",
            "custom_packaging_unit_code": "packaging_unit_code",
            "custom_item_type": "item_type",
            "custom_product_type": "product_type",
            "custom_item_type_name": "item_type_name",
            "custom_product_type_name": "product_type_name",
        },
        "eTims Item Group Field Migration Failed",
    )

    migrate_doctype_fields(
        "Item Tax Template",
        {
            "custom_etims_taxation_type": "etims_taxation_type",
        },
        "eTims Item Tax Template Field Migration Failed",
    )

    migrate_doctype_fields(
        "Sales Taxes and Charges Template",
        {
            "custom_etims_taxation_type": "etims_taxation_type",
        },
        "eTims Sales Taxes and Charges Template Field Migration Failed",
    )

    migrate_doctype_fields(
        "Stock Ledger Entry",
        {
            "custom_submitted_successfully": "sent_to_etims",
            "custom_submission_tries": "submission_attempts",
            "custom_slade_id": "etims_id",
        },
        "eTims Stock Ledger Entry Field Migration Failed",
    )

    migrate_doctype_fields(
        "Sales Invoice",
        {
            "custom_successfully_submitted": "sent_to_etims",
            "custom_slade_id": "etims_id",
            "custom_qr_code_url": "qr_code_url",
            "custom_submission_attempts": "submission_attempts",
            "custom_qr_code": "etims_qr_image",
        },
        "eTims Sales Invoice Field Migration Failed",
    )

    migrate_doctype_fields(
        "Sales Invoice Item",
        {
            "custom_tax_amount": "tax_amount",
            "custom_base_tax_amount": "base_tax_amount",
            "custom_tax_rate": "tax_rate",
        },
        "eTims Sales Invoice Item Field Migration Failed",
    )

    migrate_doctype_fields(
        "Customer",
        {
            "custom_prevent_etims_registration": "prevent_etims_registration",
        },
        "eTims Customer Field Migration Failed",
    )

    generate_invoice_verification_urls()


def get_valid_field_map(doctype, field_map):
    if not frappe.db.exists("DocType", doctype):
        return {}

    valid_map = {}
    for src, target in field_map.items():
        if frappe.db.has_column(doctype, src) and frappe.db.has_column(doctype, target):
            valid_map[src] = target
    return valid_map


def migrate_doctype_fields(doctype, field_map, error_title):
    valid_field_map = get_valid_field_map(doctype, field_map)
    if not valid_field_map:
        return

    records = frappe.get_all(
        doctype,
        fields=["name"] + list(valid_field_map.keys()),
        limit_page_length=0,
    )

    for record in records:
        try:
            update_values = {}

            for src, target in valid_field_map.items():
                value = getattr(record, src, None)
                if value is not None:
                    update_values[target] = value

            if not update_values:
                continue

            frappe.db.set_value(
                doctype,
                record.name,
                update_values,
                update_modified=False,
            )

        except Exception:
            frappe.log_error(
                title=error_title,
                message=frappe.get_traceback(),
            )


def migrate_etims_id_mapping():
    if not frappe.db.exists(
        "DocType", "eTims Slade360 ID Mapping"
    ) or not frappe.db.exists("DocType", "eTims ID Mapping"):
        return

    old_rows = frappe.get_all(
        "eTims Slade360 ID Mapping",
        fields=[
            "name",
            "parent",
            "parenttype",
            "etims_setup",
            "slade360_id",
            "is_active",
        ],
        limit_page_length=0,
    )

    for row in old_rows:
        try:
            exists = frappe.db.exists(
                "eTims ID Mapping",
                {
                    "setup_doctype": "Navari KRA eTims Settings",
                    "setup_docname": row.etims_setup,
                    "etims_id": row.slade360_id,
                },
            )

            if exists:
                continue

            doc = frappe.get_doc(
                {
                    "doctype": "eTims ID Mapping",
                    "setup_doctype": "Navari KRA eTims Settings",
                    "setup_docname": row.etims_setup,
                    "etims_id": row.slade360_id,
                    "disabled": 0 if row.is_active else 1,
                    "parent": row.parent,
                    "parenttype": row.parenttype,
                    "parentfield": "etims_id_mapping",
                }
            )

            doc.insert(ignore_permissions=True)

        except Exception:
            frappe.log_error(
                title="eTims ID Mapping Migration Failed",
                message=frappe.get_traceback(),
            )


def generate_invoice_verification_urls():
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "etims_verification_url": ("is", None)},
        fields=["name"],
        limit_page_length=0,
    )

    for invoice in invoices:
        try:
            doc = frappe.get_doc("Sales Invoice", invoice.name)
            url = build_verification_url(doc)
            if url:
                frappe.db.set_value(
                    "Sales Invoice",
                    invoice.name,
                    "etims_verification_url",
                    url,
                    update_modified=False,
                )
        except Exception:
            frappe.log_error(
                title="Invoice Verification URL Generation Failed",
                message=frappe.get_traceback(),
            )
