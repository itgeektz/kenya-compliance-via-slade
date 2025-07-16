import frappe
from ..doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME

def execute() -> None:
    # Migrate existing eTims records to multi-company setup
    setups = frappe.get_all(
        SETTINGS_DOCTYPE_NAME,
        filters={"is_active": 1},
        fields=["name", "company"]
    )
    
    if not setups:
        return
    
    if len(setups) == 1:
        setup = frappe.get_doc(SETTINGS_DOCTYPE_NAME, setups[0].name)
        if setup.organisation_mapping:
            return
        update_setting(setup)
        frappe.db.commit()

def update_setting(setup):
    setup.append("organisation_mapping", {
        "company": setup.company,
        "branch": setup.bhfid,
        "warehouse": setup.warehouse,
        "workstation": setup.workstation,
        "department": setup.department,
        "is_active": 1,
    })
    setup.save()
