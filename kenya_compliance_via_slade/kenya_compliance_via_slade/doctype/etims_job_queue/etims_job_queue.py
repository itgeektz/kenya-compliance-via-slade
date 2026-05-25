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
    clean_url_params,
    get_route_path,
    get_server_url,
    get_settings,
    parse_request_data,
    process_dynamic_url,
)

endpoints_builder = EndpointsBuilder()


class eTimsJobQueue(Document):
    def validate(self) -> None:
        if self.url:
            self.url = clean_url_params(self.url)

    def after_insert(self) -> None:
        """
        Notify the queue manager that a new job has arrived.

        The manager will start processing immediately if the queue is idle, or
        simply record the job as pending if another job is already running.
        """
        frappe.get_single("eTims Queue Manager").on_new_job()

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

    def update_status(
        self,
        status: str,
        error_message: str | None = None,
        integration_request: str | None = None,
    ) -> None:
        """
        Persist a new status on this job document and, when the job reaches a
        terminal state, advance the queue manager to the next pending job.

        Args:
            status: One of ``"Pending"``, ``"Processing"``, ``"Success"``,
                    ``"Failed"``.
            error_message: Optional error detail to append to ``error_message``
                           field (max 5 000 chars, cumulative).
            integration_request: Optional name of an ``Integration Request``
                                  document to link.
        """
        update_fields: dict = {"status": status}

        if status == "Processing":
            update_fields["last_attempt"] = now_datetime()
        elif status in ("Success", "Failed"):
            update_fields["completion_time"] = now_datetime()
            if status == "Failed":
                update_fields["last_attempt"] = now_datetime()

        if error_message:
            existing = self.error_message or ""
            combined = (
                (f"{existing}\n{error_message}").strip() if existing else error_message
            )
            update_fields["error_message"] = combined[:5000]

        if integration_request:
            update_fields["integration_request"] = integration_request

        self.db_set(update_fields, commit=True)

        if status in ("Success", "Failed"):
            frappe.get_single("eTims Queue Manager").advance_queue()

    def enqueue_next_page(self, next_url: str) -> None:
        """
        Schedule the creation of a follow-up job for the next pagination page.

        The new job inherits all configuration from this job but targets the
        URL returned in the ``next`` field of the API response.  Insertion is
        deferred to a background job (``enqueue_after_commit=True``) so the
        current transaction is fully committed before the manager sees the new
        entry.

        Args:
            next_url: The full URL for the next page as returned by the remote
                      API (e.g. ``"https://api.example.com/items/?page=2"``).
        """
        job_data = {
            "route_key": self.route_key,
            "request_data": self.request_data,
            "handler_function": self.handler_function,
            "error_callback": self.error_callback,
            "request_method": self.request_method,
            "reference_doctype": self.reference_doctype,
            "reference_docname": self.reference_docname,
            "settings_name": self.settings_name,
            "company": self.company,
            "status": "Pending",
            "is_page": 1,
            "page_size": self.page_size or 100,
            "url": next_url,
        }
        frappe.enqueue(
            _bg_insert_next_page_job,
            job_data=job_data,
            queue="default",
            is_async=True,
            enqueue_after_commit=True,
        )

    def _resolve_callable(self, path: str | None) -> Callable | None:
        """
        Resolve a dotted-path string to a Python callable.

        Args:
            path: Dotted module path such as
                  ``"myapp.handlers.on_invoice_success"``, or ``None``.

        Returns:
            The callable object, or ``None`` if *path* is falsy or does not
            resolve to a callable.
        """
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

    response = endpoints_builder.make_remote_call(
        doctype=doctype,
        document_name=document_name,
    )

    if job_queue and isinstance(response, dict) and response.get("next"):
        next_url: str = response["next"]
        job_queue.enqueue_next_page(next_url)


def _bg_insert_next_page_job(job_data: dict) -> None:
    """
    Background-job entry point that inserts a new ``eTims Job Queue`` document
    for the next pagination page.

    Deferring the insert to a background job ensures the current transaction
    is committed before a new job is enqueued, preventing the manager from
    seeing a half-committed state.

    Args:
        job_data: Dict containing all fields required to create the new job
                  document (mirrors the ``eTims Job Queue`` doctype fields).
    """
    frappe.get_doc({"doctype": "eTims Job Queue", **job_data}).insert(
        ignore_permissions=True
    )
    frappe.db.commit()
