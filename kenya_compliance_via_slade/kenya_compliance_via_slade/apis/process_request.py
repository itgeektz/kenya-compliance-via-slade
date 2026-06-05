from typing import Callable

import frappe
import frappe.defaults
from frappe.model.document import Document

from ..apis.api_builder import EndpointsBuilder
from ..doctype.doctype_names_mapping import (
    SETTINGS_DOCTYPE_NAME,
)
from ..utils import (
    build_headers,
    get_route_path,
    get_server_url,
    get_settings,
    parse_request_data,
    process_dynamic_url,
)

endpoints_builder = EndpointsBuilder()


def process_request(
    request_data: str | dict,
    route_key: str,
    handler_function: Callable,
    request_method: str = "GET",
    doctype: str = SETTINGS_DOCTYPE_NAME,
    document_name: str = None,
    error_callback: Callable = None,
    settings_name: str = None,
    company: str = None,
    queue: bool = True,
) -> str | None:
    """Create eTims Job Queue entry only. No execution is performed."""

    try:
        if not settings_name and not frappe.db.exists(
            SETTINGS_DOCTYPE_NAME, {"is_active": 1}
        ):
            return

        data = parse_request_data(request_data)

        extracted_company, branch_id, doc_name = extract_metadata(data)
        document_name = document_name or doc_name

        company_name = (
            company
            or extracted_company
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        server_url = get_server_url(company_name, branch_id, settings_name)
        route_path, _ = get_route_path(route_key, "VSCU Slade 360")
        dynamic_route_path = process_dynamic_url(route_path, request_data)
        url = f"{server_url}{dynamic_route_path}"

        settings = get_settings(company_name, branch_id, settings_name)

        if not settings or settings.get("is_active") != 1:
            return

        if queue:
            queue_doc = frappe.get_doc(
                {
                    "doctype": "eTims Job Queue",
                    "route_key": route_key,
                    "handler_function": (
                        f"{handler_function.__module__}.{handler_function.__name__}"
                        if handler_function
                        else None
                    ),
                    "request_method": request_method,
                    "status": "Pending",
                    "reference_doctype": doctype,
                    "reference_docname": document_name
                    if document_name and doctype
                    else None,
                    "company": company_name,
                    "settings_name": settings_name or settings.name,
                    "request_data": data,
                    "retry_count": 0,
                    "error_callback": (
                        f"{error_callback.__module__}.{error_callback.__name__}"
                        if error_callback
                        else None
                    ),
                    "url": url,
                }
            )

            queue_doc.insert(ignore_permissions=True)

            frappe.db.commit()

            return queue_doc.name

        else:
            headers = build_headers(company_name, branch_id, settings_name)
            if headers and server_url and route_path:
                return execute_remote_request(
                    headers=headers,
                    url=url,
                    route_path=route_path,
                    data=data,
                    route_key=route_key,
                    handler=handler_function,
                    error_handler=error_callback,
                    request_method=request_method,
                    doctype=doctype,
                    document_name=document_name,
                    settings=settings,
                    job_queue=None,
                )

    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(), title="Error processing request"
        )
        raise


def extract_metadata(data: dict) -> tuple:
    if isinstance(data, list) and data:
        first_entry = data[0]

        company_name = (
            first_entry.get("company")
            or first_entry.get("company_name")
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        branch_id = (
            first_entry.get("branch_id")
            or frappe.defaults.get_user_default("Branch")
            or frappe.get_value("Branch", "name")
        )

        document_name = first_entry.get("document_name", None)

    else:
        company_name = (
            data.pop("company", None)
            or data.pop("company_name", None)
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        branch_id = (
            data.pop("branch_id", None)
            or frappe.defaults.get_user_default("Branch")
            or frappe.get_value("Branch", "name")
        )

        document_name = data.pop("document_name", None)

    return company_name, branch_id, document_name


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
    return response
