// Copyright (c) 2025, Navari Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Document Submission Time Analysis"] = {
  filters: [
    {
      fieldname: "company",
      label: "Company",
      fieldtype: "Link",
      options: "Company",
      reqd: 0,
    },
    {
      fieldname: "from_date",
      label: "From Date",
      fieldtype: "Date",
      reqd: 0,
    },
    {
      fieldname: "to_date",
      label: "To Date",
      fieldtype: "Date",
      reqd: 0,
    },
  ],

  onload: function (report) {
    report.page.add_inner_button("Clear Filters", function () {
      report.filters.forEach((filter) => {
        filter.set_input(filter.df.default || "");
      });
      report.refresh();
    });
  },
};