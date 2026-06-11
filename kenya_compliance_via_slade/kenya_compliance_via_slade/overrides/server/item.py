import frappe
import frappe.defaults
from frappe import _
from frappe.model.document import Document

from ...apis.apis import perform_item_registration
from ...doctype.doctype_names_mapping import (
    SETTINGS_DOCTYPE_NAME,
    SLADE_ID_MAPPING_DOCTYPE_NAME,
)
from ...utils import get_active_settings


def on_update(doc: Document, method: str = None) -> None:
    """Item doctype before insertion hook"""
    active_settings = get_active_settings()

    if not active_settings:
        return

    for setting in active_settings:
        setup_mapping = frappe.db.get_value(
            SLADE_ID_MAPPING_DOCTYPE_NAME,
            {"parent": doc.name, "setup_docname": setting.name},
            "name",
        )

        if not setup_mapping:
            perform_item_registration(doc.name, setting.name)


def validate(doc: Document, method: str = None) -> None:
    is_tax_type_changed = doc.has_value_changed("etims_taxation_type")
    if doc.etims_taxation_type and is_tax_type_changed:
        relevant_tax_templates = frappe.get_all(
            "Item Tax Template",
            ["*"],
            {"etims_taxation_type": doc.etims_taxation_type},
        )

        if relevant_tax_templates:
            doc.set("taxes", [])
            for template in relevant_tax_templates:
                doc.append("taxes", {"item_tax_template": template.name})

    if doc.etims_prevent_etims_registration != 1:
        defaults = autofill_item_etims_fields(item_group=doc.item_group)

        required_fields = {
            "etims_country_of_origin": "Country of Origin Code",
            "etims_product_type": "Product Type",
            "etims_item_type": "Item Type",
            "etims_packaging_unit": "Packaging Unit Code",
            "etims_unit_of_quantity": "Unit of Quantity Code",
            "etims_item_classification": "Item Classification",
            "etims_taxation_type": "Taxation Type",
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


@frappe.whitelist()
def prevent_item_deletion(doc: Document, method=None) -> None:
    if not frappe.db.exists(SETTINGS_DOCTYPE_NAME, {"is_active": 1}):
        return
    if len(doc.etims_id_mapping) > 0:
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
        "etims_taxation_type",
        "etims_item_classification",
        "etims_country_of_origin",
        "etims_packaging_unit",
        "etims_unit_of_quantity",
        "etims_product_type",
        "etims_item_type",
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
            setting_field = field
            if hasattr(settings_doc, setting_field):
                val = settings_doc.get(setting_field)
                if val not in ("", None):
                    value = val

        results[field] = value

    return results
