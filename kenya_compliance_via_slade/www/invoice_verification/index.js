document.addEventListener("DOMContentLoaded", function () {
  document.body.classList.add("invoice-verification-page");

  const loadingState = document.getElementById("state-loading");
  const successState = document.getElementById("state-success");
  const errorState = document.getElementById("state-error");
  const pendingState = document.getElementById("state-pending");
  const errorMessage = document.getElementById("error-message");
  const successBtn = document.getElementById("success-redirect-btn");

  const initialRedirect = document.getElementById("initial_redirect")?.value;
  const initialError = document.getElementById("initial_error")?.value;

  let redirectTimer = null;

  function handleSuccess(url) {
    loadingState.style.display = "none";
    successBtn.href = url;
    successState.style.display = "block";

    redirectTimer = setTimeout(function () {
      window.location.href = url;
    }, 3000);
  }

  if (successBtn) {
    successBtn.addEventListener("click", function (e) {
      if (redirectTimer) {
        clearTimeout(redirectTimer);
      }
    });
  }

  if (initialRedirect) {
    handleSuccess(initialRedirect);
    return;
  }

  if (initialError) {
    loadingState.style.display = "none";
    errorMessage.innerText = initialError;
    errorState.style.display = "block";
    return;
  }

  const id = document.getElementById("invoice_id")?.value;
  const key = document.getElementById("verification_key")?.value;

  if (!id || !key) {
    loadingState.style.display = "none";
    errorMessage.innerText = "Invalid verification link.";
    errorState.style.display = "block";
    return;
  }

  frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.check_invoice_submission_status",
    args: { id, key },
    callback: function (r) {
      if (!r.message) {
        loadingState.style.display = "none";
        errorMessage.innerText = "Unable to verify invoice.";
        errorState.style.display = "block";
        return;
      }

      if (r.message.error) {
        loadingState.style.display = "none";
        errorMessage.innerText = r.message.error;
        errorState.style.display = "block";
        return;
      }

      if (r.message.etims_qr_code_url) {
        handleSuccess(r.message.etims_qr_code_url);
        return;
      }

      loadingState.style.display = "none";

      document.getElementById("detail-name").innerText = r.message.name || "";
      document.getElementById("detail-customer").innerText =
        r.message.customer || "";
      document.getElementById("detail-date").innerText =
        r.message.posting_date || "";

      if (r.message.grand_total) {
        const currency = r.message.currency || "";
        document.getElementById("detail-amount").innerText =
          `${currency} ${r.message.grand_total}`.trim();
        document.getElementById("detail-amount-row").style.display = "flex";
      }

      pendingState.style.display = "block";
    },
    error: function () {
      loadingState.style.display = "none";
      errorMessage.innerText = "Unable to verify invoice.";
      errorState.style.display = "block";
    },
  });
});
