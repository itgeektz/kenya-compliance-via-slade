import frappe


def execute():
    doctypes = [
        "eTims ID Mapping",
        "eTims Settings Organisation Mapping",
        "eTims Company Setup Mapping",
    ]

    for doctype in doctypes:
        if frappe.db.exists("DocType", doctype):
            frappe.db.set_value(
                doctype, {"is_active": 0}, "is_active", 1, update_modified=False
            )
            print(f"Successfully activated all records for {doctype}")
        else:
            print(f"Skipping: {doctype} does not exist in this environment.")
