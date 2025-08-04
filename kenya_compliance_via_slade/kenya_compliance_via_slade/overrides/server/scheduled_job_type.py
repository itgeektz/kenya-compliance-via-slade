import frappe
import json
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import ScheduledJobType as CoreScheduledJobType

class CustomScheduledJobType(CoreScheduledJobType):
    def autoname(self):
        if hasattr(self, 'job_name') and self.job_name:
            self.name = self.job_name
        else:
            self.name = ".".join(self.method.split(".")[-2:])

    def execute(self):
        self.scheduler_log = None
        try:
            self.log_status("Start")
            job_args = {}
            if hasattr(self, "job_args") and self.job_args:
                try:
                    job_args = json.loads(self.job_args)
                except Exception:
                    frappe.log_error(f"Invalid job_args for {self.name}: {self.job_args}")

            if self.server_script:
                script_name = frappe.db.get_value("Server Script", self.server_script)
                if script_name:
                    frappe.get_doc("Server Script", script_name).execute_scheduled_method()
            else:
                frappe.log_error(f"Scheduled Job Type {self.name} has no server script or method defined. {job_args}")
                frappe.get_attr(self.method)(**job_args)

            frappe.db.commit()
            self.log_status("Complete")
        except Exception:
            frappe.db.rollback()
            self.log_status("Failed")
