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
              settings_name: frm.doc.name,
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
              settings_name: frm.doc.name,
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
                  settings_name: frm.doc.name,
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
              "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.search_clusters",
            args: {
              settings_name: frm.doc.name,
              request_data: {
                document_name: frm.doc.name,
                company_name: companyName,
                branch_id: frm.doc.bhfid,
              },
            },
            freeze: true,
            freeze_message: __("Fetching clusters..."),
            callback: (response) => {
              if (response.message) {
                showClusterMatchingModal(response.message, frm);
              }
            },
            error: (error) => {
              frappe.msgprint(__("Error fetching clusters"));
              console.error(error);
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
            args: { settings_name: frm.doc.name },

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
          freeze: true,
          freeze_message: __("Syncing user details..."),
          callback: function (response) {
            if (response) {
              // Show toast notification
              frappe.show_alert(
                {
                  message: __("User details synced successfully"),
                  indicator: "green",
                },
                5
              );

              frm.refresh();
            } else {
              frappe.msgprint({
                title: __("Error"),
                indicator: "red",
                message: __("Failed to sync user details."),
              });
            }
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

function showClusterMatchingModal(clusterData, form) {
  let tableData = clusterData.map((cluster) => {
    return {
      cluster_id: cluster.id,
      cluster_name: cluster.name,
      organisation: cluster.organisation,
      company: "",
    };
  });

  let fields = [
    {
      fieldname: "cluster_table",
      fieldtype: "Table",
      label: __("Match Clusters to Companies"),
      data: tableData,
      cannot_add_rows: 1,
      in_place_edit: true,
      fields: [
        {
          fieldname: "cluster_id",
          label: __("Cluster ID"),
          fieldtype: "Data",
          in_list_view: 1,
          read_only: 1,
          columns: 2,
        },
        {
          fieldname: "organisation",
          label: __("Organisation ID"),
          fieldtype: "Data",
          in_list_view: 1,
          read_only: 1,
          columns: 2,
        },
        {
          fieldname: "cluster_name",
          label: __("Cluster Name"),
          fieldtype: "Data",
          in_list_view: 1,
          read_only: 1,
          columns: 3,
        },
        {
          fieldname: "company",
          label: __("Company"),
          fieldtype: "Link",
          in_list_view: 1,
          options: "Company",
          reqd: 1,
          columns: 3,
        },
      ],
    },
  ];

  let dialog = new frappe.ui.Dialog({
    title: __("Match Clusters to Companies"),
    fields: fields,
    primary_action_label: __("Submit"),
    primary_action: function () {
      let matched_data = dialog.get_value("cluster_table");

      frappe.call({
        method:
          "kenya_compliance_via_slade.kenya_compliance_via_slade.doctype.navari_kra_etims_settings.navari_kra_etims_settings.update_companies_with_cluster_info",
        args: {
          matched_data: matched_data,
          settings_name: form.doc.name,
        },
        freeze: true,
        freeze_message: __("Updating companies..."),
        callback: function (update_response) {
          if (update_response.message.success) {
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.search_organisations_request",
              args: {
                settings_name: form.doc.name,
                request_data: {
                  document_name: form.doc.name,
                },
              },
              freeze: true,
              freeze_message: __("Matching clusters..."),
              callback: function (r) {
                frappe.msgprint({
                  title: __("Success"),
                  indicator: "green",
                  message: __(
                    "Clusters matched successfully. System will now fetch branches, departments and workstations in the background."
                  ),
                });
                dialog.hide();
              },
              error: function (error) {
                frappe.msgprint(__("Error fetching organizations"));
                console.error(error);
              },
            });
          } else {
            frappe.msgprint({
              title: __("Update Failed"),
              indicator: "red",
              message:
                __("Failed to update companies: ") +
                update_response.message.message,
            });
          }
        },
        error: function (error) {
          frappe.msgprint(__("Error updating companies"));
          console.error(error);
        },
      });
    },
  });

  dialog.$wrapper.find(".modal-dialog").css("max-width", "max-content");
  dialog.$wrapper.find(".modal-content").css("width", "800px");
  dialog.show();
}
