import frappe


def update_links_for_doctypes() -> None:
    doctypes = [
        "Sales Invoice",
        "Item",
        "Purchase Invoice",
        "BOM",
        "Stock Ledger Entry",
        "Customer",
        "Supplier",
    ]

    new_links = [
        {
            "link_doctype": "Integration Request",
            "group": "Logs",
            "link_fieldname": "reference_docname",
        },
        {
            "link_doctype": "Error Log",
            "group": "Logs",
            "link_fieldname": "reference_name",
        },
    ]

    for doctype_name in doctypes:
        try:
            if not frappe.db.exists("DocType", doctype_name):
                continue

            doc = frappe.get_doc("DocType", doctype_name)

            target_doctypes = [d["link_doctype"] for d in new_links]
            doc.links = [
                link
                for link in doc.get("links", [])
                if link.link_doctype not in target_doctypes
            ]

            for link_data in new_links:
                doc.append("links", link_data)

            doc.save()
            frappe.db.commit()

        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Link Update Fail: {doctype_name}",
            )


def execute() -> None:
    update_links_for_doctypes()
