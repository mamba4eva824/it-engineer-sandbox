const REFRESH_INTERVAL_MS = 60_000;

let onboardingData = [];
let offboardingData = [];
let onboardingSort = { key: "startDate", asc: true };
let offboardingSort = { key: "endDate", asc: true };

function formatTimestamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `Last updated: ${d.toLocaleString()}`;
}

function progressWidth(used, purchased) {
  if (purchased == null || used == null || purchased === 0) return 0;
  return Math.min(100, Math.round((used / purchased) * 100));
}

function renderLicenseCards(data) {
  const container = document.getElementById("license-cards");
  const ts = document.getElementById("licenses-timestamp");

  if (!data?.services?.length) {
    container.innerHTML = '<p class="empty">No license data available.</p>';
    return;
  }

  container.innerHTML = data.services
    .map((svc) => {
      const pct = progressWidth(svc.used, svc.purchased);
      const available =
        svc.available != null ? svc.available : svc.purchased == null ? "—" : "—";
      const purchased = svc.purchased != null ? svc.purchased : "—";
      const used = svc.used != null ? svc.used : "—";
      const util =
        svc.utilizationPct != null ? `${svc.utilizationPct}% utilized` : "";

      let body = "";
      if (svc.status === "error") {
        body = `<p class="card-error">${escapeHtml(svc.detail || "API error")}</p>`;
      } else {
        body = `
          <div class="license-stats">
            <div class="stat"><div class="value">${used}</div><div class="label">Used</div></div>
            <div class="stat"><div class="value">${purchased}</div><div class="label">Purchased</div></div>
            <div class="stat"><div class="value">${available}</div><div class="label">Available</div></div>
          </div>
          ${
            svc.purchased != null
              ? `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>`
              : ""
          }
          ${util ? `<p class="card-detail">${util}</p>` : ""}
          ${svc.detail ? `<p class="card-detail">${escapeHtml(svc.detail)}</p>` : ""}
        `;
      }

      return `
        <article class="license-card status-${svc.status}">
          <h3>${escapeHtml(svc.label)}</h3>
          ${body}
        </article>
      `;
    })
    .join("");

  ts.textContent = formatTimestamp(data.generatedAt);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function sortRows(rows, key, asc) {
  return [...rows].sort((a, b) => {
    const av = a[key] ?? "";
    const bv = b[key] ?? "";
    if (typeof av === "number" && typeof bv === "number") {
      return asc ? av - bv : bv - av;
    }
    const cmp = String(av).localeCompare(String(bv));
    return asc ? cmp : -cmp;
  });
}

function renderOnboardingTable() {
  const tbody = document.querySelector("#onboarding-table tbody");
  const errorEl = document.getElementById("onboarding-error");

  if (onboardingData.error) {
    errorEl.textContent = onboardingData.error;
    errorEl.classList.remove("hidden");
  } else {
    errorEl.classList.add("hidden");
  }

  const rows = sortRows(onboardingData.users || [], onboardingSort.key, onboardingSort.asc);

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">No users in onboarding pipeline.</td></tr>';
    return;
  }

  tbody.innerHTML = rows
    .map((u) => {
      const badge =
        u.badge === "missed_activation"
          ? ' <span class="badge badge-missed">Missed activation</span>'
          : "";
      const days =
        u.daysUntilStart != null
          ? u.daysUntilStart < 0
            ? `${Math.abs(u.daysUntilStart)}d ago`
            : `${u.daysUntilStart}d`
          : "—";
      return `<tr>
        <td>${escapeHtml(u.name || "—")}${badge}</td>
        <td>${escapeHtml(u.email || "—")}</td>
        <td>${escapeHtml(u.department || "—")}</td>
        <td>${escapeHtml(u.roleTitle || "—")}</td>
        <td>${escapeHtml(u.status || "—")}</td>
        <td>${escapeHtml(u.startDate || "—")}</td>
        <td>${days}</td>
      </tr>`;
    })
    .join("");
}

function renderOffboardingTable() {
  const tbody = document.querySelector("#offboarding-table tbody");
  const errorEl = document.getElementById("offboarding-error");

  if (offboardingData.error) {
    errorEl.textContent = offboardingData.error;
    errorEl.classList.remove("hidden");
  } else {
    errorEl.classList.add("hidden");
  }

  const rows = sortRows(offboardingData.users || [], offboardingSort.key, offboardingSort.asc);

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No users scheduled for offboarding.</td></tr>';
    return;
  }

  tbody.innerHTML = rows
    .map((u) => {
      const badge =
        u.badge === "due_today_or_overdue"
          ? ' <span class="badge badge-due">Due today / overdue</span>'
          : "";
      const days =
        u.daysUntilEnd != null
          ? u.daysUntilEnd <= 0
            ? u.daysUntilEnd === 0
              ? "Today"
              : `${Math.abs(u.daysUntilEnd)}d overdue`
            : `${u.daysUntilEnd}d`
          : "—";
      return `<tr>
        <td>${escapeHtml(u.name || "—")}${badge}</td>
        <td>${escapeHtml(u.email || "—")}</td>
        <td>${escapeHtml(u.department || "—")}</td>
        <td>${escapeHtml(u.status || "—")}</td>
        <td>${escapeHtml(u.endDate || "—")}</td>
        <td>${days}</td>
      </tr>`;
    })
    .join("");
}

function setupTableSort(tableId, dataKey, sortState, renderFn) {
  document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortState.key === key) {
        sortState.asc = !sortState.asc;
      } else {
        sortState.key = key;
        sortState.asc = true;
      }
      renderFn();
    });
  });
}

async function fetchJson(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return resp.json();
}

async function refreshAll() {
  const status = document.getElementById("refresh-status");
  status.textContent = "Refreshing…";

  try {
    const [licenses, onboarding, offboarding] = await Promise.all([
      fetchJson("/api/licenses"),
      fetchJson("/api/pipeline/onboarding"),
      fetchJson("/api/pipeline/offboarding"),
    ]);

    renderLicenseCards(licenses);
    onboardingData = onboarding;
    offboardingData = offboarding;
    renderOnboardingTable();
    renderOffboardingTable();
    status.textContent = `Updated ${new Date().toLocaleTimeString()} · auto-refresh every 60s`;
  } catch (err) {
    status.textContent = `Refresh failed: ${err.message}`;
  }
}

document.getElementById("refresh-btn").addEventListener("click", refreshAll);
setupTableSort("onboarding-table", "onboarding", onboardingSort, renderOnboardingTable);
setupTableSort("offboarding-table", "offboarding", offboardingSort, renderOffboardingTable);

refreshAll();
setInterval(refreshAll, REFRESH_INTERVAL_MS);
