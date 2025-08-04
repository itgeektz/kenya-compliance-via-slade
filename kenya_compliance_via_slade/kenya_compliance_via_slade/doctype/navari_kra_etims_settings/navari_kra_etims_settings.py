from typing import Optional
import json
import frappe
from frappe.model.document import Document

from ...background_tasks.tasks import (
    get_item_classification_codes,
    refresh_code_lists,
    refresh_notices,
    send_purchase_information,
    send_sales_invoices_information,
    send_stock_information,
)
from ...utils import reset_auth_password, update_navari_settings_with_token
from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME, ORGANISATION_MAPPING_DOCTYPE_NAME

class NavariKRAeTimsSettings(Document):
    """ETims Integration Settings doctype"""
    def validate(self) -> None:
        if self.is_active == 1:
            seen_pairs = set()
            for row in self.get("organisation_mapping") or []:
                if row.is_active != 1:
                    continue
                pair = (row.company, row.branch)
                if pair in seen_pairs:
                    frappe.throw(
                        f"Duplicate active mapping for company '{row.company}' and branch '{row.branch}' "
                        f"in the same eTims Settings document. Only one active mapping is allowed per company + branch."
                    )
                seen_pairs.add(pair)
                existing = frappe.get_all(
                    ORGANISATION_MAPPING_DOCTYPE_NAME,
                    filters={
                        "company": row.company,
                        "branch": row.branch,
                        "is_active": 1,
                        "parenttype": SETTINGS_DOCTYPE_NAME,
                        "parent": ["!=", self.name],
                    },
                    fields=["parent"],
                    limit=1,
                    order_by=None,
                )
                if existing:
                    parent_doc = frappe.get_value(SETTINGS_DOCTYPE_NAME, existing[0].parent, "is_active")
                    if parent_doc:
                        frappe.throw(
                            f"Active mapping for company '{row.company}' and branch '{row.branch}' "
                            f"already exists in another active eTims Settings ({existing[0].parent}). "
                            "Only one active mapping is allowed per company + branch across all active settings."
                        )

    def on_update(self) -> None:
        def get_or_create_scheduled_job(name: str, method: str, freq: Optional[str], cron: Optional[str], job_args: dict) -> None:
            task_name = frappe.db.exists("Scheduled Job Type", {"job_name": name})
            if task_name:
                task = frappe.get_doc("Scheduled Job Type", task_name)
            else:
                task = frappe.new_doc("Scheduled Job Type")
                task.job_name = name
                task.name = name

            task.method = method
            task.frequency = freq or task.frequency
            if freq == "Cron" and cron:
                task.cron_format = cron
            task.stopped = 0 
            task.job_args = frappe.as_json(job_args)
            task.save(ignore_permissions=True)
            task.enqueue()

        def disable_scheduled_job(name: str) -> None:
            task_name = frappe.db.exists("Scheduled Job Type", name)
            if task_name:
                task = frappe.get_doc("Scheduled Job Type", task_name)
                task.stopped = 1
                task.save(ignore_permissions=True)

        task_configs = [
            {
                "enabled": self.sales_auto_submission_enabled == 1,
                "name": f"{self.name}-send_sales_invoices_information",
                "method": f"{send_sales_invoices_information.__module__}.{send_sales_invoices_information.__name__}",
                "frequency": self.sales_information_submission,
                "cron": self.sales_info_cron_format,
            },
            {
                "enabled": self.stock_auto_submission_enabled == 1,
                "name": f"{self.name}-send_stock_information",
                "method": f"{send_stock_information.__module__}.{send_stock_information.__name__}",
                "frequency": self.stock_information_submission,
                "cron": self.stock_info_cron_format,
            },
            {
                "enabled": self.purchase_auto_submission_enabled == 1,
                "name": f"{self.name}-send_purchase_information",
                "method": f"{send_purchase_information.__module__}.{send_purchase_information.__name__}",
                "frequency": self.purchase_information_submission,
                "cron": self.purchase_info_cron_format,
            },
            {
                "enabled": bool(self.notices_refresh_frequency),
                "name": f"{self.name}-refresh_notices",
                "method": f"{refresh_notices.__module__}.{refresh_notices.__name__}",
                "frequency": self.notices_refresh_frequency,
                "cron": self.notices_refresh_freq_cron_format,
            },
            {
                "enabled": bool(self.codes_refresh_frequency),
                "name": f"{self.name}-refresh_code_lists",
                "method": f"{refresh_code_lists.__module__}.{refresh_code_lists.__name__}",
                "frequency": self.codes_refresh_frequency,
                "cron": self.codes_refresh_freq_cron_format,
                "with_request_data": True,
            },
            {
                "enabled": bool(self.codes_refresh_frequency),
                "name": f"{self.name}-get_item_classification_codes",
                "method": f"{get_item_classification_codes.__module__}.{get_item_classification_codes.__name__}",
                "frequency": self.codes_refresh_frequency,
                "cron": self.codes_refresh_freq_cron_format,
                "with_request_data": True,
            },
        ]

        for config in task_configs:
            job_args = {"settings_name": self.name}
            if config.get("with_request_data"):
                job_args["request_data"] = {}
            if config["enabled"]:
                get_or_create_scheduled_job(config["name"], config["method"], config["frequency"], config["cron"], job_args)
            else:
                disable_scheduled_job(config["name"])

            
    def update_password(self) -> None:
        """Update the password for the settings document."""
        reset_auth_password(self.name)
        
    def update_token(self) -> None:
        """Update the password for the settings document."""
        update_navari_settings_with_token(self.name, True)
    
    
@frappe.whitelist()
def update_companies_with_cluster_info(matched_data, settings_name):
    """Update company documents with cluster information using setup_mapping table"""
    try:
        if isinstance(matched_data, str):
            matched_data = json.loads(matched_data)
        
        for match in matched_data:
            if not isinstance(match, dict) or not match.get("company") or not match.get("cluster_id"):
                continue
            
            company_name = match["company"]
            if not frappe.db.exists("Company", company_name):
                continue
                
            company = frappe.get_doc("Company", company_name)
            
            existing_mapping = None
            duplicate_mappings = []
            
            for mapping in company.setup_mapping:
                if mapping.etims_setup == settings_name:
                    if existing_mapping:
                        duplicate_mappings.append(mapping)
                    else:
                        existing_mapping = mapping
            for duplicate in duplicate_mappings:
                company.setup_mapping.remove(duplicate)
            
            if existing_mapping:
                existing_mapping.organisation = match.get("organisation", "")
                existing_mapping.cluster = match["cluster_id"]
                existing_mapping.is_active = 1
            else:
                company.append("setup_mapping", {
                    "etims_setup": settings_name,
                    "organisation": match.get("organisation", ""),
                    "cluster": match["cluster_id"],
                    "is_active": 1,
                })
            
            company.save(ignore_permissions=True)
                
        frappe.db.commit()
        return {"success": True, "message": "Companies updated successfully"}
    except Exception as e:
        frappe.log_error(f"Company update failed: {str(e)}")
        return {"success": False, "message": str(e)}
