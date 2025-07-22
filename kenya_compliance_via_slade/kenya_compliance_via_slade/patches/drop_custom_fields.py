import frappe

def execute() -> None:
    """Delete all custom fields related to Kenya Compliance Via Slade module"""
    custom_fields = frappe.get_all(
        "Custom Field", 
        filters={"module": "Kenya Compliance Via Slade"},
        pluck="name"
    )
    
    for field in custom_fields:
        frappe.delete_doc("Custom Field", field)
        
    frappe.db.commit()