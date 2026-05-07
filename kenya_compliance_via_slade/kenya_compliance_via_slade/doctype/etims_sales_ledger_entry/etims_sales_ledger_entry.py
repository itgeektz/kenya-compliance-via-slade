# Copyright (c) 2026, Navari Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class eTIMSSalesLedgerEntry(Document):
    def validate(self):
        self.link_related_document()

    def link_related_document(self):
        if not self.reference_number:
            return

        base_ref = self.reference_number.split("-REV")[0]

        if self.type == "Credit Note":
            existing_cn = frappe.db.get_value(
                "Sales Invoice", {"name": base_ref, "is_return": 1}
            )
            if existing_cn:
                self.credit_note = existing_cn
        else:
            existing_inv = frappe.db.get_value(
                "Sales Invoice", {"name": base_ref, "is_return": 0}
            )
            if existing_inv:
                self.sales_invoice = existing_inv
