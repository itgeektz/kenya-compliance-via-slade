from typing import Any, Dict, List, Optional, Tuple

from pypika.functions import Avg, Max, Min

import frappe
from frappe.query_builder import DocType
from frappe.utils import flt


def execute(
    filters: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
    return IntegrationRequestTimeAnalysis(filters).run()


class IntegrationRequestTimeAnalysis:
    def __init__(self, filters: Optional[Dict[str, Any]] = None) -> None:
        self.filters = frappe._dict(filters or {})
        self.columns = [
            {
                "fieldname": "integration_request_service",
                "label": "Service",
                "fieldtype": "Data",
                "width": 450,
            },
            {
                "fieldname": "avg_time",
                "label": "Average Time (Seconds)",
                "fieldtype": "Float",
                "width": 250,
            },
            {
                "fieldname": "min_time",
                "label": "Min Time (Seconds)",
                "fieldtype": "Float",
                "width": 250,
            },
            {
                "fieldname": "max_time",
                "label": "Max Time (Seconds)",
                "fieldtype": "Float",
                "width": 250,
            },
        ]
        self.data: List[Dict[str, Any]] = []
        self.chart: Dict[str, Any] = {}

    def run(
        self,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
        self.fetch_data()
        self.get_chart_data()
        return self.columns, self.data, None, self.chart

    def fetch_data(self) -> None:
        IntegrationRequest = DocType("Integration Request")
        Version = DocType("Version")

        first_status_change_query = (
            frappe.qb.from_(Version)
            .select(
                Version.ref_doctype,
                Version.docname,
                Min(Version.modified).as_("first_modified"),
            )
            .where(
                (Version.ref_doctype == "Integration Request")
                & (Version.data.like('%"status"%'))
            )
            .groupby(Version.ref_doctype, Version.docname)
        ).as_("status_change_times")

        query = (
            frappe.qb.from_(IntegrationRequest)
            .join(first_status_change_query)
            .on(IntegrationRequest.name == first_status_change_query.docname)
            .select(
                IntegrationRequest.integration_request_service,
                Avg(
                    first_status_change_query.first_modified
                    - IntegrationRequest.creation
                ).as_("avg_time"),
                Min(
                    first_status_change_query.first_modified
                    - IntegrationRequest.creation
                ).as_("min_time"),
                Max(
                    first_status_change_query.first_modified
                    - IntegrationRequest.creation
                ).as_("max_time"),
            )
            .where(
                (first_status_change_query.first_modified - IntegrationRequest.creation)
                <= 300
            )
            .groupby(IntegrationRequest.integration_request_service)
            .orderby(IntegrationRequest.integration_request_service)
        )

        if self.filters.get("from_date"):
            query = query.where(
                IntegrationRequest.creation >= self.filters["from_date"]
            )
        if self.filters.get("to_date"):
            query = query.where(IntegrationRequest.creation <= self.filters["to_date"])
        if self.filters.get("integration_request_service"):
            selected_services = self.filters["integration_request_service"]
            if isinstance(selected_services, str):
                selected_services = selected_services.split(",")
            query = query.where(
                IntegrationRequest.integration_request_service.isin(selected_services)
            )

        self.data = query.run(as_dict=True)

    def get_chart_data(self) -> None:
        labels = [row["integration_request_service"] for row in self.data]
        datasets = [
            {
                "name": "Average Time",
                "values": [flt(row.get("avg_time", 0.0)) for row in self.data],
            },
            {
                "name": "Min Time",
                "values": [flt(row.get("min_time", 0.0)) for row in self.data],
            },
            {
                "name": "Max Time",
                "values": [flt(row.get("max_time", 0.0)) for row in self.data],
            },
        ]

        self.chart = {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "axis_options": {"xIsSeries": True},
        }
