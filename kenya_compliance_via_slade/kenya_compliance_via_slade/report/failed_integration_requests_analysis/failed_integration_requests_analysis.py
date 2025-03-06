import ast
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

import frappe
from frappe import _, scrub
from frappe.utils import add_days, add_to_date, flt, getdate

from erpnext.accounts.utils import get_fiscal_year

DOCTYPE_MAPPING = {
    "Sales Invoice": ["Sales Invoice", "Sales Invoice Item"],
    "Purchase Invoice": ["Purchase Invoice", "Purchase Invoice Item"],
    "BOM": ["BOM", "BOM Item"],
    "Item": ["Item"],
    "Customer": ["Customer"],
    "Supplier": ["Supplier"],
    "Stock Ledger Entry": ["Stock Ledger Entry"],
}


def execute(
    filters: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
    return FailedIntegrationRequestsAnalytics(filters).run()


class FailedIntegrationRequestsAnalytics:
    def __init__(self, filters: Optional[Dict[str, Any]] = None) -> None:
        """Failed Integration Requests Report"""
        self.filters = frappe._dict(filters or {})
        self.get_period_date_ranges()

    def run(
        self,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
        self.get_columns()
        self.get_data()
        self.get_chart_data()
        return self.columns, self.data, None, self.chart

    def get_columns(self) -> None:
        """Define report columns"""
        self.columns: List[Dict[str, Any]] = [
            {
                "label": _("Error"),
                "fieldname": "error",
                "fieldtype": "Data",
                "width": 400,
            }
        ]

        for end_date in self.periodic_daterange:
            period = self.get_period(end_date)
            self.columns.append(
                {
                    "label": _(period),
                    "fieldname": scrub(period),
                    "fieldtype": "Int",
                    "width": 120,
                }
            )

        self.columns.append(
            {
                "label": _("Total"),
                "fieldname": "total",
                "fieldtype": "Int",
                "width": 120,
            }
        )

    def get_data(self) -> None:
        """Fetch and process failed integration requests"""
        self.get_failed_requests()
        self.get_rows()

    def get_failed_requests(self) -> None:
        """Fetch failed integration requests grouped by error"""
        filters: Dict[str, Any] = {"status": "Failed"}
        if self.filters.get("reference_doctype"):
            if self.filters.reference_doctype not in DOCTYPE_MAPPING:
                frappe.throw(
                    _("Doctype {} is not supported in this report.").format(
                        self.filters.reference_doctype
                    )
                )
            filters["reference_doctype"] = self.filters.reference_doctype

        failed_requests = frappe.get_all(
            "Integration Request", filters=filters, fields=["error", "creation"]
        )

        self.error_periodic_data: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        for request in failed_requests:
            error = self.style_error_message(request["error"] or "No error message")
            period = self.get_period(getdate(request["creation"]))

            self.error_periodic_data[error][period] += 1

    def style_error_message(self, error: str) -> str:
        error = error.strip()

        if error.startswith("{") and error.endswith("}"):
            try:
                error_json = ast.literal_eval(error)
                if isinstance(error_json, dict):
                    return format_error_dict(error_json)
            except (ValueError, SyntaxError):
                pass

        try:
            error_json = json.loads(error.replace("'", '"'))
            if isinstance(error_json, dict):
                return format_error_dict(error_json)
        except (json.JSONDecodeError, TypeError):
            pass

        try:
            soup = BeautifulSoup(error, "html.parser")
            h1 = soup.find("h1")
            h2 = soup.find("h2")
            title = soup.find("title")

            if h1:
                return h1.text.strip()
            elif h2:
                return h2.text.strip()
            elif title:
                return title.text.strip()
        except Exception:
            pass

        return error[:100]

    def get_rows(self) -> None:
        """Format grouped data into report rows"""
        self.data: List[Dict[str, Any]] = []

        for error, period_data in self.error_periodic_data.items():
            row: Dict[str, Any] = {"error": error}
            total = 0

            for end_date in self.periodic_daterange:
                period = self.get_period(end_date)
                count = flt(period_data.get(period, 0.0))
                row[scrub(period)] = count
                total += count

            row["total"] = total
            self.data.append(row)

    def get_period(self, date: str) -> str:
        """Determine report period labels"""
        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]

        if self.filters.range == "Weekly":
            period = "Week " + str(date.isocalendar()[1])
        elif self.filters.range == "Monthly":
            period = str(months[date.month - 1])
        elif self.filters.range == "Quarterly":
            period = "Quarter " + str(((date.month - 1) // 3) + 1)
        else:
            year = get_fiscal_year(date, self.filters.company)
            period = str(year[0])

        if (
            getdate(self.filters.from_date).year != getdate(self.filters.to_date).year
            and self.filters.range != "Yearly"
        ):
            period += " " + str(date.year)

        return period

    def get_period_date_ranges(self) -> None:
        """Generate date ranges based on filters"""
        from dateutil.relativedelta import MO, relativedelta

        from_date, to_date = getdate(self.filters.from_date), getdate(
            self.filters.to_date
        )
        increment = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Yearly": 12}.get(
            self.filters.range, 1
        )

        if self.filters.range in ["Monthly", "Quarterly"]:
            from_date = from_date.replace(day=1)
        elif self.filters.range == "Yearly":
            from_date = get_fiscal_year(from_date)[1]
        else:
            from_date = from_date + relativedelta(from_date, weekday=MO(-1))

        self.periodic_daterange: List[str] = []
        for x in range(1, 53):
            period_end_date = (
                add_days(from_date, 6)
                if self.filters.range == "Weekly"
                else add_to_date(from_date, months=increment, days=-1)
            )
            if period_end_date > to_date:
                period_end_date = to_date
            self.periodic_daterange.append(period_end_date)
            from_date = add_days(period_end_date, 1)
            if period_end_date == to_date:
                break

    def get_chart_data(self) -> None:
        labels = [d.get("label") for d in self.columns[1:-1]]
        datasets: List[Dict[str, Any]] = []

        for error, period_data in self.error_periodic_data.items():
            dataset_values = [
                flt(period_data.get(self.get_period(end_date), 0.0))
                for end_date in self.periodic_daterange
            ]
            datasets.append({"name": error, "values": dataset_values})

        if len(self.error_periodic_data.items()) > 5:
            labels = [self.columns[-1].get("label")]
            for error, period_data in self.error_periodic_data.items():
                total_value = sum(
                    flt(period_data.get(self.get_period(end_date), 0.0))
                    for end_date in self.periodic_daterange[1:-1]
                )
                datasets.append({"name": error, "values": [total_value]})

        self.chart: Dict[str, Any] = {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "axis_options": {"xIsSeries": True},
        }


def format_error_dict(error_dict: Dict[str, Any]) -> str:
    messages = []
    for key, value in error_dict.items():
        if isinstance(value, list) and value:
            messages.append(f"{key}: {', '.join(map(str, value))}")
        else:
            messages.append(f"{key}: {value}")
    return "; ".join(messages)
