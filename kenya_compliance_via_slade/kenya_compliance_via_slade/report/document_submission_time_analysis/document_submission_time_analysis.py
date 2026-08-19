"""Document Submission Time Analysis report.

Calculates average / min / max submission durations for Item, Customer and
Supplier using the ``eTims ID Mapping`` child table modification time, and
for Sales Invoice / Credit Note using the ``sent_to_etims`` checkbox.
"""

from typing import Any, Dict, List, Optional, Tuple

from pypika.functions import Avg, Max, Min

import frappe
from frappe.query_builder import DocType

from ...doctype.doctype_names_mapping import SLADE_ID_MAPPING_DOCTYPE_NAME


def execute(
    filters: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
    return DocumentSubmissionTimeAnalytics(filters).run()


class DocumentSubmissionTimeAnalytics:
    """Aggregates eTIMS submission time analytics across tracked document types."""

    def __init__(self, filters: Optional[Dict[str, Any]] = None) -> None:
        self.filters = frappe._dict(filters or {})
        self.columns = [
            {
                "fieldname": "doctype",
                "label": "Document Type",
                "fieldtype": "Data",
                "width": 300,
            },
            {
                "fieldname": "avg_time",
                "label": "Average Time (Seconds)",
                "fieldtype": "Float",
                "width": 300,
            },
            {
                "fieldname": "min_time",
                "label": "Min Time (Seconds)",
                "fieldtype": "Float",
                "width": 300,
            },
            {
                "fieldname": "max_time",
                "label": "Max Time (Seconds)",
                "fieldtype": "Float",
                "width": 300,
            },
        ]
        self.data: List[Dict[str, Any]] = []
        self.chart: Dict[str, Any] = {}
        self.mapped_docs = {
            "Item": DocType("Item"),
            "Customer": DocType("Customer"),
            "Supplier": DocType("Supplier"),
        }
        self.invoice_docs = {
            "Invoice": 0,  # is_return = 0
            "Credit Note": 1,  # is_return = 1
        }

    def run(
        self,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
        self.fetch_data()
        self.get_chart_data()
        return self.columns, self.data, None, self.chart

    def fetch_data(self) -> None:
        for doc_name, doctype in self.mapped_docs.items():
            row = self._fetch_mapped_doc_times(doc_name, doctype)
            if row:
                row["doctype"] = doc_name
                self.data.append(row)

        invoice = DocType("Sales Invoice")
        for doc_name, is_return in self.invoice_docs.items():
            row = self._fetch_invoice_times(invoice, is_return)
            if row:
                row["doctype"] = doc_name
                self.data.append(row)

    def _fetch_mapped_doc_times(
        self, doc_name: str, doctype: DocType
    ) -> Optional[Dict[str, Any]]:
        """Computes submission duration using the eTims ID Mapping row timestamp.

        The duration is measured from the entity's creation to when its mapping
        child row was last modified (roughly the submission moment).
        """
        mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        query = (
            frappe.qb.from_(doctype)
            .join(mapping)
            .on(
                (mapping.parent == doctype.name)
                & (mapping.parenttype == doc_name)
            )
            .select(
                Avg(mapping.modified - doctype.creation).as_("avg_time"),
                Min(mapping.modified - doctype.creation).as_("min_time"),
                Max(mapping.modified - doctype.creation).as_("max_time"),
            )
            .where((mapping.modified - doctype.creation) <= 300)
        )
        query = self._apply_date_filters(query, doctype)

        try:
            row = query.run(as_dict=True)[0]
            return row
        except Exception as e:
            frappe.log_error(f"Error fetching data for {doc_name}: {str(e)}")
            return None

    def _fetch_invoice_times(
        self, invoice: DocType, is_return: int
    ) -> Optional[Dict[str, Any]]:
        """Computes submission duration for invoices/credit notes sent to eTims."""
        company = self.filters.get("company")

        query = (
            frappe.qb.from_(invoice)
            .select(
                Avg(invoice.modified - invoice.creation).as_("avg_time"),
                Min(invoice.modified - invoice.creation).as_("min_time"),
                Max(invoice.modified - invoice.creation).as_("max_time"),
            )
            .where((invoice.sent_to_etims == 1) & (invoice.is_return == is_return))
            .where((invoice.modified - invoice.creation) <= 300)
        )
        if company:
            query = query.where(invoice.company == company)
        query = self._apply_date_filters(query, invoice)

        try:
            row = query.run(as_dict=True)[0]
            return row
        except Exception as e:
            frappe.log_error(f"Error fetching data for invoice return {is_return}: {str(e)}")
            return None

    def _apply_date_filters(self, query, doctype: DocType):
        """Applies from_date / to_date creation filters to a query."""
        from_date = self.filters.get("from_date")
        to_date = self.filters.get("to_date")
        if from_date:
            query = query.where(doctype.creation >= from_date)
        if to_date:
            query = query.where(doctype.creation <= to_date)
        return query

    def get_chart_data(self) -> None:
        labels: List[str] = [row["doctype"] for row in self.data]
        datasets: List[Dict[str, Any]] = [
            {
                "name": "Average Time",
                "values": [row.get("avg_time", 0) for row in self.data],
            },
            {
                "name": "Min Time",
                "values": [row.get("min_time", 0) for row in self.data],
            },
            {
                "name": "Max Time",
                "values": [row.get("max_time", 0) for row in self.data],
            },
        ]

        self.chart = {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "axis_options": {"xIsSeries": True},
        }