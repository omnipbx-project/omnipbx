(() => {
  const page = document.querySelector("[data-followup-page]");
  const list = document.getElementById("followup-list");
  if (!page || !list) return;

  const escapeText = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

  const statusMarkup = (row) => {
    if (row.followup_status === "done") {
      return `<span class="followup-badge done">Done</span><small>Completed by ${escapeText(row.completed_by || "team")}</small>`;
    }
    if (row.followup_status === "in_progress") {
      return `<span class="followup-badge progress">In Progress</span><small>By ${escapeText(row.assigned_to || "team member")}</small>`;
    }
    if (row.followup_status === "answered_later") {
      return '<span class="followup-badge answered">Answered Later</span><small>No callback needed</small>';
    }
    return '<span class="followup-badge needed">Needs Callback</span><small>Not taken yet</small>';
  };

  const actionsMarkup = (row) => {
    const linkedid = encodeURIComponent(row.linkedid);
    if (row.followup_status === "done" || row.followup_status === "answered_later") return "";
    const take = row.followup_status === "needs_callback"
      ? `<button type="button" data-action="take" data-linkedid="${linkedid}">Take</button>`
      : "";
    return `
      ${take}
      <a class="button-link secondary" href="tel:${escapeText(row.caller_number)}">Call</a>
      <button type="button" class="secondary" data-action="done" data-linkedid="${linkedid}">Done</button>
    `;
  };

  const renderRows = (rows) => {
    if (!rows.length) {
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">∅</div>
          <div class="empty-title">No follow ups</div>
          <div class="empty-copy">Missed and abandoned calls will appear here only while they still need a callback.</div>
        </div>
      `;
      return;
    }
    list.innerHTML = rows.map((row) => `
      <article class="followup-item" data-linkedid="${escapeText(row.linkedid)}">
        <div class="followup-main">
          <div class="followup-avatar">${escapeText(String(row.caller_number || "?").slice(0, 1))}</div>
          <div>
            <h4>${escapeText(row.caller_number)}</h4>
            <p>${escapeText(row.callback_reason)}${row.target ? ` · ${escapeText(row.target)}` : ""}</p>
            <small>${escapeText(row.call_time)} · ${escapeText(row.route_name || row.queue_name || row.ivr_name || "Inbound")}</small>
          </div>
        </div>
        <div class="followup-state">${statusMarkup(row)}</div>
        <div class="followup-actions">${actionsMarkup(row)}</div>
      </article>
    `).join("");
  };

  const refresh = async () => {
    const params = new URLSearchParams(window.location.search);
    params.set("open_only", page.dataset.openOnly || "1");
    const response = await fetch(`/api/callbacks?${params.toString()}`, { headers: { "Accept": "application/json" } });
    if (!response.ok) return;
    const data = await response.json();
    renderRows(data.rows || []);
  };

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    button.disabled = true;
    const response = await fetch(`/api/callbacks/${button.dataset.linkedid}/${button.dataset.action}`, { method: "POST" });
    if (response.ok) {
      await refresh();
    } else {
      button.disabled = false;
    }
  });

  window.setInterval(refresh, 5000);
})();
