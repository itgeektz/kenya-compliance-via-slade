import frappe
from ..doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME, SLADE_ID_MAPPING_DOCTYPE_NAME
from ..background_tasks.tasks import (
    get_item_classification_codes,
    refresh_code_lists,
    search_clusters,
    search_organisations_request,
)
from ..doctype.navari_kra_etims_settings.navari_kra_etims_settings import (
    update_companies_with_cluster_info,
)


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
        update_entities(setup, "Item", "custom_sent_to_slade", "custom_slade_id")
        update_entities(setup, "Customer", "custom_details_submitted_successfully", "slade_id")
        update_entities(setup, "Supplier", "custom_details_submitted_successfully", "slade_id")
        refresh_code_lists({}, setup.name)
        get_item_classification_codes({}, setup.name)
        cluster = search_clusters({}, setup.name)[0]
        cluster_data = {
            "cluster_id": cluster.get("cluster_id"),
            "cluster_name": cluster.get("cluster_name"),
            "organisation": cluster.get("organisation"),
            "company": setup.company,
        }
        update_companies_with_cluster_info(cluster_data, setup.name)
        search_organisations_request({}, setup.name)
        frappe.db.commit()
        

def update_entities(setup, doctype, filter_field, id_field):
    registered_entities = frappe.get_all(
        doctype,
        filters={filter_field: 1},
        fields=["name", id_field]
    )

    for entity in registered_entities:
        mapping_exists = frappe.db.exists(
            SLADE_ID_MAPPING_DOCTYPE_NAME,
            {
                "parent": entity.name,
                "parenttype": doctype,
                "etims_setup": setup.name
            }
        )

        if mapping_exists:
            frappe.db.set_value(
                SLADE_ID_MAPPING_DOCTYPE_NAME,
                mapping_exists,
                {
                    "slade360_id": entity.get(id_field),
                    "is_active": 1
                }
            )
        else:
            new_mapping = {
                "doctype": SLADE_ID_MAPPING_DOCTYPE_NAME,
                "parent": entity.name,
                "parenttype": doctype,
                "parentfield": "etims_setup_mapping",
                "slade360_id": entity.get(id_field),
                "etims_setup": setup.name,
                "is_active": 1
            }
            frappe.get_doc(new_mapping).insert(ignore_permissions=True, ignore_mandatory=True)

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
