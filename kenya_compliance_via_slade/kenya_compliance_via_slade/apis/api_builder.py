from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal, Optional, Union
from urllib import parse

import frappe
import requests
from frappe.integrations.utils import create_request_log
from frappe.model.document import Document

from ..logger import etims_logger
from ..utils import (
    clean_url_params,
    reset_auth_password,
    update_last_request_date,
    update_navari_settings_with_token,
)
from .remote_response_status_handlers import on_slade_error


class BaseEndpointsBuilder:
    """
    Abstract base class that implements the *observer* pattern for error
    propagation.

    Observers are notified (via :py:meth:`notify`) whenever
    :py:attr:`error` is set and a fatal condition is detected.
    """

    def __init__(self) -> None:
        self._integration_request: str | Document | None = None
        self._error: str | Exception | None = None
        self._observers: list[ErrorObserver] = []
        self._doctype: str | Document | None = None
        self._document_name: str | None = None

    @property
    def integration_request(self) -> str | Document | None:
        """Integration Request document linked to the current request."""
        return self._integration_request

    @integration_request.setter
    def integration_request(self, value: str | Document | None) -> None:
        self._integration_request = value

    @property
    def error(self) -> str | Exception | None:
        """Current error captured during request processing."""
        return self._error

    @error.setter
    def error(self, value: str | Exception | None) -> None:
        self._error = value

    @property
    def doctype(self) -> str | Document | None:
        """Reference doctype associated with the current request."""
        return self._doctype

    @doctype.setter
    def doctype(self, value: str | Document | None) -> None:
        self._doctype = value

    @property
    def document_name(self) -> str | None:
        """Reference document name associated with the current request."""
        return self._document_name

    @document_name.setter
    def document_name(self, value: str | None) -> None:
        self._document_name = value

    def attach(self, observer: "ErrorObserver") -> None:
        """
        Attach an error observer.

        Args:
            observer: An :py:class:`ErrorObserver` instance that will be
                      notified when a fatal error occurs.
        """
        self._observers.append(observer)

    def notify(self) -> None:
        """Notify all attached observers of the current error state."""
        for observer in self._observers:
            observer.update(self)


class ErrorObserver:
    """
    Reacts to fatal errors surfaced by an :py:class:`BaseEndpointsBuilder`.

    On notification it updates the linked ``Integration Request`` to
    ``"Failed"``, logs the error, and raises a hard ``frappe.throw``.
    """

    def update(self, notifier: BaseEndpointsBuilder) -> None:
        """
        Handle a fatal-error notification.

        Args:
            notifier: The builder that encountered the error.
        """
        if not notifier.error:
            return

        _update_integration_request(
            notifier.integration_request.name,
            status="Failed",
            output=None,
            error=notifier.error,
        )
        etims_logger.exception(notifier.error, exc_info=True)
        frappe.log_error(
            title="Fatal Error",
            message=notifier.error,
            reference_doctype=notifier.doctype,
            reference_name=notifier.document_name,
        )
        frappe.throw(
            "A Fatal Error was encountered. Please check the Error Log for details.",
            notifier.error,
            title="Fatal Error",
        )


