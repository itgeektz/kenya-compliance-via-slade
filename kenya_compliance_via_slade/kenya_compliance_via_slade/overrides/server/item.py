import frappe
import frappe.defaults
from frappe import _
from frappe.model.document import Document

from ...apis.apis import perform_item_registration
from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME, SLADE_ID_MAPPING_DOCTYPE_NAME
from ...utils import generate_custom_item_code_etims, get_active_settings


def on_update(doc: Document, method: str = None) -> None:
    """Item doctype before insertion hook"""
    active_settings = get_active_settings()
    
    if not active_settings:
        return
    
    for setting in active_settings:
        setup_mapping = frappe.db.get_value(
            SLADE_ID_MAPPING_DOCTYPE_NAME,
            {"parent": doc.name, "etims_setup": setting.name},
            "name"
        )
        
        if not setup_mapping:
            perform_item_registration(doc.name, setting.name)


def validate(doc: Document, method: str = None) -> None:
    is_tax_type_changed = doc.has_value_changed("custom_taxation_type")
    if doc.custom_taxation_type and is_tax_type_changed:
        relevant_tax_templates = frappe.get_all(
            "Item Tax Template",
            ["*"],
            {"custom_etims_taxation_type": doc.custom_taxation_type},
        )

        if relevant_tax_templates:
            doc.set("taxes", [])
            for template in relevant_tax_templates:
                doc.append("taxes", {"item_tax_template": template.name})

    if doc.custom_prevent_etims_registration != 1:
        missing_fields = []
        if not doc.custom_etims_country_of_origin_code:
            missing_fields.append("Country of Origin Code")
        if not doc.custom_product_type:
            missing_fields.append("Product Type")
        if not doc.custom_packaging_unit_code:
            missing_fields.append("Packaging Unit Code")
        if not doc.custom_unit_of_quantity_code:
            missing_fields.append("Unit of Quantity Code")
        if not doc.custom_item_classification:
            missing_fields.append("Item Classification")
        if not doc.custom_taxation_type:
            missing_fields.append("Taxation Type")

        if missing_fields:
            frappe.throw(_("Please fill in the following required fields: {0}").format(", ".join(missing_fields)))

    if not doc.custom_item_code_etims:
        doc.custom_item_code_etims = generate_custom_item_code_etims(doc)


@frappe.whitelist()
def prevent_item_deletion(doc: dict) -> None:
    if not frappe.db.exists(SETTINGS_DOCTYPE_NAME, {"is_active": 1}):
        return
    if doc.custom_item_registered == 1:  # Assuming 1 means registered, adjust as needed
        frappe.throw(_("Cannot delete registered items"))
    pass
