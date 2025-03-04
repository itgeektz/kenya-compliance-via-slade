import frappe


def execute() -> None:
    doctypes = ["Sales Invoice", "Item", "Purchase Invoice", "BOM"]

    for doctype in doctypes:
        doc = frappe.get_doc("DocType", doctype)

        if not any(
            link.link_doctype == "Integration Request"
            and link.link_fieldname == "reference_docname"
            for link in doc.__dict__.get("links", [])
        ):
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
