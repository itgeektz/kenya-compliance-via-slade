from typing import Optional
import json
import frappe
from frappe.model.document import Document

from ...background_tasks.tasks import (
    refresh_notices,
    search_organisations_request,
    send_purchase_information,
    send_sales_invoices_information,
    send_stock_information,
)
from ...utils import user_details_fetch, reset_auth_password, update_navari_settings_with_token
from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME, ORGANISATION_MAPPING_DOCTYPE_NAME

class NavariKRAeTimsSettings(Document):
    """ETims Integration Settings doctype"""

    def after_insert(self) -> None:
        if self.is_active == 1:
            request_data = {
                "branch_id": self.bhfid,
                "company_name": self.company,
                "document_name": self.name,
            }
            search_organisations_request(request_data, self.name)
            user_details_fetch(self.name)

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
        def get_or_create_scheduled_job(
            method_name: str, frequency: str, cron_format: Optional[str] = None
        ) -> None:
            task: Optional[str] = frappe.db.exists(
                "Scheduled Job Type", {"method": ["like", f"%{method_name}%"]}
            )

            if task:
                task = frappe.get_doc("Scheduled Job Type", task)
            else:
                task = frappe.new_doc("Scheduled Job Type")
                task.method = method_name

            task.frequency = frequency

            if frequency == "Cron" and cron_format:
                task.cron_format = cron_format

            task.save(ignore_permissions=True)

        if self.sales_information_submission:
            get_or_create_scheduled_job(
                f"{send_sales_invoices_information.__module__}.{send_sales_invoices_information.__name__}",
                self.sales_information_submission,
                (
                    self.sales_info_cron_format
                    if self.sales_information_submission == "Cron"
                    else None
                ),
            )

        if self.stock_information_submission:
            get_or_create_scheduled_job(
                f"{send_stock_information.__module__}.{send_stock_information.__name__}",
                self.stock_information_submission,
                (
                    self.stock_info_cron_format
                    if self.stock_information_submission == "Cron"
                    else None
                ),
            )

        if self.purchase_information_submission:
            get_or_create_scheduled_job(
                f"{send_purchase_information.__module__}.{send_purchase_information.__name__}",
                self.purchase_information_submission,
                (
                    self.purchase_info_cron_format
                    if self.purchase_information_submission == "Cron"
                    else None
                ),
            )

        if self.notices_refresh_frequency:
            get_or_create_scheduled_job(
                f"{refresh_notices.__module__}.{refresh_notices.__name__}",
                self.notices_refresh_frequency,
                (
                    self.notices_refresh_freq_cron_format
                    if self.notices_refresh_frequency == "Cron"
                    else None
                ),
            )
            
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
