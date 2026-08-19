"""Document Submission Status Analytics report.

Tracks eTIMS submission status for Item, Customer and Supplier via the
``eTims ID Mapping`` child table, and for Sales Invoice / Credit Note via
the ``sent_to_etims`` checkbox. An optional company filter scopes results.
"""

from typing import Any, Dict, List, Optional, Tuple

from pypika.functions import Count
from pypika.terms import Case

import frappe
from frappe.query_builder import DocType

from ...doctype.doctype_names_mapping import SLADE_ID_MAPPING_DOCTYPE_NAME


def execute(
    filters: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], None, Dict[str, Any]]:
    return DocumentSubmissionStatusAnalytics(filters).run()


class DocumentSubmissionStatusAnalytics:
    """Aggregates eTIMS submission status across tracked document types."""

    def __init__(self, filters: Optional[Dict[str, Any]] = None) -> None:
        self.filters = frappe._dict(filters or {})
        self.columns = [
            {
                "fieldname": "doctype",
                "label": "Document Type",
                "fieldtype": "Data",
                "width": 300,
            },
            {"fieldname": "sent", "label": "Sent", "fieldtype": "Int", "width": 150},
            {
                "fieldname": "not_sent",
                "label": "Not Sent",
                "fieldtype": "Int",
                "width": 150,
            },
            {
                "fieldname": "failed",
                "label": "Failed",
                "fieldtype": "Int",
                "width": 150,
            },
            {
                "fieldname": "successful",
                "label": "Successful",
                "fieldtype": "Int",
                "width": 150,
            },
            {"fieldname": "total", "label": "Total", "fieldtype": "Int", "width": 150},
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
            row = self._fetch_mapped_doc_counts(doc_name, doctype)
            if row:
                row["doctype"] = doc_name
                self.data.append(row)

        invoice = DocType("Sales Invoice")
        for doc_name, is_return in self.invoice_docs.items():
            row = self._fetch_invoice_counts(invoice, is_return)
            if row:
                row["doctype"] = doc_name
                self.data.append(row)

    def _fetch_mapped_doc_counts(
        self, doc_name: str, doctype: DocType
    ) -> Optional[Dict[str, Any]]:
        """Counts registered vs unregistered entities using etims_id_mapping.

        An entity is considered "sent" when it has at least one row in the
        ``eTims ID Mapping`` child table.
        """
        mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        sent_condition = mapping.name.isnotnull()

        query = (
            frappe.qb.from_(doctype)
            .left_join(mapping)
            .on(
                (mapping.parent == doctype.name)
                & (mapping.parenttype == doc_name)
            )
            .select(
                Count(doctype.name).distinct().as_("total"),
                Count(Case().when(sent_condition, doctype.name).else_(None))
                .distinct()
                .as_("sent"),
            )
        )
        query = self._apply_date_filters(query, doctype)

        try:
            row = query.run(as_dict=True)[0]
            total = row.get("total") or 0
            sent = row.get("sent") or 0
            row["not_sent"] = total - sent
            row["failed"] = 0
            row["successful"] = sent
            return row
        except Exception as e:
            frappe.log_error(f"Error fetching data for {doc_name}: {str(e)}")
            return None

    def _fetch_invoice_counts(
        self, invoice: DocType, is_return: int
    ) -> Optional[Dict[str, Any]]:
        """Counts Sales Invoices / Credit Notes based on sent_to_etims checkbox."""
        company = self.filters.get("company")

        query = (
            frappe.qb.from_(invoice)
            .select(
                Count(invoice.name).distinct().as_("total"),
                Count(
                    Case()
                    .when(invoice.sent_to_etims == 1, invoice.name)
                    .else_(None)
                )
                .distinct()
                .as_("sent"),
            )
            .where(invoice.is_return == is_return)
        )
        if company:
            query = query.where(invoice.company == company)
        query = self._apply_date_filters(query, invoice)

        try:
            row = query.run(as_dict=True)[0]
            total = row.get("total") or 0
            sent = row.get("sent") or 0
            row["not_sent"] = total - sent
            row["failed"] = 0
            row["successful"] = sent
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
        labels = [row["doctype"] for row in self.data]
        datasets = [
            {"name": "Sent", "values": [row.get("sent", 0) for row in self.data]},
            {
                "name": "Not Sent",
                "values": [row.get("not_sent", 0) for row in self.data],
            },
            {"name": "Failed", "values": [row.get("failed", 0) for row in self.data]},
            {
                "name": "Successful",
                "values": [row.get("successful", 0) for row in self.data],
            },
        ]

        self.chart = {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "axis_options": {"xIsSeries": True},
        }