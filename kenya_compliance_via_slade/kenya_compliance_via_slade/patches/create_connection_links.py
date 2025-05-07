import frappe

def update_links_for_doctypes() -> None:
    doctypes = [
        "Sales Invoice", 
        "Item", 
        "Purchase Invoice", 
        "BOM", 
        "Stock Ledger Entry", 
        "Customer", 
        "Supplier"
    ]
    for doctype in doctypes:
        doc = frappe.get_doc("DocType", doctype)

        # Filter out existing links to Integration Request
        doc.links = [
            link for link in doc.get("links", [])
            if link.link_doctype != "Integration Request"
        ]

        # Add fresh Integration Request link
        doc.append(
            "links",
            {
                "link_doctype": "Integration Request",
                "group": "Integration Request",
                "link_fieldname": "reference_docname",
            },
        )

        doc.save()
        frappe.db.commit()

def execute() -> None:
    update_links_for_doctypes()
