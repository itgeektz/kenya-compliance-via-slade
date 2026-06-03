from __future__ import annotations

from typing import Callable

import frappe
import frappe.defaults
from csf_ke.etims.doctype.etims_job_queue.etims_job_queue import eTimsJobQueue
from frappe.model.document import Document

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


class CustomETimsJobQueue(eTimsJobQueue):
    @frappe.whitelist()
    def run_queue(self) -> None:
        """
        Execute this job by making the configured remote HTTP call.

        Steps
        -----
        1. Set status to ``"Processing"``.
        2. Delegate to :py:func:`process_job_request` which calls the remote
           API via ``EndpointsBuilder``.
        3. On unhandled exception: mark ``"Failed"``, log the traceback, and
           re-raise so the manager's ``_execute_current_job`` can clean up.

        Note: The actual ``"Success"`` / ``"Failed"`` status update (and the
        subsequent ``advance_queue`` call) is made by
        :py:meth:`update_status`, which is called by ``EndpointsBuilder``
        after the HTTP response is received.
        """
        try:
            self.update_status("Processing")
            process_job_request(
                request_data=self.request_data,
                route_key=self.route_key,
                handler=self._resolve_callable(self.handler_function),
                request_method=self.request_method,
                doctype=self.reference_doctype,
                document_name=self.reference_docname,
                error_handler=self._resolve_callable(self.error_callback),
                settings_name=self.settings_name,
                company=self.company,
                job_queue=self,
            )
        except Exception:
            error = frappe.get_traceback()
            self.update_status("Failed", error_message=str(error))
            frappe.log_error(
                message=error,
                title=f"eTims Job Queue — run_queue failed: {self.route_key}",
            )
            raise


def process_job_request(
    request_data: str | dict,
    route_key: str,
    handler: Callable | None,
    request_method: str,
    doctype: str,
    document_name: str,
    error_handler: Callable | None,
    settings_name: str | None,
    company: str | None,
    job_queue: Document | None,
) -> None:
    """
    Resolve all connection details and delegate to
    :py:func:`execute_remote_request`.

    This function is the single point that translates a job document into a
    concrete HTTP call.  It resolves company, branch, headers, server URL, and
    route path before handing off to the builder.

    Args:
        request_data: Raw JSON string or dict payload for the request.
        route_key: Key used to look up the endpoint path in the route table.
        handler: Success callback function.
        request_method: HTTP method (``"GET"``, ``"POST"``, ``"PATCH"``,
                        ``"PUT"``).
        doctype: Reference doctype name for the triggering document.
        document_name: Name of the document triggering the job.
        error_handler: Error callback function, or ``None``.
        settings_name: Explicit eTims Settings document name, or ``None`` to
                       use the active default.
        company: Explicit company name override, or ``None``.
        job_queue: The ``eTimsJobQueue`` document driving this call.
    """
    if not settings_name and not frappe.db.exists(
        SETTINGS_DOCTYPE_NAME, {"is_active": 1}
    ):
        return

    data = parse_request_data(request_data)
    company_name, branch_id, doc_name = extract_metadata(data)

    company_name = (
        company
        or company_name
        or frappe.defaults.get_user_default("Company")
        or frappe.get_value("Company", {}, "name")
    )

    headers = build_headers(company_name, branch_id, settings_name)
    server_url = get_server_url(company_name, branch_id, settings_name)
    route_path, _ = get_route_path(route_key, "VSCU Slade 360")

    if job_queue and job_queue.url:
        url = job_queue.url
    else:
        url = f"{server_url}{process_dynamic_url(route_path, request_data)}"

    if job_queue and not job_queue.url:
        job_queue.db_set("url", url, commit=True)

    if job_queue and document_name and not job_queue.reference_docname:
        job_queue.db_set("reference_docname", document_name, commit=True)

    settings = get_settings(company_name, branch_id, settings_name)

    if not settings or settings.get("is_active") != 1:
        return
    if not headers or not server_url or not route_path:
        return

    execute_remote_request(
        headers=headers,
        url=url,
        route_path=route_path,
        data=data,
        route_key=route_key,
        handler=handler,
        error_handler=error_handler,
        request_method=request_method,
        doctype=doctype,
        document_name=document_name or doc_name,
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
) -> None:
    """
    Configure ``EndpointsBuilder`` and issue the remote HTTP call.

    After the call returns, check whether the response contains a ``next``
    field indicating additional pages.  If so, ask the job to enqueue a
    follow-up job for the next page.

    Args:
        headers: HTTP request headers (including ``Authorization``).
        url: Fully-resolved target URL.
        route_path: Relative path portion of the URL (used for logging).
        data: Parsed request payload dict.
        route_key: Identifier for the route / endpoint.
        handler: Success callback.
        error_handler: Error callback, or ``None``.
        request_method: HTTP method string.
        doctype: Reference doctype.
        document_name: Reference document name.
        settings: eTims Settings dict.
        job_queue: The driving ``eTimsJobQueue`` document, or ``None``.
    """
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
    endpoints_builder.doctype = doctype
    endpoints_builder.document_name = document_name

    response = endpoints_builder.make_remote_call()

    if job_queue and isinstance(response, dict) and response.get("next"):
        next_url: str = response["next"]
        job_queue.enqueue_next_page(next_url)

    frappe.db.commit()
