import frappe
import frappe.defaults
from frappe import _
from frappe.model.document import Document

from ...apis.apis import perform_item_registration
from ...doctype.doctype_names_mapping import (
    SETTINGS_DOCTYPE_NAME,
    SLADE_ID_MAPPING_DOCTYPE_NAME,
)
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
            "name",
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
        defaults = autofill_item_etims_fields(item_group=doc.item_group)

        required_fields = {
            "custom_etims_country_of_origin": "Country of Origin Code",
            "custom_product_type": "Product Type",
            "custom_item_type": "Item Type",
            "custom_packaging_unit": "Packaging Unit Code",
            "custom_unit_of_quantity": "Unit of Quantity Code",
            "custom_item_classification": "Item Classification",
            "custom_taxation_type": "Taxation Type",
        }

        missing_fields = []

        for field, label in required_fields.items():
            if not doc.get(field):
                if defaults.get(field):
                    doc.set(field, defaults.get(field))
                else:
                    missing_fields.append(label)

        if missing_fields:
            frappe.throw(
                _("Please fill in the following required fields: {0}").format(
                    ", ".join(missing_fields)
                )
            )

        if not doc.custom_item_code_etims:
            doc.custom_item_code_etims = generate_custom_item_code_etims(doc)


@frappe.whitelist()
def prevent_item_deletion(doc: Document, method=None) -> None:
    if not frappe.db.exists(SETTINGS_DOCTYPE_NAME, {"is_active": 1}):
        return
    if doc.custom_item_registered == 1:
        frappe.throw(_("Cannot delete registered items"))
    pass


@frappe.whitelist()
def autofill_item_etims_fields(item_group=None, settings_name=None):
    """
    Auto-fill Item eTIMS fields from:
    1. Item Group (priority)
    2. Settings doctype (secondary)
    3. None (fallback)
    """

    FIELD_LIST = [
        "custom_taxation_type",
        "custom_item_classification",
        "custom_etims_country_of_origin",
        "custom_packaging_unit",
        "custom_unit_of_quantity",
        "custom_product_type",
        "custom_item_type",
    ]

    item_group_doc = None
    settings_doc = None

    if item_group:
        item_group_doc = frappe.get_doc("Item Group", item_group)

    if settings_name:
        settings_doc = frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)

    results = {}

    for field in FIELD_LIST:
        value = None

        if item_group_doc and hasattr(item_group_doc, field):
            val = item_group_doc.get(field)
            if val not in ("", None):
                value = val

        if value is None and settings_doc:
            setting_field = field.replace("custom_", "")
            if hasattr(settings_doc, setting_field):
                val = settings_doc.get(setting_field)
                if val not in ("", None):
                    value = val

        results[field] = value

    return results
