const doctypeName = "Sales Invoice";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName] =
  frappe.listview_settings[doctypeName] || {};

const existingOnload = frappe.listview_settings[doctypeName].onload;

frappe.listview_settings[doctypeName].onload = async function (listview) {
  if (existingOnload) {
    await existingOnload(listview);
  }

  const { message: activeSetting } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
    args: { doctype: settingsDoctypeName },
  });

  if (activeSetting?.length > 0) {
    listview.page.add_action_item(
      __("Submit to eTims"),
      function () {
        const checked_items = listview.get_checked_items();
        if (checked_items.length === 0) {
          frappe.msgprint(__("Please select at least one invoice."));
          return;
        }

        showSettingsModalAndExecute(
          "Submit to eTims",
          activeSetting,
          (settings_name) => ({
            method: "bulk_submit_sales_invoices",
            args: {
              docs_list: checked_items.map((item) => item.name),
              settings_name,
            },
            success_msg: "Submission to eTims queued.",
          }),
        );
      },
      __("eTims Actions"),
    );

    listview.page.add_action_item(
      __("Regenerate eTims QR Codes"),
      function () {
        const checked_items = listview.get_checked_items();
        if (checked_items.length === 0) {
          frappe.msgprint(__("Please select at least one invoice."));
          return;
        }

        const invoiceNames = checked_items.map((item) => item.name);

        frappe.confirm(
          __("Are you sure you want to regenerate QR codes for {0} invoices?", [
            invoiceNames.length,
          ]),
          function () {
            showSettingsModalAndExecute(
              "Regenerate QR Codes",
              activeSetting,
              (settings_name) => ({
                method: "regenerate_qr_code",
                args: {
                  names: invoiceNames,
                  settings_name: settings_name,
                },
                success_msg: `QR Code regeneration for ${invoiceNames.length} invoices`,
              }),
            );
          },
        );
      },
      __("eTims Actions"),
    );

    listview.page.add_inner_button(
      __("Run Auto-submission Scheduler"),
      function () {
        showSettingsModalAndExecute(
          "Run Auto-submission Scheduler",
          activeSetting,
          (settings_name) => ({
            method: "send_sales_invoices_information",
            args: { settings_name: settings_name },
            success_msg: "Bulk submission to eTims queued.",
          }),
        );
      },
      __("eTims Actions"),
    );
  }
};

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  executeWithSingleOrDialog(
    settings,
    (settingsName) => {
      const { method, args, success_msg } = getCallArgs(settingsName);
      executeEtimsAction(method, args, success_msg);
    },
    () => {
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
            options,
            reqd: 1,
            default: options[0]?.value,
          },
        ],
        primary_action_label: __("Proceed"),
        primary_action: ({ settings_name }) => {
          dialog.hide();

          const { method, args, success_msg } = getCallArgs(settings_name);

          executeEtimsAction(method, args, success_msg);
        },
      });

      dialog.show();
    },
  );
}

function executeWithSingleOrDialog(settings, actionFn, buildDialog) {
  if (settings.length === 1) {
    actionFn(settings[0].name);
    return;
  }

  buildDialog();
}

function executeEtimsAction(method, args, successMsg) {
  let methodPath;

  if (method === "regenerate_qr_code") {
    methodPath = `kenya_compliance_via_slade.kenya_compliance_via_slade.overrides.server.sales_invoice.${method}`;
  } else if (method === "send_sales_invoices_information") {
    methodPath = `kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.${method}`;
  } else {
    methodPath = `kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.${method}`;
  }

  frappe.call({
    method: methodPath,
    args,
    freeze: true,
    freeze_message: __("Processing..."),
    callback: (response) => {
      if (response.message && response.message.results) {
        const result = response.message;

        const grouped = {
          success: result.results.filter((r) => r.status === "success"),
          error: result.results.filter((r) => r.status === "error"),
          skipped: result.results.filter((r) => r.status === "skipped"),
        };

        let summaryHtml = `
          <div style="margin: 10px 0;">
            <strong>Total Processed:</strong> ${result.total}<br>
            <strong>✅ Success:</strong> ${grouped.success.length}<br>
            <strong>⏭️ Skipped:</strong> ${grouped.skipped.length}<br>
            <strong>❌ Errors:</strong> ${grouped.error.length}
          </div>
        `;

        if (grouped.success.length > 0) {
          const successList = grouped.success
            .map((r) => `<li>${r.invoice}</li>`)
            .join("");
          summaryHtml += `
            <div style="margin-top: 12px; padding: 10px; background: #f0fdf4; border-radius: 4px; border: 1px solid #bbf7d0;">
              <strong style="color: #166534;">✅ Successful (${grouped.success.length}):</strong>
              <ul style="margin: 5px 0 0 20px; padding: 0; list-style: disc;">
                ${successList}
              </ul>
            </div>
          `;
        }

        if (grouped.skipped.length > 0) {
          const skippedDetails = grouped.skipped
            .map((r) => `<li><strong>${r.invoice}</strong>: ${r.message}</li>`)
            .join("");
          summaryHtml += `
            <div style="margin-top: 12px; padding: 10px; background: #fffbeb; border-radius: 4px; border: 1px solid #fde68a;">
              <strong style="color: #92400e;">⏭️ Skipped (${grouped.skipped.length}):</strong>
              <ul style="margin: 5px 0 0 20px; padding: 0; list-style: disc;">
                ${skippedDetails}
              </ul>
            </div>
          `;
        }

        if (grouped.error.length > 0) {
          const errorDetails = grouped.error
            .map((r) => `<li><strong>${r.invoice}</strong>: ${r.message}</li>`)
            .join("");
          summaryHtml += `
            <div style="margin-top: 12px; padding: 10px; background: #fef2f2; border-radius: 4px; border: 1px solid #fecaca;">
              <strong style="color: #991b1b;">❌ Errors (${grouped.error.length}):</strong>
              <ul style="margin: 5px 0 0 20px; padding: 0; list-style: disc;">
                ${errorDetails}
              </ul>
            </div>
          `;
        }

        let indicator = "green";
        let title = __(successMsg);

        if (grouped.error.length > 0) {
          indicator = "red";
          title = __(successMsg + " with Errors");
        } else if (grouped.skipped.length > 0 && grouped.success.length === 0) {
          indicator = "orange";
          title = __(successMsg + " with Skips");
        }

        frappe.msgprint({
          title: title,
          indicator: indicator,
          message: summaryHtml,
        });

        setTimeout(() => {
          frappe.listview.refresh();
        }, 2000);
      } else {
        frappe.msgprint(__(successMsg));
      }
    },
    error: (err) => {
      console.error(err);
      frappe.msgprint({
        title: __("Error"),
        indicator: "red",
        message: __("An error occurred during the request: {0}", [
          err.message || err,
        ]),
      });
    },
  });
}
