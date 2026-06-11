import frappe


def execute() -> None:
    print("Starting the unhide eTims fields patch...")

    cleanup_property_setters()

    print("Patch execution completed successfully.")


def cleanup_property_setters() -> None:
    property_setters = frappe.get_all(
        "Property Setter",
        filters={"module": "eTims", "property": "hidden"},
        pluck="name",
    )

    print(f"Found {len(property_setters)} property setters to delete.")

    for setter in property_setters:
        print(f"Deleting Property Setter: {setter}")
        frappe.delete_doc("Property Setter", setter)

    frappe.db.commit()
    print("Database changes committed successfully.")
