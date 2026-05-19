from __future__ import annotations

from typing import Callable

import frappe
import frappe.defaults
from frappe.model.document import Document
from frappe.utils import now_datetime

from ...apis.api_builder import EndpointsBuilder
from ...apis.process_request import extract_metadata
from ...doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME
from ...utils import (
    build_headers,
    get_route_path,
    get_server_url,
    get_settings,
    parse_request_data,
    process_dynamic_url,
)

endpoints_builder = EndpointsBuilder()


class eTimsJobQueue(Document):
    def after_insert(self):
        if not self.is_page:
            self.run_queue()

    @frappe.whitelist()
    def run_queue(self):
        try:
            self.update_status("Processing")
            process_job_request(
                request_data=self.request_data,
                route_key=self.route_key,
                handler=self.get_callable(self.handler_function),
                request_method=self.request_method,
                doctype=self.reference_doctype,
                error_handler=self.get_callable(self.error_callback),
                settings_name=self.settings_name,
                company=self.company,
                job_queue=self,
            )
        except Exception:
            error = frappe.get_traceback()
            self.update_status("Failed", error_message=str(error))
            frappe.log_error(
                message=error, title=f"eTims Job Queue Failed: {self.route_key}"
            )
            raise

    def update_status(
        self,
        status: str,
        error_message: str | None = None,
        integration_request: str | None = None,
    ) -> None:
        update_fields = {"status": status}

        if status == "Processing":
            update_fields["last_attempt"] = now_datetime()
        elif status == "Completed":
            update_fields["completion_time"] = now_datetime()
        elif status == "Failed":
            update_fields["last_attempt"] = now_datetime()

        if error_message:
            current = self.error_message or ""
            new = (current + "\n" + error_message).strip() if current else error_message
            update_fields["error_message"] = new[:5000]

        if integration_request:
            update_fields["integration_request"] = integration_request

        self.db_set(update_fields, commit=True)

    def get_callable(self, path: str | None) -> Callable | None:
        if not path:
            return None
        obj = frappe.get_attr(path)
        return obj if callable(obj) else None


def process_job_request(
    request_data: str | dict,
    route_key: str,
    handler: Callable | None,
    request_method: str,
    doctype: str,
    error_handler: Callable | None,
    settings_name: str | None,
    company: str | None,
    job_queue: Document | None,
):
    if not settings_name and not frappe.db.exists(
        SETTINGS_DOCTYPE_NAME, {"is_active": 1}
    ):
        return

    data = parse_request_data(request_data)
    company_name, branch_id, document_name = extract_metadata(data)
    company_name = (
        company
        or company_name
        or frappe.defaults.get_user_default("Company")
        or frappe.get_value("Company", {}, "name")
    )

    headers = build_headers(company_name, branch_id, settings_name)
    server_url = get_server_url(company_name, branch_id, settings_name)
    route_path, _ = get_route_path(route_key, "VSCU Slade 360")

    url = (
        job_queue.url
        if job_queue and job_queue.url
        else f"{server_url}{process_dynamic_url(route_path, request_data)}"
    )

    if job_queue and not job_queue.url:
        job_queue.db_set("url", url, commit=True)

    if job_queue and document_name and not job_queue.reference_docname:
        job_queue.db_set("reference_docname", document_name, commit=True)

    settings = get_settings(company_name, branch_id, settings_name)

    if not settings or settings.get("is_active") != 1:
        return
    if not headers or not server_url or not route_path:
        return

    return execute_remote_request(
        headers=headers,
        url=url,
        route_path=route_path,
        data=data,
        route_key=route_key,
        handler=handler,
        error_handler=error_handler,
        request_method=request_method,
        doctype=doctype,
        document_name=document_name,
        settings=settings,
        job_queue=job_queue,
    )


def execute_remote_request(
    headers: dict,
    url: str,
    route_path: str,
    data: dict,
    route_key: str,
    handler: Callable | None,
    error_handler: Callable | None,
    request_method: str,
    doctype: str,
    document_name: str,
    settings: dict,
    job_queue: Document | None,
):
    endpoints_builder.headers = headers
    endpoints_builder.url = url
    endpoints_builder.route_path = route_path
    endpoints_builder.payload = data
    endpoints_builder.request_description = route_key
    endpoints_builder.method = request_method
    endpoints_builder.success_callback = handler
    endpoints_builder.error_callback = error_handler
    endpoints_builder.settings = settings
    endpoints_builder.job_queue = job_queue

    response = endpoints_builder.make_remote_call(
        doctype=doctype,
        document_name=document_name,
    )

    if (
        not (job_queue and job_queue.is_page)
        and isinstance(response, dict)
        and response.get("next")
    ):
        total_pages = response.get("total_pages", 1)
        current_page = response.get("current_page", 1)

        base_url = response.get("next").split("?")[0]
        page_size = job_queue.page_size if job_queue else 100

        for page_no in range(current_page + 1, total_pages + 1):
            next_page_url = f"{base_url}?page={page_no}&page_size={page_size}"

            frappe.get_doc(
                {
                    "doctype": "eTims Job Queue",
                    "route_key": route_key,
                    "request_data": data,
                    "handler_function": job_queue.handler_function
                    if job_queue
                    else None,
                    "error_callback": job_queue.error_callback if job_queue else None,
                    "request_method": request_method,
                    "reference_doctype": doctype,
                    "reference_docname": document_name,
                    "settings_name": settings.get("name"),
                    "company": job_queue.company if job_queue else None,
                    "status": "Pending",
                    "is_page": 1,
                    "page_size": page_size,
                    "url": next_page_url,
                }
            ).insert(ignore_permissions=True)

        if job_queue:
            job_queue.update_status(status="Completed")

    return response
