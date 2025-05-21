// Copyright (c) 2024, Navari Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Navari KRA eTims Settings", {
  refresh: function (frm) {
    const companyName = frm.doc.company;

    frm.fields_dict.get_new_token.$wrapper
      .find("button")
      .on("click", function () {
        frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.update_navari_settings_with_token",
          args: {
            docname: frm.doc.name,
            skip_checks: true,
          },
        });
      });

    frm.fields_dict.reset_auth_password.$wrapper
      .find("button")
      .on("click", function () {
        frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.reset_auth_password",
          args: {
            docname: frm.doc.name,
          },
        });
      });

    if (!frm.is_new() && frm.doc.is_active) {
      frm.add_custom_button(
        __("Get Notices"),
        function () {
          frappe.call({
            method:
              "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.perform_notice_search",
            args: {
              request_data: {
                document_name: frm.doc.name,
                company_name: companyName,
                branch_id: frm.doc.bhfid,
              },
            },
            callback: (response) => {},
            error: (error) => {
              // Error Handling is Defered to the Server
            },
          });
        },
        __("eTims Actions")
      );

      frm.add_custom_button(
        __("Get Codes"),
        function () {
          frappe.call({
            method:
              "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.refresh_code_lists",
            args: {
              request_data: {
                document_name: frm.doc.name,
                company_name: companyName,
                branch_id: frm.doc.bhfid,
              },
            },
            callback: (response) => {
              frappe.call({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.get_item_classification_codes",
                args: {
                  request_data: {
                    document_name: frm.doc.name,
                    company_name: companyName,
                    branch_id: frm.doc.bhfid,
                  },
                },
                callback: (response) => {},
                error: (error) => {
                  // Error Handling is Defered to the Server
                },
              });
            },
            error: (error) => {
              // Error Handling is Defered to the Server
            },
          });
        },
        __("eTims Actions")
      );
      frm.add_custom_button(
        __("Sync Organisation Units"),
        function () {
          frappe.call({
            method:
              "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.search_organisations_request",
            args: {
              request_data: {
                document_name: frm.doc.name,
                company_name: companyName,
                branch_id: frm.doc.bhfid,
              },
            },
            callback: (response) => {},
            error: (error) => {
              // Error Handling is Defered to the Server
            },
          });
        },
        __("eTims Actions")
      );

      frm.add_custom_button(
        __("Submit Mode of Payments"),
        function () {
          frappe.call({
            method:
              "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.send_all_mode_of_payments",
            args: {},

            callback: (response) => {},
            error: (error) => {
              // Error Handling is Defered to the Server
            },
          });
        },
        __("eTims Actions")
      );
    }

    frm.add_custom_button(
      __("Sync User Details"),
      function () {
        frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.user_details_fetch",
          args: {
            document_name: frm.doc.name,
          },
        });
      },
      __("eTims Actions")
    );

    frm.add_custom_button(
      __("Get Auth Token"),
      function () {
        frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.update_navari_settings_with_token",
          args: {
            docname: frm.doc.name,
            skip_checks: true,
          },
        });
      },
      __("eTims Actions")
    );

    frm.add_custom_button(
      __("Ping Server"),
      function () {
        frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.ping_server",
          args: {
            request_data: {
              server_url: frm.doc.server_url + "/alive",
              auth_url: frm.doc.auth_server_url,
            },
          },
        });
      },
      __("eTims Actions")
    );

    frm.set_query("bhfid", function () {
      return {
        filters: [["Branch", "custom_is_etims_branch", "=", 1]],
      };
    });
  },
  sandbox: function (frm) {
    const sandboxFieldValue = parseInt(frm.doc.sandbox);
    const sandboxServerUrl = "https://api.erp.release.slade360edi.com";
    const productionServerUrl = "https://api.erp.slade360.co.ke";
    const sandboxAuthUrl = "https://accounts.multitenant.slade360.co.ke";
    const productionAuthUrl = "https://accounts.edi.slade360.co.ke";

    if (sandboxFieldValue === 1) {
      frm.set_value("env", "Sandbox");
      frm.set_value("server_url", sandboxServerUrl);
      frm.set_value("auth_server_url", sandboxAuthUrl);
    } else {
      frm.set_value("env", "Production");
      frm.set_value("server_url", productionServerUrl);
      frm.set_value("auth_server_url", productionAuthUrl);
    }
  },
});