class EndpointsBuilder(BaseEndpointsBuilder):
    """
    Concrete HTTP client used to communicate with eTims / Slade 360 servers.

    Usage pattern::

        builder = EndpointsBuilder()
        builder.headers = {...}
        builder.url = "https://..."
        builder.method = "POST"
        builder.payload = {...}
        builder.success_callback = my_handler
        builder.settings = settings_doc
        builder.job_queue = job_doc
        builder.doctype = "Sales Invoice"
        builder.document_name = "SI-001"
        response = builder.make_remote_call()

    The builder is typically reused (module-level singleton in ``etims_job_queue.py``)
    with properties reset before each call.
    """

    def __init__(self) -> None:
        super().__init__()

        self._url: str | None = None
        self._route_path: str | None = None
        self._request_description: str | None = None
        self._payload: dict | list | None = None
        self._settings: Document | dict | None = None
        self._headers: dict[str, str] | None = None
        self._method: Literal["GET", "POST", "PATCH", "PUT"] | None = None
        self._success_callback_handler: Callable[..., None] | None = None
        self._error_callback_handler: Callable[..., None] | None = None
        self._job_queue: Document | None = None

        self.attach(ErrorObserver())

    @property
    def method(self) -> Literal["GET", "POST", "PATCH", "PUT"] | None:
        """HTTP method for the next request."""
        return self._method

    @method.setter
    def method(self, value: Literal["GET", "POST", "PATCH", "PUT"]) -> None:
        self._method = value

    @property
    def url(self) -> str | None:
        """Target URL (may include query-string for GET requests)."""
        return self._url

    @url.setter
    def url(self, value: str | None) -> None:
        self._url = value

    @property
    def route_path(self) -> str | None:
        """Relative route path (used for logging and ``update_last_request_date``)."""
        return self._route_path

    @route_path.setter
    def route_path(self, value: str | None) -> None:
        self._route_path = value

    @property
    def request_description(self) -> str | None:
        """Human-readable label for the request (stored on Integration Request)."""
        return self._request_description

    @request_description.setter
    def request_description(self, value: str | None) -> None:
        self._request_description = value

    @property
    def payload(self) -> dict | list | None:
        """Request body / query params dict."""
        return self._payload

    @payload.setter
    def payload(self, value: dict | list | None) -> None:
        self._payload = value

    @property
    def settings(self) -> Document | dict | None:
        """eTims Settings document (or dict) associated with this call."""
        return self._settings

    @settings.setter
    def settings(self, value: Document | dict | None) -> None:
        self._settings = value

    @property
    def headers(self) -> dict[str, str] | None:
        """HTTP headers including ``Authorization``."""
        return self._headers

    @headers.setter
    def headers(self, value: dict[str, str] | None) -> None:
        self._headers = value

    @property
    def success_callback(self) -> Callable[..., None] | None:
        """Callable invoked when the server returns 200/201."""
        return self._success_callback_handler

    @success_callback.setter
    def success_callback(self, value: Callable[..., None] | None) -> None:
        self._success_callback_handler = value

    @property
    def error_callback(self) -> Callable[..., None] | None:
        """Callable invoked on non-2xx responses."""
        return self._error_callback_handler

    @error_callback.setter
    def error_callback(self, value: Callable[..., None] | None) -> None:
        self._error_callback_handler = value

    @property
    def job_queue(self) -> Document | None:
        """Queue document associated with the current request."""
        return self._job_queue

    @job_queue.setter
    def job_queue(self, value: Document | None) -> None:
        self._job_queue = value

    def make_remote_call(
        self,
        retrying: bool = False,
    ) -> dict | str | bytes | None:
        """
        Issue the configured HTTP request and handle the response.

        On success (200/201): invoke ``success_callback``, update the
        Integration Request to ``"Completed"``, and mark the job ``"Success"``.

        On error: update the Integration Request to ``"Failed"``, invoke
        ``error_callback`` (if provided), and mark the job ``"Failed"``. If
        the status code is 401 and this is not already a retry, refresh the
        access token and retry once.

        Args:
            retrying: Internal flag — ``True`` on the single token-refresh
                      retry. Prevents infinite loops.

        Returns:
            The parsed response (dict, str, or bytes) or ``None`` on error.
        """
        self._validate_required_fields()

        if not self.settings.is_active == 1:
            frappe.log_error(
                title="Inactive eTims Settings",
                message=(
                    f"Settings '{self.settings.name}' is inactive. Remote call aborted."
                ),
                reference_doctype=self.doctype,
                reference_name=self.document_name,
            )
            return None

        if not retrying:
            self.integration_request = self._create_integration_log(
                self.doctype,
                self.document_name,
            )

        try:
            response = self._dispatch_http_request()

            response_data = _parse_response(response)

            update_last_request_date(
                datetime.now(),
                self.route_path,
            )

            if response.status_code in {200, 201}:
                self._handle_success(
                    response_data,
                    self.doctype,
                    self.document_name,
                )
            else:
                self._handle_error(
                    response,
                    response_data,
                    self.doctype,
                    self.document_name,
                )

                if response.status_code == 401 and not retrying:
                    self.refresh_token()
                    return self.make_remote_call(retrying=True)

            return response_data

        except Exception as exc:
            frappe.log_error(
                title="eTims — HTTP error",
                message=(
                    f"Error: {exc}\n"
                    f"URL: {self.route_path}\n"
                    f"Traceback:\n{frappe.get_traceback()}"
                ),
                reference_doctype=self.doctype,
                reference_name=self.document_name,
            )

            if self.job_queue:
                self.job_queue.update_status(
                    status="Failed",
                    error_message=str(exc),
                    integration_request=(
                        self.integration_request.name
                        if self.integration_request
                        else None
                    ),
                )

            return None

    def refresh_token(self) -> str | None:
        """
        Obtain a new access token and update ``Authorization`` in the headers.

        Returns:
            The new token string, or ``None`` if the refresh failed.

        Raises:
            frappe.AuthenticationError: If the refresh request fails.
        """
        try:
            settings = update_navari_settings_with_token(self.settings.name)

            if settings:
                new_token = settings.access_token
                self.headers["Authorization"] = f"Bearer {new_token}"
                return new_token

            frappe.throw(
                "Failed to refresh token",
                frappe.AuthenticationError,
            )

        except requests.exceptions.RequestException as exc:
            frappe.throw(
                f"Error refreshing token: {exc}",
                frappe.AuthenticationError,
            )

    def _validate_required_fields(self) -> None:
        """
        Assert that all mandatory builder properties have been set.

        Raises:
            frappe.MandatoryError: If any required field is missing.
        """
        if not all(
            [
                self.url,
                self.headers,
                self.method,
                self.success_callback,
            ]
        ):
            frappe.throw(
                "Please ensure URL, headers, method, and success_callback are set.",
                frappe.MandatoryError,
                title="Setup Error",
                is_minimizable=True,
            )

    def _create_integration_log(
        self,
        doctype: str | None,
        document_name: str | None,
    ) -> Document:
        """
        Create a Frappe ``Integration Request`` log for this call.

        Falls back to a log without ``reference_docname`` if a
        ``LinkValidationError`` is raised.

        Args:
            doctype: Reference doctype.
            document_name: Reference document name.

        Returns:
            The newly created ``Integration Request`` document.
        """
        cleaned_url = clean_url_params(self.url)

        common = dict(
            data=self.payload,
            request_description=self.request_description,
            is_remote_request=True,
            service_name=self.request_description,
            request_headers=self.headers,
            url=cleaned_url,
            reference_doctype=doctype,
        )

        try:
            return create_request_log(
                **common,
                reference_docname=document_name,
            )

        except frappe.LinkValidationError:
            return create_request_log(**common)

    def _dispatch_http_request(self) -> requests.Response:
        """
        Send the HTTP request using the configured method and return the raw
        ``requests.Response``.

        URL query parameters are normalized before dispatch to prevent
        duplicated pagination params.

        Returns:
            requests.Response:
                Raw HTTP response object.
        """
        request_url = (
            self.job_queue.url if self.job_queue and self.job_queue.url else self.url
        )

        if self.method == "GET":
            page_size = (
                self.job_queue.page_size
                if self.job_queue and self.job_queue.page_size
                else 100
            )

            params = {
                **(self.payload or {}),
                "page_size": page_size,
            }

            prepared = requests.Request(
                method="GET",
                url=request_url,
                params=params,
            ).prepare()

            request_url = clean_url_params(prepared.url)

            return requests.get(
                request_url,
                headers=self.headers,
            )

        if self.method == "POST":
            request_url = clean_url_params(request_url)

            return requests.post(
                request_url,
                json=self.payload,
                headers=self.headers,
            )

        if self.method == "PATCH":
            patch_id = self.payload.pop("id", None)

            if patch_id and f"/{patch_id}/" not in request_url:
                request_url = f"{request_url.rstrip('/')}/{patch_id}/"

            request_url = clean_url_params(request_url)

            return requests.patch(
                request_url,
                json=self.payload,
                headers=self.headers,
            )

        if self.method == "PUT":
            put_id = self.payload.pop("id", None)

            if put_id and f"/{put_id}/" not in request_url:
                request_url = f"{request_url.rstrip('/')}/{put_id}/"

            request_url = clean_url_params(request_url)

            return requests.put(
                request_url,
                json=self.payload,
                headers=self.headers,
            )

        frappe.throw(f"Unsupported HTTP method: {self.method}")

    def _handle_success(
        self,
        response_data: dict | str | bytes | None,
        doctype: str | None,
        document_name: str | None,
    ) -> None:
        """
        Handle a 200/201 response.

        * Invokes ``success_callback``.
        * Updates the Integration Request to ``"Completed"``.
        * Marks the job ``"Success"``.

        Args:
            response_data: Parsed response body.
            doctype: Reference doctype.
            document_name: Reference document name.
        """
        frappe.db.set_value(
            "Integration Request",
            self.integration_request.name,
            "status",
            "Completed",
        )

        self.success_callback(
            response=response_data,
            document_name=document_name,
            doctype=doctype,
            payload=self.payload,
            settings_name=self.settings.name,
        )

        current_page = (
            response_data.get("current_page")
            if isinstance(response_data, dict)
            else None
        )

        total_pages = (
            response_data.get("total_pages", 0)
            if isinstance(response_data, dict)
            else 0
        )

        _update_integration_request(
            self.integration_request.name,
            status="Completed",
            output=str(response_data),
            error=None,
            request_description=(
                f"Page {current_page} of {total_pages}"
                if total_pages and int(total_pages) > 1
                else None
            ),
        )

        if self.job_queue:
            self.job_queue.update_status(
                status="Success",
                error_message=None,
                integration_request=self.integration_request.name,
            )

    def _handle_error(
        self,
        response: requests.Response,
        response_data: dict | str | bytes | None,
        doctype: str | None,
        document_name: str | None,
    ) -> None:
        """
        Handle a non-2xx response.

        * Extracts a human-readable error message.
        * Resets auth password on JSON-decode errors.
        * Updates the Integration Request to ``"Failed"``.
        * Calls ``on_slade_error`` and ``error_callback``.
        * Marks the job ``"Failed"``.

        Args:
            response: The raw ``requests.Response``.
            response_data: Parsed response body.
            doctype: Reference doctype.
            document_name: Reference document name.
        """
        parsed_url = parse.urlparse(self.url)

        route_path = f"/{parsed_url.path.split('/')[-1]}"

        if isinstance(response_data, str):
            error = response_data
        elif isinstance(response_data, list):
            error = response_data[0] if response_data else "Unknown error"
        else:
            error = str(response_data)

        if "could not decode json" in error.lower():
            reset_auth_password(self.settings.name)

        _update_integration_request(
            self.integration_request.name,
            status="Failed",
            output=None,
            error=error,
        )

        on_slade_error(
            response_data,
            url=route_path,
            doctype=doctype,
            document_name=document_name,
        )

        if self.job_queue:
            self.job_queue.update_status(
                status="Failed",
                error_message=error,
                integration_request=self.integration_request.name,
            )

        if self.error_callback:
            self.error_callback(
                response=response_data,
                url=route_path,
                doctype=doctype,
                document_name=document_name,
                payload=self.payload,
                settings_name=self.settings.name,
            )


