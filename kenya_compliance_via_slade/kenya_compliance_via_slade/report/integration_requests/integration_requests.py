from typing import Any, Dict, List, Optional, Tuple

from pypika.functions import Count, Sum
from pypika.terms import Case

import frappe
from frappe.query_builder import DocType


def execute(
    filters: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
    return IntegrationRequestAnalytics(filters).run()


class IntegrationRequestAnalytics:
    def __init__(self, filters: Optional[Dict[str, Any]] = None) -> None:
        self.filters = frappe._dict(filters or {})
        self.columns = [
            {
                "fieldname": "integration_request_service",
                "label": "Service",
                "fieldtype": "Data",
                "width": 400,
            },
            {
                "fieldname": "queued",
                "label": "Queued",
                "fieldtype": "Int",
                "width": 150,
            },
            {
                "fieldname": "completed",
                "label": "Completed",
                "fieldtype": "Int",
                "width": 150,
            },
            {
                "fieldname": "cancelled",
                "label": "Cancelled",
                "fieldtype": "Int",
                "width": 150,
            },
            {
                "fieldname": "failed",
                "label": "Failed",
                "fieldtype": "Int",
                "width": 150,
            },
            {"fieldname": "total", "label": "Total", "fieldtype": "Int", "width": 150},
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

        query = (
            frappe.qb.from_(IntegrationRequest)
            .select(
                IntegrationRequest.integration_request_service,
                Sum(Case().when(IntegrationRequest.status == "Queued", 1).else_(0)).as_(
                    "queued"
                ),
                Sum(
                    Case().when(IntegrationRequest.status == "Completed", 1).else_(0)
                ).as_("completed"),
                Sum(
                    Case().when(IntegrationRequest.status == "Cancelled", 1).else_(0)
                ).as_("cancelled"),
                Sum(Case().when(IntegrationRequest.status == "Failed", 1).else_(0)).as_(
                    "failed"
                ),
                Count("*").as_("total"),
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
            {"name": "Queued", "values": [row.get("queued", 0) for row in self.data]},
            {
                "name": "Completed",
                "values": [row.get("completed", 0) for row in self.data],
            },
            {
                "name": "Cancelled",
                "values": [row.get("cancelled", 0) for row in self.data],
            },
            {"name": "Failed", "values": [row.get("failed", 0) for row in self.data]},
        ]

        self.chart = {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "axis_options": {"xIsSeries": True},
        }
