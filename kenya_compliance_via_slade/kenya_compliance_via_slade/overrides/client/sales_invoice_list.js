const doctypeName = "Sales Invoice";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName].onload = async function (listview) {
  const { message: activeSetting } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
    args: { doctype: settingsDoctypeName },
  });

  if (activeSetting?.length > 0) {
    listview.page.add_action_item(
      __("Bulk Submit to eTims"),
      function () {
        showSettingsSelectionDialog(
          "Bulk Submit to eTims",
          activeSetting,
          (settings_name) => {
            const selected = listview
              .get_checked_items()
              .map((item) => item.name);
            bulkSubmitInvoices(selected, settings_name);
          }
        );
      },
      __("eTims Actions")
    );

    listview.page.add_inner_button(
      __("Submit All Invoices"),
      function () {
        showSettingsSelectionDialog(
          "Submit All Invoices",
          activeSetting,
          (settings_name) => {
            bulkSubmitInvoices(null, settings_name);
          }
        );
      },
      __("eTims Actions")
    );

    listview.page.add_action_item(
      __("Verify & Resend to eTims"),
      function () {
        showSettingsSelectionDialog(
          "Verify & Resend to eTims",
          activeSetting,
          (settings_name) => {
            const selected = listview
              .get_checked_items()
              .map((item) => item.name);
            bulkVerifyAndResendInvoices(selected, settings_name);
          }
        );
      },
      __("eTims Actions")
    );

    listview.page.add_inner_button(
      __("Verify & Resend All Invoices"),
      function () {
        showSettingsSelectionDialog(
          "Verify & Resend All Invoices",
          activeSetting,
          (settings_name) => {
            bulkVerifyAndResendInvoices(null, settings_name);
          }
        );
      },
      __("eTims Actions")
    );
  }
};

function bulkSubmitInvoices(docs_list = null, settings_name) {
  frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.bulk_submit_sales_invoices",
    args: {
      docs_list: docs_list,
      settings_name: settings_name,
    },
    callback: () => frappe.msgprint("Bulk submission to eTims queued."),
  });
}

function bulkVerifyAndResendInvoices(docs_list = null, settings_name) {
  frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.bulk_verify_and_resend_invoices",
    args: {
      docs_list: docs_list,
      settings_name: settings_name,
    },
    callback: () =>
      frappe.msgprint(
        "Bulk verification queued. Incorrect invoices will be resent to eTims."
      ),
  });
}

function showSettingsSelectionDialog(title, settings, callback) {
  const options = settings.map((s) => ({
    label: `${s.company} (${s.name})`,
    value: s.name,
  }));

  const dialog = new frappe.ui.Dialog({
    title: __(title),
    fields: [
      {
        label: __("Select eTims Settings"),
        fieldname: "settings_name",
        fieldtype: "Select",
        options: options,
        reqd: 1,
        default: options[0]?.value,
      },
    ],
    primary_action_label: __("Proceed"),
    primary_action: ({ settings_name }) => {
      dialog.hide();
      callback(settings_name);
    },
  });
  dialog.show();
}
