async function refreshStatus() {
  const response = await fetch('/status/data', { cache: 'no-store' });
  if (!response.ok) {
    return;
  }

  const snapshot = await response.json();
  document.getElementById('generated-at').textContent = snapshot.generated_at;

  const metricValues = {
    "Total endpoints": snapshot.summary.extensions_total,
    "Online": snapshot.summary.extensions_online,
    "Offline": snapshot.summary.extensions_offline,
    "Unknown": snapshot.summary.extensions_unknown,
  };

  document.querySelectorAll('.metric-card').forEach((card) => {
    const label = card.querySelector('strong')?.textContent?.trim();
    if (label && metricValues[label] !== undefined) {
      card.querySelector('span').textContent = metricValues[label];
    }
  });

  const tbody = document.getElementById('status-rows');
  tbody.innerHTML = snapshot.extensions.map((row) => `
    <tr>
      <td class="mono">${row.extension}</td>
      <td>${row.display_name}</td>
      <td><span class="status-pill ${row.status.toLowerCase()}">${row.status}</span></td>
      <td>${row.endpoint_state}</td>
      <td class="mono">${row.contact_uri || 'Not registered'}</td>
      <td class="mono">${row.contact_rtt || '-'}</td>
      <td class="mono">${row.transport}</td>
    </tr>
  `).join('');
}

setInterval(refreshStatus, 4000);
