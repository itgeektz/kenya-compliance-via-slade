// Copyright (c) 2026, Navari Ltd and contributors
// For license information, please see license.txt

const doctypeName = "eTIMS Sales Ledger Entry";
const settingsDoctypeName = "Navari KRA eTims Settings";

const _existing_onload = frappe.listview_settings[doctypeName]?.onload;

if (!frappe.listview_settings[doctypeName]) {
  frappe.listview_settings[doctypeName] = {};
}

frappe.listview_settings[doctypeName].onload = async function (listview) {
  if (_existing_onload) {
    await _existing_onload.call(this, listview);
  }

  const { message: activeSetting } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
    args: { doctype: settingsDoctypeName },
  });

  listview.page.add_inner_button(
    __("Fetch All Invoices"),
    function () {
      showSettingsModalAndExecute(activeSetting);
    },
    __("eTims Actions"),
  );

  listview.page.add_action_item(__("Refetch eTIMS Invoices"), () => {
    const selected_docs = listview.get_checked_items();

    frappe.confirm(
      __(
        "Are you sure you want to refetch eTIMS data for {0} selected entries?",
        [selected_docs.length],
      ),
      () => {
        frappe
          .run_serially(
            selected_docs.map((doc) => {
              return () =>
                frappe.call({
                  method:
                    "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.fetch_etims_ledger_entry",
                  args: {
                    name: doc.name,
                    queue: true,
                  },
                });
            }),
          )
          .then(() => {
            frappe.show_alert({
              message: __("Selected eTIMS invoices refetched successfully."),
              indicator: "green",
            });
            listview.refresh();
          });
      },
    );
  });

  listview.page.add_action_item(__("Generate Credit Notes"), () => {
    const selected_docs = listview
      .get_checked_items()
      .filter((d) => d.type === "Sales Invoice");

    if (selected_docs.length === 0) {
      frappe.msgprint(
        __(
          "Please select at least one 'Sales Invoice' entry to generate Credit Notes.",
        ),
      );
      return;
    }

    frappe.confirm(
      __(
        "Are you sure you want to generate Credit Notes for {0} selected Sales Invoices?",
        [selected_docs.length],
      ),
      () => {
        frappe
          .run_serially(
            selected_docs.map((doc) => {
              return () =>
                frappe.call({
                  method:
                    "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.return_etims_credit_note",
                  args: {
                    name: doc.name,
                    queue: true,
                  },
                });
            }),
          )
          .then(() => {
            frappe.show_alert({
              message: __(
                "Credit Notes process completed for selected invoices.",
              ),
              indicator: "green",
            });
            listview.refresh();
          });
      },
    );
  });
};

function showSettingsModalAndExecute(settings) {
  const executeFetch = (settings_name, request_data, invoice_type) => {
    frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.fetch_etims_sales_data",
      args: {
        request_data: request_data,
        settings_name: settings_name,
        invoice_type: invoice_type,
      },
      freeze: true,
      freeze_message: __("Processing..."),
      callback: () => frappe.msgprint(__("Invoices fetched successfully.")),
      error: (err) => {
        console.error(err);
        frappe.msgprint(__("An error occurred during the request."));
      },
    });
  };

  const showFilterDialog = (settings_name) => {
    const lastMonth = new Date();
    lastMonth.setMonth(lastMonth.getMonth() - 1);
    const defaultFromDate = lastMonth.toISOString().split("T")[0];
    const defaultToDate = new Date().toISOString().split("T")[0];

    const dialog = new frappe.ui.Dialog({
      title: __("Fetch eTIMS Sales Invoices"),
      size: "large",
      fields: [
        {
          fieldtype: "Section Break",
          fieldname: "date_section",
          label: __("Date Range"),
          collapsible: 0,
        },
        {
          fieldtype: "Column Break",
          fieldname: "col_break_1",
        },
        {
          label: __("Invoice Date From"),
          fieldname: "invoice_date_after",
          fieldtype: "Date",
          default: defaultFromDate,
          placeholder: "YYYY-MM-DD",
        },
        {
          fieldtype: "Column Break",
          fieldname: "col_break_2",
        },
        {
          label: __("Invoice Date To"),
          fieldname: "invoice_date_before",
          fieldtype: "Date",
          default: defaultToDate,
          placeholder: "YYYY-MM-DD",
        },
        {
          fieldtype: "Section Break",
          fieldname: "document_section",
          label: __("Document Information"),
        },
        {
          fieldtype: "Column Break",
          fieldname: "col_break_3",
        },
        {
          label: __("Invoice Type"),
          fieldname: "type",
          fieldtype: "Select",
          options: [
            { label: __("Both"), value: "Both" },
            { label: __("Sales Invoice"), value: "Sales Invoice" },
            { label: __("Credit Note"), value: "Credit Note" },
          ],
          default: "Both",
        },
        {
          fieldtype: "Column Break",
          fieldname: "col_break_4",
        },
        {
          label: __("Reference Number"),
          fieldname: "reference_number",
          fieldtype: "Link",
          options: "Sales Invoice",
          placeholder: "Enter reference number",
        },
      ],
      primary_action_label: __("Fetch Invoices"),
      primary_action: (values) => {
        const request_data = {};

        if (values.invoice_date_after)
          request_data.invoice_date_after = values.invoice_date_after;
        if (values.invoice_date_before)
          request_data.invoice_date_before = values.invoice_date_before;
        if (values.reference_number)
          request_data.search = values.reference_number;

        dialog.hide();
        executeFetch(settings_name, request_data, values.type);
      },
      secondary_action_label: __("Skip Filters"),
      secondary_action: () => {
        dialog.hide();
        executeFetch(settings_name, {}, "Both");
      },
    });

    dialog.show();
  };

  if (settings.length === 1) {
    showFilterDialog(settings[0].name);
  } else {
    const options = settings.map((s) => ({
      label: `${s.company} (${s.name})`,
      value: s.name,
    }));

    const settingsDialog = new frappe.ui.Dialog({
      title: __("Select eTims Settings"),
      fields: [
        {
          label: __("eTims Settings"),
          fieldname: "settings_name",
          fieldtype: "Select",
          options: options,
          reqd: 1,
          default: options[0]?.value,
        },
      ],
      primary_action_label: __("Continue"),
      primary_action: ({ settings_name }) => {
        settingsDialog.hide();
        showFilterDialog(settings_name);
      },
    });
    settingsDialog.show();
  }
}
