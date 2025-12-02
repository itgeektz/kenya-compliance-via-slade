import frappe
import json
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import (
    ScheduledJobType as CoreScheduledJobType,
)


class CustomScheduledJobType(CoreScheduledJobType):
    def autoname(self):
        if hasattr(self, "job_name") and self.job_name:
            self.name = self.job_name
        else:
            self.name = ".".join(self.method.split(".")[-2:])

    def execute(self):
        self.scheduler_log = None
        try:
            if (
                self.next_execution
                and self.next_execution > frappe.utils.now_datetime()
            ):
                return

            self.log_status("Start")
            job_args = {}
            if hasattr(self, "job_args") and self.job_args:
                try:
                    job_args = json.loads(self.job_args)
                except Exception:
                    frappe.log_error(
                        message=f"Invalid job_args: {self.job_args}\n\n{frappe.get_traceback()}",
                        title=f"Invalid job_args for {self.name}",
                    )

            if self.server_script:
                script_name = frappe.db.get_value("Server Script", self.server_script)
                if script_name:
                    frappe.get_doc(
                        "Server Script", script_name
                    ).execute_scheduled_method()
                else:
                    frappe.log_error(
                        message=f"No Server Script found for reference '{self.server_script}'. job_args: {job_args}",
                        title=f"Scheduled Job Type misconfigured: {self.name}",
                    )
            else:
                frappe.get_attr(self.method)(**job_args)

            frappe.db.commit()
            self.log_status("Complete")
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error executing Scheduled Job Type: {self.name}",
            )
            self.log_status("Failed")
