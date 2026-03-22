import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """
    Updates custom_etims_taxation_type for all tax templates based on their total rates.
    """
    ensure_custom_fields_exist()
    update_item_tax_templates()
    update_sales_taxes_templates()


def ensure_custom_fields_exist():
    """
    Ensure required custom fields exist before running logic.
    """

    custom_fields = {
        "Sales Taxes and Charges Template": [
            {
                "fieldname": "custom_etims_taxation_type",
                "label": "eTims Taxation Type",
                "fieldtype": "Link",
                "options": "Navari KRA eTims Taxation Type",
                "insert_after": "tax_category",
            }
        ],
        "Item Tax Template": [
            {
                "fieldname": "custom_etims_taxation_type",
                "label": "eTims Taxation Type",
                "fieldtype": "Link",
                "options": "Navari KRA eTims Taxation Type",
                "insert_after": "taxes",
            }
        ],
    }

    filtered = {}
    for doctype, fields in custom_fields.items():
        for df in fields:
            if not frappe.db.exists(
                "Custom Field", {"dt": doctype, "fieldname": df["fieldname"]}
            ):
                filtered.setdefault(doctype, []).append(df)

    if filtered:
        create_custom_fields(filtered)
        frappe.db.commit()


def update_item_tax_templates():
    """
    Calculates total rate for Item Tax Templates and sets the taxation code.
    """
    templates = frappe.get_all("Item Tax Template", fields=["name"])

    for t in templates:
        doc = frappe.get_doc("Item Tax Template", t.name)

        if doc.custom_etims_taxation_type:
            continue

        total_rate = sum(float(tax.tax_rate or 0) for tax in doc.taxes)

        taxation_code = _determine_logic_based_code(total_rate)

        frappe.db.set_value(
            "Item Tax Template",
            doc.name,
            "custom_etims_taxation_type",
            taxation_code,
            update_modified=False,
        )
        print(
            f"Updated Item Tax Template {doc.name}: Rate {total_rate}% -> {taxation_code}"
        )


def update_sales_taxes_templates():
    """
    Calculates total rate for Sales Taxes and Charges Templates and sets the taxation code.
    """
    templates = frappe.get_all("Sales Taxes and Charges Template", fields=["name"])

    for t in templates:
        doc = frappe.get_doc("Sales Taxes and Charges Template", t.name)

        if doc.custom_etims_taxation_type:
            continue

        total_rate = sum(float(tax.rate or 0) for tax in doc.taxes)

        taxation_code = _determine_logic_based_code(total_rate)

        frappe.db.set_value(
            "Sales Taxes and Charges Template",
            doc.name,
            "custom_etims_taxation_type",
            taxation_code,
            update_modified=False,
        )
        print(
            f"Updated Sales Taxes Template {doc.name}: Rate {total_rate}% -> {taxation_code}"
        )


def _determine_logic_based_code(rate: float) -> str:
    """
    Pure logic helper to map a total rate to an eTIMS taxation code.
    """
    r = round(rate)
    if r >= 16:
        return "B"
    if r >= 8:
        return "E"
    if r == 0:
        return "A"
    return "A"
