document.addEventListener('DOMContentLoaded', () => {
  let currentStep = 1;
  const totalSteps = 6;
  const steps = document.querySelectorAll('.wizard-step');
  const dots = document.querySelectorAll('.progress-dot');

  window.goToStep = (n) => {
    if (n < 1 || n > totalSteps) return;

    // Basic validation for "Next"
    if (n > currentStep) {
        const currentInputs = steps[currentStep-1].querySelectorAll('input[required], select[required]');
        let valid = true;
        currentInputs.forEach(input => {
            if (!input.checkValidity()) {
                input.reportValidity();
                valid = false;
            }
        });
        if (!valid) return;
    }

    steps[currentStep-1].classList.remove('active');
    currentStep = n;
    steps[currentStep-1].classList.add('active');

    updateProgress();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  function updateProgress() {
    dots.forEach((dot, idx) => {
      dot.classList.remove('active', 'complete');
      if (idx + 1 < currentStep) dot.classList.add('complete');
      if (idx + 1 === currentStep) dot.classList.add('active');
    });
  }

  window.applyLocationPreset = (type, event) => {
    const depSelect = document.querySelector('select[name="deployment_mode"]');
    const accSelect = document.querySelector('select[name="access_mode"]');
    const behindNat = document.querySelector('input[name="behind_nat_raw"]');
    const details = document.getElementById('location-details');
    const nextBtn = document.getElementById('step-4-next');

    // UI selection visual feedback
    document.querySelectorAll('.big-choice-card').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');

    if (type === 'office') {
        depSelect.value = 'office';
        accSelect.value = 'local_network';
        behindNat.checked = true;
        document.getElementById('location-label-text').textContent = "Office Access Address";
        document.getElementById('location-help-text').textContent = "Use the local name or IP address people will type inside the office.";
        document.getElementById('external_host').value = document.querySelector('.wizard-form')?.dataset.detectedHost || "";
    } else {
        depSelect.value = 'public_server';
        accSelect.value = 'public_domain';
        behindNat.checked = false;
        document.getElementById('location-label-text').textContent = "Business Domain Name";
        document.getElementById('location-help-text').textContent = "Recommended for production HTTPS, Webphone, and remote access.";
        document.getElementById('external_host').placeholder = "e.g. pbx.mycompany.com";
        document.getElementById('external_host').value = "";
    }

    details.style.display = 'block';
    nextBtn.style.display = 'inline-flex';
    updateCustomCertificateFields();
  };

  window.toggleAdvancedNetwork = (event) => {
      const adv = document.getElementById('advanced-network-options');
      const isVisible = adv.style.display === 'block';
      adv.style.display = isVisible ? 'none' : 'block';
      event.currentTarget.textContent = isVisible ? 'Show advanced settings' : 'Hide advanced settings';
      updateCustomCertificateFields();
  };

  function updateCustomCertificateFields() {
      const accessMode = document.querySelector('select[name="access_mode"]');
      const uploadBlock = document.getElementById('custom-certificate-upload');
      const certInput = document.getElementById('custom_certificate_file');
      const keyInput = document.getElementById('custom_private_key_file');
      const showUploads = accessMode?.value === 'private_self_hosted';
      if (uploadBlock) uploadBlock.style.display = showUploads ? 'block' : 'none';
      if (certInput) certInput.required = showUploads;
      if (keyInput) keyInput.required = showUploads;
  }

  document.querySelector('select[name="access_mode"]')?.addEventListener('change', updateCustomCertificateFields);
  updateCustomCertificateFields();

  window.generateSummary = () => {
      const box = document.getElementById('final-summary-box');
      const data = {
          "Admin User": document.getElementById('admin_username').value,
          "Admin Email": document.getElementById('admin_email').value,
          "Company": document.getElementById('company_name').value,
          "PBX Address": document.getElementById('external_host').value,
          "Location": document.querySelector('select[name="deployment_mode"]').value,
          "Behind NAT": document.querySelector('input[name="behind_nat_raw"]').checked ? "Yes" : "No"
      };

      let html = '';
      for (const [k, v] of Object.entries(data)) {
          html += `<div class="setup-summary-item"><span>${k}</span><strong>${v}</strong></div>`;
      }
      box.innerHTML = html;
  };
});