def _parse_response(
    response: requests.Response,
) -> Optional[Union[dict, str, bytes]]:
    """
    Extract the response body in the most appropriate Python type based on the
    ``Content-Type`` header.

    Args:
        response: A ``requests.Response`` object.

    Returns:
        * ``dict`` for JSON responses.
        * ``str`` for plain-text or XML responses.
        * ``bytes`` for binary/octet-stream/PDF/ZIP responses.
        * ``None`` if the body is empty or the content type is unrecognised.
    """
    content_type = response.headers.get("Content-Type", "").lower()

    if "application/json" in content_type:
        return response.json()
    if "text/plain" in content_type or "text/html" in content_type:
        return response.text if response.text.strip() else None
    if "application/xml" in content_type or "text/xml" in content_type:
        return response.text if response.text.strip() else None
    if any(
        ct in content_type
        for ct in ("application/octet-stream", "application/pdf", "application/zip")
    ):
        return response.content
    return None


def _update_integration_request(
    integration_request: str,
    status: Literal["Completed", "Failed"],
    output: str | None = None,
    error: str | None = None,
    request_description: str | None = None,
) -> None:
    """
    Silently update an ``Integration Request`` document without creating a
    version history entry.

    Each field is appended to rather than overwritten so that multiple partial
    updates (e.g. pagination) accumulate a complete audit trail.  All fields
    are capped at 5 000 characters.

    Args:
        integration_request: The ``name`` of the Integration Request document.
        status: New status — either ``"Completed"`` or ``"Failed"``.
        output: Success response text to append, or ``None``.
        error: Error detail to append, or ``None``.
        request_description: Additional description label to append, or ``None``.
    """
    update_fields: dict = {"status": status}

    def _append(field: str, new_value: str, separator: str = "\n") -> None:
        current = frappe.db.get_value("Integration Request", integration_request, field)
        if not current or current == "null":
            update_fields[field] = new_value[:5000]
        elif new_value not in current:
            combined = current + separator + new_value
            update_fields[field] = combined[:5000]

    if error:
        _append("error", error)
    if output:
        _append("output", output)
    if request_description:
        _append("request_description", request_description, " - ")

    frappe.db.set_value(
        "Integration Request",
        integration_request,
        update_fields,
        update_modified=False,
    )
