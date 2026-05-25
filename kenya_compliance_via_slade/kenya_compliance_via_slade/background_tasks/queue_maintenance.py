from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from ..doctype.doctype_names_mapping import QUEUE_DOCTYPE

QUEUE_TIMEOUT_MINUTES = 5
QUEUE_RETENTION_HOURS = 1


def run_etims_queue_maintenance() -> None:
    """
    Scheduled maintenance task for eTims queue management.

    Runs every 5 minutes and performs:

        1. Detect stale Processing jobs
        2. Ensure only latest Processing job remains active
        3. Mark orphaned/expired jobs as Failed
        4. Cleanup completed/failed jobs older than 1 hour
        5. Re-trigger queue manager if necessary

    This protects against:
        - worker crashes
        - stuck jobs
        - duplicated processing states
        - infinite running queues
        - database bloat
    """
    mark_stale_jobs_as_failed()

    cleanup_old_jobs()

    frappe.get_single("eTims Queue Manager").trigger_queue()


def mark_stale_jobs_as_failed() -> None:
    """
    Validates all currently Processing queue jobs.

    Rules:
        - Only ONE Processing job may exist
        - Latest Processing job is preserved
        - Older Processing jobs are failed immediately
        - If linked Integration Request is older than timeout,
          the queue job is marked Failed

    Failure conditions:
        - Missing Integration Request
        - Integration Request older than timeout threshold
        - Multiple Processing jobs detected
    """

    processing_jobs = frappe.get_all(
        QUEUE_DOCTYPE,
        filters={
            "status": "Processing",
        },
        fields=[
            "name",
            "integration_request",
            "creation",
            "modified",
        ],
        order_by="creation desc",
    )

    if not processing_jobs:
        return

    now = now_datetime()

    timeout_threshold = now - timedelta(minutes=QUEUE_TIMEOUT_MINUTES)

    for index, job in enumerate(processing_jobs):
        should_fail = False

        failure_reason = None

        if index > 0:
            should_fail = True
            failure_reason = (
                "Queue maintenance detected multiple "
                "Processing jobs. Older job invalidated."
            )

        elif not job.integration_request:
            should_fail = True
            failure_reason = "Queue job missing Integration Request."

        else:
            integration_creation = frappe.db.get_value(
                "Integration Request",
                job.integration_request,
                "creation",
            )

            if not integration_creation:
                should_fail = True
                failure_reason = "Linked Integration Request does not exist."

            elif integration_creation < timeout_threshold:
                should_fail = True
                failure_reason = (
                    f"Queue job exceeded {QUEUE_TIMEOUT_MINUTES} minute timeout."
                )

        if should_fail:
            fail_queue_job(
                job.name,
                failure_reason,
            )

    manager = frappe.get_single("eTims Queue Manager")

    remaining_processing = frappe.get_all(
        QUEUE_DOCTYPE,
        filters={
            "status": "Processing",
        },
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )

    manager.db_set(
        "current_job",
        remaining_processing[0].name if remaining_processing else None,
        update_modified=False,
    )


def fail_queue_job(
    queue_name: str,
    reason: str,
) -> None:
    """
    Marks a queue job as Failed safely.

    Args:
        queue_name (str):
            Queue document name.

        reason (str):
            Failure explanation appended to error_message.
    """

    queue_doc = frappe.get_doc(
        QUEUE_DOCTYPE,
        queue_name,
    )

    current_error = queue_doc.error_message or ""

    error_message = f"{current_error}\n{reason}".strip() if current_error else reason

    queue_doc.db_set(
        {
            "status": "Failed",
            "completion_time": now_datetime(),
            "error_message": error_message[:5000],
        },
        update_modified=False,
    )

    frappe.log_error(
        title=f"eTims Queue Maintenance :: {queue_name}",
        message=reason,
    )


def cleanup_old_jobs() -> None:
    """
    Deletes old completed or failed queue jobs.

    Cleanup rules:
        - status in Completed / Failed / Success
        - completion_time older than retention threshold

    This prevents long-term database growth.
    """

    cutoff = now_datetime() - timedelta(hours=QUEUE_RETENTION_HOURS)

    old_jobs = frappe.get_all(
        QUEUE_DOCTYPE,
        filters={
            "status": [
                "in",
                [
                    "Completed",
                    "Failed",
                    "Success",
                ],
            ],
            "completion_time": ["<", cutoff],
        },
        pluck="name",
    )

    for job_name in old_jobs:
        try:
            frappe.delete_doc(
                QUEUE_DOCTYPE,
                job_name,
                ignore_permissions=True,
                force=True,
            )

        except Exception:
            frappe.log_error(
                title=f"Failed deleting queue job {job_name}",
                message=frappe.get_traceback(),
            )

    frappe.db.commit()
