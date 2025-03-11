// Copyright (c) 2025, Navari Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Failed Integration Requests Analysis"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company"),
      reqd: 1,
    },
    {
      fieldname: "reference_doctype",
      label: "Issue Type",
      fieldtype: "Select",
      options: [
        "",
        "Sales Invoice",
        "Item",
        "BOM",
        "Customer",
        "Supplier",
        "Purchase Invoice",
        "Stock Ledger Entry",
      ],
      default: "Sales Invoice",
      reqd: 1,
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.add_days(frappe.datetime.now_date(), -365),
      reqd: 1,
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.nowdate(),
      reqd: 1,
    },
    {
      fieldname: "range",
      label: __("Range"),
      fieldtype: "Select",
      options: [
        { value: "Weekly", label: __("Weekly") },
        { value: "Monthly", label: __("Monthly") },
        { value: "Quarterly", label: __("Quarterly") },
        { value: "Yearly", label: __("Yearly") },
      ],
      default: "Monthly",
      reqd: 1,
    },
  ],

  after_datatable_render: function (datatable_obj) {
    $(datatable_obj.wrapper)
      .find(".dt-row-0")
      .find("input[type=checkbox]")
      .click();
  },

  get_datatable_options(options) {
    return Object.assign(options, {
      checkboxColumn: true,
      events: {
        onCheckRow: function (data) {
          if (data && data.length) {
            let row_name = data[1].content;
            let row_values = data.slice(2).map((column) => column.content);
            let entry = { name: row_name, values: row_values };

            let raw_data = frappe.query_report.chart.data;
            let new_datasets = [...raw_data.datasets];

            let existing_index = new_datasets.findIndex(
              (ds) => ds.name === row_name
            );

            if (existing_index !== -1) {
              new_datasets.splice(existing_index, 1);
            } else {
              new_datasets.push(entry);
            }

            let new_data = {
              labels: raw_data.labels,
              datasets: new_datasets,
            };

            setTimeout(() => {
              frappe.query_report.chart.update(new_data);
            }, 500);

            setTimeout(() => {
              frappe.query_report.chart.draw(true);
            }, 1000);

            frappe.query_report.raw_chart_data = new_data;
          }
        },
      },
    });
  },
};
