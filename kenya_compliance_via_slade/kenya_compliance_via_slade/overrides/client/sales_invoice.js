const parentDoctype = "Sales Invoice";
const childDoctype = `${parentDoctype} Item`;
const packagingUnitDoctypeName = "Navari eTims Packaging Unit";
const unitOfQuantityDoctypeName = "Navari eTims Unit of Quantity";
const taxationTypeDoctypeName = "Navari KRA eTims Taxation Type";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.realtime.on("refresh_form", function (name) {
  const currentForm = cur_frm;
  if (currentForm && currentForm.doc.name === name) {
    currentForm.reload_doc();
  }
});

frappe.ui.form.on(parentDoctype, {
  refresh: async function (frm) {
    await updateTaxAmountLabel(frm);

    const summaryData = await renderEtimsSummary(frm);

    if (frm.is_new()) return;

    const { message: activeSetting } = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
      args: { doctype: settingsDoctypeName, company: frm.doc.company },
    });

    if (
      activeSetting?.length > 0 &&
      frm.doc.docstatus !== 0 &&
      !frm.doc.prevent_etims_submission
    ) {
      if (!frm.doc.custom_successfully_submitted) {
        frm.add_custom_button(
          __("Send Invoice"),
          function () {
            showSettingsModalAndExecute(
              "Send Invoice",
              activeSetting,
              (settings_name) => ({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.overrides.server.sales_invoice.send_invoice_details",
                args: {
                  name: frm.doc.name,
                  settings_name: settings_name,
                },
                success_msg: "Invoice submission queued",
              }),
            );
          },
          __("eTims Actions"),
        );
      }

      frm.add_custom_button(
        __("Check & Sync eTIMS Status"),
        function () {
          showSettingsModalAndExecute(
            "Sync Invoice",
            activeSetting,
            (settings_name) => ({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.get_invoice_details",
              args: {
                document_name: frm.doc.name,
                invoice_type: "Sales Invoice",
                settings_name: settings_name,
                company: frm.doc.company,
              },
              success_msg: "Invoice sync queued",
            }),
          );

          showSettingsModalAndExecute(
            "Check eTIMS Status",
            activeSetting,
            (settings_name) => ({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.fetch_etims_sales_data",
              args: {
                request_data: {
                  reference_number: frm.doc.is_return
                    ? frm.doc.return_against
                    : frm.doc.name,
                },
                settings_name: settings_name,
                invoice_type: "Sales Invoice",
              },
              success_msg: "Invoice status fetch queued",
            }),
          );
        },
        __("eTims Actions"),
      );

      if (
        frm.doc.custom_successfully_submitted &&
        summaryData?.hasSignificantMismatch
      ) {
        frm.add_custom_button(
          __("Correction Credit Note on eTIMS"),
          function () {
            const erpInvoiceAmount = flt(
              summaryData?.totalRow?.erp_invoice_period_amount || 0,
            );

            const erpCreditAmount = flt(
              summaryData?.totalRow?.erp_credit_period_amount || 0,
            );

            const etimsInvoiceAmount = flt(
              summaryData?.totalRow?.etims_invoice_amount || 0,
            );

            const etimsCreditAmount = flt(
              summaryData?.totalRow?.etims_credit_amount || 0,
            );

            const erpVat = flt(summaryData?.totalRow?.erp_tax_amount || 0);

            const etimsVat = flt(summaryData?.totalRow?.etims_total_tax || 0);

            const difference = flt(summaryData?.totalRow?.difference || 0);

            const vatDifference = flt(
              summaryData?.totalRow?.tax_difference || 0,
            );

            const erpNet = erpInvoiceAmount - erpCreditAmount;

            const etimsNet = etimsInvoiceAmount - etimsCreditAmount;

            const differencePercent = flt(summaryData?.differencePercent || 0);

            const currency = "KES";

            const formatValue = (value) =>
              format_currency(value || 0, currency);

            const issueNotes = [];

            if (Math.abs(difference) > 1) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          ERPNext invoice totals do not match eTIMS invoice totals.
        </li>
      `);
            }

            if (Math.abs(vatDifference) > 1) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          ERPNext VAT totals do not match eTIMS VAT totals.
        </li>
      `);
            }

            if (Math.abs(erpNet) > 1 && Math.abs(etimsNet) > 1) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          Net invoice balance is not fully offset by credit notes. Some invoices may be missing corresponding correction credit notes on eTIMS.
        </li>
      `);
            }

            if (
              Math.abs(erpInvoiceAmount) > 1 &&
              Math.abs(etimsInvoiceAmount) < 1
            ) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          ERPNext invoices exist but no matching eTIMS invoice totals were found.
        </li>
      `);
            }

            if (
              Math.abs(erpCreditAmount) > 1 &&
              Math.abs(etimsCreditAmount) < 1
            ) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          ERPNext credit notes exist but no matching eTIMS credit notes were found.
        </li>
      `);
            }

            if (!issueNotes.length) {
              issueNotes.push(`
        <li style="margin-bottom:10px;">
          Significant reconciliation mismatch detected requiring verification.
        </li>
      `);
            }

            const dialog = new frappe.ui.Dialog({
              title: __("Correction Credit Note on eTIMS"),
              size: "large",
              fields: [
                {
                  fieldtype: "HTML",
                  fieldname: "warning_html",
                  options: `
            <div style="
              display:flex;
              flex-direction:column;
              gap:18px;
            ">

              <div style="
                padding:22px;
                border-radius:18px;
                background:#fef2f2;
                border:1px solid #fecaca;
              ">
                <div style="
                  font-size:20px;
                  font-weight:700;
                  color:#991b1b;
                  margin-bottom:14px;
                ">
                  Warning
                </div>

                <div style="
                  font-size:14px;
                  color:#7f1d1d;
                  line-height:1.8;
                ">
                  This process verifies ERPNext invoice values against eTIMS records and may automatically generate correction credit notes on eTIMS to align submitted tax data with ERPNext records.

                  <br><br>

                  This affects official tax submissions to KRA and should only be executed after reviewing the reconciliation summary below.
                </div>
              </div>

              <div style="
                border:1px solid #e5e7eb;
                border-radius:18px;
                overflow:hidden;
                background:#ffffff;
              ">
                <div style="
                  padding:16px 20px;
                  background:#f8fafc;
                  border-bottom:1px solid #e5e7eb;
                  font-size:17px;
                  font-weight:700;
                  color:#0f172a;
                ">
                  Advanced Reconciliation Summary
                </div>

                <div style="
                  display:grid;
                  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
                  gap:14px;
                  padding:18px;
                ">

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #e2e8f0;
                    background:#ffffff;
                  ">
                    <div style="font-size:12px;color:#64748b;">
                      ERPNext Invoice Amount
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#0f172a;
                    ">
                      ${formatValue(erpInvoiceAmount)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #e2e8f0;
                    background:#ffffff;
                  ">
                    <div style="font-size:12px;color:#64748b;">
                      ERPNext Credit Notes
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#0f172a;
                    ">
                      ${formatValue(erpCreditAmount)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #bfdbfe;
                    background:#eff6ff;
                  ">
                    <div style="font-size:12px;color:#1d4ed8;">
                      eTIMS Invoice Amount
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#1e3a8a;
                    ">
                      ${formatValue(etimsInvoiceAmount)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #bfdbfe;
                    background:#eff6ff;
                  ">
                    <div style="font-size:12px;color:#1d4ed8;">
                      eTIMS Credit Notes
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#1e3a8a;
                    ">
                      ${formatValue(etimsCreditAmount)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #fecaca;
                    background:#fef2f2;
                  ">
                    <div style="font-size:12px;color:#991b1b;">
                      Difference
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#991b1b;
                    ">
                      ${formatValue(difference)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #fecaca;
                    background:#fef2f2;
                  ">
                    <div style="font-size:12px;color:#991b1b;">
                      VAT Difference
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#991b1b;
                    ">
                      ${formatValue(vatDifference)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #e5e7eb;
                    background:#ffffff;
                  ">
                    <div style="font-size:12px;color:#64748b;">
                      ERPNext Net Value
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#0f172a;
                    ">
                      ${formatValue(erpNet)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #e5e7eb;
                    background:#ffffff;
                  ">
                    <div style="font-size:12px;color:#64748b;">
                      eTIMS Net Value
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#0f172a;
                    ">
                      ${formatValue(etimsNet)}
                    </div>
                  </div>

                  <div style="
                    padding:16px;
                    border-radius:14px;
                    border:1px solid #fcd34d;
                    background:#fffbeb;
                  ">
                    <div style="font-size:12px;color:#92400e;">
                      Difference Percentage
                    </div>

                    <div style="
                      margin-top:8px;
                      font-size:24px;
                      font-weight:700;
                      color:#92400e;
                    ">
                      ${differencePercent.toFixed(2)}%
                    </div>
                  </div>
                </div>
              </div>

              <div style="
                border:1px solid #fde68a;
                background:#fffbeb;
                border-radius:18px;
                padding:20px;
              ">
                <div style="
                  font-size:17px;
                  font-weight:700;
                  color:#92400e;
                  margin-bottom:14px;
                ">
                  Potential Causes Detected
                </div>

                <ul style="
                  margin:0;
                  padding-left:20px;
                  color:#78350f;
                  font-size:14px;
                  line-height:1.8;
                ">
                  ${issueNotes.join("")}
                </ul>
              </div>

              </div>
            </div>
          `,
                },
              ],
              primary_action_label: __("Queue Correction"),
              secondary_action_label: __("Cancel"),
              secondary_action: () => {
                dialog.hide();
              },
              primary_action: () => {
                dialog.hide();

                showSettingsModalAndExecute(
                  "Correction Credit Note on eTIMS",
                  activeSetting,
                  (settings_name) => ({
                    method:
                      "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.verify_invoice_details",
                    args: {
                      document_name: frm.doc.name,
                      invoice_type: "Sales Invoice",
                      settings_name: settings_name,
                      company: frm.doc.company,
                    },
                    success_msg: "Verification and correction queued",
                  }),
                );
              },
            });

            dialog.set_secondary_action(() => {
              dialog.hide();
            });

            dialog.show();
          },
          __("eTims Actions"),
        );
      }
    }
  },
});

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  if (settings.length === 1) {
    const { method, args, success_msg } = getCallArgs(settings[0].name);

    frappe.call({
      method: method,
      args: args,
      freeze: true,
      freeze_message: "Processing...",
      callback: () => frappe.msgprint(__(success_msg)),
      error: (err) => {
        console.error(err);
        frappe.msgprint(__("An error occurred during the request."));
      },
    });

    return;
  }

  const dialog = new frappe.ui.Dialog({
    title: __(title),
    fields: [
      {
        label: __("Select eTims Settings"),
        fieldname: "settings_name",
        fieldtype: "Select",
        options: settings.map((s) => ({
          label: `${s.company} (${s.name})`,
          value: s.name,
        })),
        reqd: 1,
        default: settings[0]?.name,
      },
    ],
    primary_action_label: __("Proceed"),
    primary_action: ({ settings_name }) => {
      dialog.hide();

      const { method, args, success_msg } = getCallArgs(settings_name);

      frappe.call({
        method: method,
        args: args,
        freeze: true,
        freeze_message: "Processing...",
        callback: () => frappe.msgprint(__(success_msg)),
        error: (err) => {
          console.error(err);
          frappe.msgprint(__("An error occurred during the request."));
        },
      });
    },
  });

  dialog.show();
}

frappe.ui.form.on(childDoctype, {
  item_code: function (frm, cdt, cdn) {
    const item = locals[cdt][cdn].item_code;
    const taxationType = locals[cdt][cdn].custom_taxation_type;

    if (!taxationType) {
      frappe.db.get_value(
        "Item",
        { item_code: item },
        ["custom_taxation_type"],
        (response) => {
          locals[cdt][cdn].custom_taxation_type = response.custom_taxation_type;
          locals[cdt][cdn].custom_taxation_type_code =
            response.custom_taxation_type;
        },
      );
    }
  },

  custom_packaging_unit: async function (frm, cdt, cdn) {
    const packagingUnit = locals[cdt][cdn].custom_packaging_unit;

    if (packagingUnit) {
      frappe.db.get_value(
        packagingUnitDoctypeName,
        {
          name: packagingUnit,
        },
        ["code"],
        (response) => {
          const code = response.code;
          locals[cdt][cdn].custom_packaging_unit_code = code;
          frm.refresh_field("custom_packaging_unit_code");
        },
      );
    }
  },

  custom_unit_of_quantity: function (frm, cdt, cdn) {
    const unitOfQuantity = locals[cdt][cdn].custom_unit_of_quantity;

    if (unitOfQuantity) {
      frappe.db.get_value(
        unitOfQuantityDoctypeName,
        {
          name: unitOfQuantity,
        },
        ["code"],
        (response) => {
          const code = response.code;
          locals[cdt][cdn].custom_unit_of_quantity_code = code;
          frm.refresh_field("custom_unit_of_quantity_code");
        },
      );
    }
  },
});

async function updateTaxAmountLabel(frm) {
  try {
    const defaultCompany = frappe.defaults.get_user_default("Company");

    if (!defaultCompany) return;

    const { message: companyDoc } = await frappe.db.get_value(
      "Company",
      defaultCompany,
      "default_currency",
    );

    if (companyDoc?.default_currency) {
      const currency = companyDoc.default_currency;

      frm.fields_dict.items.grid.update_docfield_property(
        "custom_tax_amount",
        "label",
        `Tax Amount (${currency})`,
      );
    }
  } catch (error) {
    console.error("Error updating Tax Amount label:", error);
  }
}

async function renderEtimsSummary(frm) {
  if (!frm.doc.name || frm.is_new()) return null;

  const htmlField = frm.fields_dict.etims_summary;

  if (!htmlField) return null;

  htmlField.$wrapper.html(`
    <div style="padding:20px;text-align:center;">
      <div class="spinner-border text-primary"></div>
      <div style="margin-top:10px;">Loading eTIMS Summary...</div>
    </div>
  `);

  try {
    const postingDate = frappe.datetime.str_to_obj(frm.doc.posting_date);

    const creationDate = frappe.datetime.str_to_obj(
      (frm.doc.creation || "").split(" ")[0],
    );

    const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());

    const threeMonthsBack = frappe.datetime.add_months(
      frm.doc.posting_date,
      -3,
    );

    const startDate =
      creationDate && creationDate < postingDate
        ? frappe.datetime.obj_to_str(creationDate)
        : threeMonthsBack;

    const endDate =
      postingDate && postingDate < today
        ? frm.doc.posting_date
        : frappe.datetime.get_today();

    const response = await frappe.call({
      method: "frappe.desk.query_report.run",
      args: {
        report_name: "eTIMS Sales Ledger",
        filters: {
          company: frm.doc.company,
          from_date: startDate,
          to_date: endDate,
          sales_invoice: frm.doc.name,
          show_details: 1,
        },
      },
      freeze: false,
    });

    const rows = response.message.result || [];

    const totalRow = rows.find((d) => d.sales_invoice === "TOTAL") || {};

    const detailRows = rows.filter(
      (d) =>
        d.indent === 1 &&
        (flt(d.etims_invoice_amount) ||
          flt(d.etims_credit_amount) ||
          flt(d.etims_total_tax)),
    );

    const currency = "KES";

    const formatCurrency = (value) => format_currency(value || 0, currency);

    const getIndicatorColor = (value) =>
      Math.abs(value || 0) > 1 ? "#dc2626" : "#16a34a";

    const differenceColor = getIndicatorColor(totalRow.difference);

    const taxDifferenceColor = getIndicatorColor(totalRow.tax_difference);

    const erpTotal =
      Math.abs(flt(totalRow.erp_invoice_period_amount || 0)) +
      Math.abs(flt(totalRow.erp_credit_period_amount || 0));

    const differencePercent =
      erpTotal > 0
        ? (Math.abs(flt(totalRow.difference || 0)) / erpTotal) * 100
        : 0;

    const hasSignificantMismatch = differencePercent > 0.5;

    const detailRowsHtml = detailRows.length
      ? detailRows
          .map((row, index) => {
            const signedBadge = row.is_signed
              ? `
                <span style="
                  background:#dcfce7;
                  color:#166534;
                  padding:4px 10px;
                  border-radius:999px;
                  font-size:11px;
                  font-weight:700;
                ">
                  Signed
                </span>
              `
              : `
                <span style="
                  background:#fee2e2;
                  color:#991b1b;
                  padding:4px 10px;
                  border-radius:999px;
                  font-size:11px;
                  font-weight:700;
                ">
                  Not Signed
                </span>
              `;

            return `
              <tr style="
                border-bottom:1px solid #e5e7eb;
                background:${index % 2 === 0 ? "#ffffff" : "#f8fafc"};
              ">
                <td style="padding:12px;font-size:12px;">
                  ${frappe.datetime.str_to_user(row.invoice_date)}
                </td>

                <td style="padding:12px;font-size:12px;font-weight:600;">
                  ${row.customer || "-"}
                </td>

                <td style="padding:12px;font-size:12px;">
                  ${row.type || "-"}
                </td>

                <td style="padding:12px;font-size:12px;text-align:right;font-weight:600;">
                  ${formatCurrency(row.etims_invoice_amount)}
                </td>

                <td style="padding:12px;font-size:12px;text-align:right;font-weight:600;">
                  ${formatCurrency(row.etims_credit_amount)}
                </td>

                <td style="padding:12px;font-size:12px;text-align:right;font-weight:600;">
                  ${formatCurrency(row.etims_total_tax)}
                </td>

                <td style="padding:12px;font-size:12px;">
                  ${row.reference_number || "-"}
                </td>

                <td style="padding:12px;font-size:12px;">
                  ${row.scu_invoice_number || "-"}
                </td>

                <td style="padding:12px;text-align:center;">
                  ${signedBadge}
                </td>
              </tr>
            `;
          })
          .join("")
      : `
        <tr>
          <td colspan="9" style="
            padding:20px;
            text-align:center;
            color:#64748b;
          ">
            No eTIMS records found
          </td>
        </tr>
      `;

    htmlField.$wrapper.html(`
      <div style="
        display:flex;
        flex-direction:column;
        gap:16px;
      ">

        <div style="
          border:1px solid #dbeafe;
          background:linear-gradient(135deg,#eff6ff 0%,#ffffff 100%);
          border-radius:16px;
          padding:20px;
        ">
          <div style="
            display:flex;
            justify-content:space-between;
            align-items:center;
            flex-wrap:wrap;
            gap:10px;
          ">
            <div>
              <div style="
                font-size:22px;
                font-weight:700;
                color:#0f172a;
              ">
                eTIMS Sales Ledger
              </div>

              <div style="
                margin-top:4px;
                font-size:13px;
                color:#64748b;
              ">
                ${startDate} → ${endDate}
              </div>
            </div>

            <div style="
              padding:10px 16px;
              border-radius:999px;
              background:${hasSignificantMismatch ? "#fee2e2" : "#dcfce7"};
              color:${hasSignificantMismatch ? "#991b1b" : "#166534"};
              font-weight:700;
              font-size:13px;
            ">
              ${totalRow.reconciliation_status || "Matched"}
            </div>
          </div>
        </div>

        <div style="
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
          gap:14px;
        ">

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #e2e8f0;
            background:#ffffff;
          ">
            <div style="font-size:12px;color:#64748b;">
              ERPNext Invoice Amount
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#0f172a;
            ">
              ${formatCurrency(totalRow.erp_invoice_period_amount)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #e2e8f0;
            background:#ffffff;
          ">
            <div style="font-size:12px;color:#64748b;">
              ERPNext Credit Notes
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#0f172a;
            ">
              ${formatCurrency(totalRow.erp_credit_period_amount)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #e2e8f0;
            background:#ffffff;
          ">
            <div style="font-size:12px;color:#64748b;">
              ERPNext VAT
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#0f172a;
            ">
              ${formatCurrency(totalRow.erp_tax_amount)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #bfdbfe;
            background:#eff6ff;
          ">
            <div style="font-size:12px;color:#1d4ed8;">
              eTIMS Invoice Amount
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#1e3a8a;
            ">
              ${formatCurrency(totalRow.etims_invoice_amount)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #bfdbfe;
            background:#eff6ff;
          ">
            <div style="font-size:12px;color:#1d4ed8;">
              eTIMS Credit Notes
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#1e3a8a;
            ">
              ${formatCurrency(totalRow.etims_credit_amount)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #bfdbfe;
            background:#eff6ff;
          ">
            <div style="font-size:12px;color:#1d4ed8;">
              eTIMS VAT
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:#1e3a8a;
            ">
              ${formatCurrency(totalRow.etims_total_tax)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #fecaca;
            background:#fef2f2;
          ">
            <div style="
              font-size:12px;
              color:${differenceColor};
            ">
              Difference
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:${differenceColor};
            ">
              ${formatCurrency(totalRow.difference)}
            </div>
          </div>

          <div style="
            border-radius:14px;
            padding:18px;
            border:1px solid #fecaca;
            background:#fef2f2;
          ">
            <div style="
              font-size:12px;
              color:${taxDifferenceColor};
            ">
              VAT Difference
            </div>

            <div style="
              margin-top:8px;
              font-size:28px;
              font-weight:700;
              color:${taxDifferenceColor};
            ">
              ${formatCurrency(totalRow.tax_difference)}
            </div>
          </div>
        </div>

        <div style="
          margin-top:8px;
          border:1px solid #e5e7eb;
          border-radius:16px;
          overflow:hidden;
          background:#ffffff;
        ">

          <div style="
            padding:18px 20px;
            border-bottom:1px solid #e5e7eb;
            background:#f8fafc;
            font-size:18px;
            font-weight:700;
            color:#0f172a;
          ">
            eTIMS Ledger Entries
          </div>

          <div style="
            overflow:auto;
            max-height:700px;
          ">
            <table style="
              width:100%;
              border-collapse:collapse;
              min-width:1200px;
            ">

              <thead style="
                position:sticky;
                top:0;
                z-index:2;
                background:#f1f5f9;
              ">
                <tr>
                  <th style="padding:14px;text-align:left;font-size:12px;color:#475569;">
                    Invoice Date
                  </th>

                  <th style="padding:14px;text-align:left;font-size:12px;color:#475569;">
                    Customer
                  </th>

                  <th style="padding:14px;text-align:left;font-size:12px;color:#475569;">
                    Type
                  </th>

                  <th style="padding:14px;text-align:right;font-size:12px;color:#475569;">
                    Invoice Amount
                  </th>

                  <th style="padding:14px;text-align:right;font-size:12px;color:#475569;">
                    Credit Amount
                  </th>

                  <th style="padding:14px;text-align:right;font-size:12px;color:#475569;">
                    VAT
                  </th>

                  <th style="padding:14px;text-align:left;font-size:12px;color:#475569;">
                    Reference No
                  </th>

                  <th style="padding:14px;text-align:left;font-size:12px;color:#475569;">
                    SCU Invoice No
                  </th>

                  <th style="padding:14px;text-align:center;font-size:12px;color:#475569;">
                    Status
                  </th>
                </tr>
              </thead>

              <tbody>
                ${detailRowsHtml}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `);

    return {
      hasSignificantMismatch,
      differencePercent,
      totalRow,
    };
  } catch (error) {
    console.error(error);

    htmlField.$wrapper.html(`
      <div style="
        padding:18px;
        border-radius:12px;
        border:1px solid #fecaca;
        background:#fef2f2;
        color:#991b1b;
        font-weight:600;
      ">
        Failed to load eTIMS Summary
      </div>
    `);

    return null;
  }
}
