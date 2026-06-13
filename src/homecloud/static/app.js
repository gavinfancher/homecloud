const state = {
  tailnet: "",
  vmSshUser: "ubuntu",
  vms: [],
  jobs: [],
  images: [],
  dashboard: null,
  selectedJobId: null,
  selectedVmid: null,
  pollTimer: null,
  activeJobId: null,
};

const TITLES = {
  overview: "Dashboard",
  vms: "Virtual machines",
  create: "Create instance",
  images: "Machine images",
  activity: "Activity log",
  settings: "Settings",
  "vm-detail": "Instance details",
};

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = (await res.text()) || detail;
    }
    throw new Error(detail);
  }
  return res.json();
}

function toast(message, kind = "ok") {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatRam(gb) {
  if (!gb) return "—";
  return `${gb} GB`;
}

function formatUptime(sec) {
  if (!sec) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function showView(view) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`view-${view}`)?.classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  document.getElementById("breadcrumb").textContent = TITLES[view] || view;
  document.getElementById("page-title").textContent = TITLES[view] || view;
}

function renderLogs(logs) {
  if (!logs?.length) return "No log output yet.";
  return logs
    .map((l) => `[${new Date(l.ts).toLocaleTimeString()}] ${l.message}`)
    .join("\n");
}

function renderStats() {
  const d = state.dashboard;
  if (!d) return;
  const s = d.stats;
  document.getElementById("stats-grid").innerHTML = `
    <div class="stat-card"><div class="label">Instances</div><div class="value">${s.total_vms}</div><div class="sub">${s.running} running · ${s.stopped} stopped</div></div>
    <div class="stat-card"><div class="label">Node</div><div class="value" style="font-size:1.1rem">${esc(d.proxmox_node)}</div><div class="sub">Storage: ${esc(d.proxmox_storage)}</div></div>
    <div class="stat-card"><div class="label">Templates</div><div class="value">${s.templates}</div><div class="sub">${d.base_image_built ? "Base image ready" : "Base image not built"}</div></div>
    <div class="stat-card"><div class="label">Tailnet</div><div class="value" style="font-size:0.95rem">${esc(d.tailscale_tailnet || "—")}</div><div class="sub">MagicDNS for all instances</div></div>`;
}

function renderOverviewActivity() {
  const jobs = state.jobs.slice(0, 6);
  const el = document.getElementById("overview-activity");
  if (!jobs.length) {
    el.innerHTML = '<p class="empty">No recent jobs.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table"><thead><tr><th>Job</th><th>Type</th><th>Status</th><th>Started</th></tr></thead><tbody>${jobs
    .map(
      (j) => `<tr data-job-id="${j.id}">
        <td><strong>${esc(j.label)}</strong></td>
        <td>${esc(j.type.replace("_", " "))}</td>
        <td><span class="badge ${j.status === "running" ? "running-job" : j.status}">${esc(j.status)}</span></td>
        <td>${formatTime(j.created_at)}</td>
      </tr>`
    )
    .join("")}</tbody></table>`;
  el.querySelectorAll("tbody tr").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedJobId = row.dataset.jobId;
      showView("activity");
      renderActivity();
    });
  });
}

function renderSetupBanner() {
  const banner = document.getElementById("setup-banner");
  const d = state.dashboard;
  if (!d) return;
  if (!d.setup_complete) {
    banner.className = "info-banner";
    banner.textContent = "Complete setup in Settings — upload your SSH public key.";
    return;
  }
  if (!d.base_image_built) {
    banner.className = "info-banner";
    banner.textContent = "Build the base image before creating instances.";
    return;
  }
  banner.className = "info-banner ok";
  banner.textContent = "Ready to create instances.";
}

function renderVmTable(filter = "") {
  const q = filter.trim().toLowerCase();
  const vms = state.vms.filter((v) => {
    if (!q) return true;
    const hay = [v.name, v.vmid, v.tailscale_ip, v.hostname, v.status].join(" ").toLowerCase();
    return hay.includes(q);
  });
  document.getElementById("vm-count").textContent = `${vms.length} instance${vms.length === 1 ? "" : "s"}`;
  const el = document.getElementById("vm-table");
  if (!vms.length) {
    el.innerHTML = '<p class="empty">No instances found.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table"><thead><tr>
    <th>Name</th><th>Status</th><th>ID</th><th>vCPU</th><th>Memory</th><th>Disk</th><th>Tailscale IP</th><th>MagicDNS</th><th>Uptime</th><th></th>
  </tr></thead><tbody>${vms
    .map((v) => {
      const mem = v.memory_gb ?? (v.memory_mb ? (v.memory_mb / 1024).toFixed(1) : "—");
      const dns = v.hostname || v.magic_dns || "—";
      return `<tr data-vmid="${v.vmid}">
        <td><strong>${esc(v.name)}</strong></td>
        <td><span class="badge ${v.status}">${esc(v.status)}</span></td>
        <td>${v.vmid}</td>
        <td>${v.cores || v.cpus || "—"}</td>
        <td>${mem} GB</td>
        <td>${v.disk_gb || "—"} GB</td>
        <td>${esc(v.tailscale_ip || v.ip || "—")}</td>
        <td><code>${esc(dns)}</code></td>
        <td>${formatUptime(v.uptime)}</td>
        <td><button class="btn sm" data-action="open">Details</button></td>
      </tr>`;
    })
    .join("")}</tbody></table>`;

  el.querySelectorAll("tbody tr").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      openVmDetail(Number(row.dataset.vmid));
    });
    row.querySelector('[data-action="open"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      openVmDetail(Number(row.dataset.vmid));
    });
  });
}

async function openVmDetail(vmid) {
  state.selectedVmid = vmid;
  showView("vm-detail");
  const vm = await api(`/vms/${vmid}`);
  const dns = vm.hostname || vm.magic_dns || "—";
  const mem = vm.memory_gb ?? (vm.memory_mb ? (vm.memory_mb / 1024).toFixed(1) : "—");
  document.getElementById("vm-detail").innerHTML = `
    <div class="panel">
      <h2>${esc(vm.name)}</h2>
      <p><span class="badge ${vm.status}">${esc(vm.status)}</span></p>
      <dl class="detail-dl">
        <dt>Instance ID</dt><dd>${vm.vmid}</dd>
        <dt>Node</dt><dd>${esc(vm.node || "—")}</dd>
        <dt>Status</dt><dd>${esc(vm.status)}</dd>
        <dt>Registered</dt><dd>${vm.registered ? "Yes" : "No (orphan)"}</dd>
        <dt>vCPUs</dt><dd>${vm.cores || vm.cpus || "—"}</dd>
        <dt>Memory</dt><dd>${mem} GB</dd>
        <dt>Boot disk</dt><dd>${vm.disk_gb || "—"} GB</dd>
        <dt>Uptime</dt><dd>${formatUptime(vm.uptime)}</dd>
      </dl>
      <div class="detail-actions">
        ${vm.status === "running"
          ? `<button class="btn" id="detail-stop">Stop</button>`
          : `<button class="btn primary" id="detail-start">Start</button>`}
        <button class="btn danger" id="detail-delete">Delete</button>
      </div>
    </div>
    <div class="panel">
      <h2>Connect</h2>
      <dl class="detail-dl">
        <dt>MagicDNS</dt><dd><code>${esc(dns)}</code></dd>
        <dt>Tailscale IP</dt><dd>${esc(vm.tailscale_ip || vm.ip || "—")}</dd>
        <dt>SSH command</dt><dd><code>ssh ${state.vmSshUser}@${esc(dns)}</code></dd>
        <dt>Image</dt><dd>${esc(vm.image_id || "homecloud-base")}</dd>
      </dl>
    </div>`;

  document.getElementById("detail-start")?.addEventListener("click", () => vmAction(vmid, "start"));
  document.getElementById("detail-stop")?.addEventListener("click", () => vmAction(vmid, "stop"));
  document.getElementById("detail-delete")?.addEventListener("click", () => vmDelete(vmid, vm.name));
}

async function vmAction(vmid, action) {
  try {
    await api(`/vms/${vmid}/${action}`, { method: "POST" });
    toast(`Instance ${action}${action.endsWith("e") ? "d" : "ed"}`);
    await refresh();
    if (state.selectedVmid === vmid) await openVmDetail(vmid);
  } catch (e) {
    toast(e.message, "err");
  }
}

async function vmDelete(vmid, name) {
  if (!confirm(`Delete instance ${name} (${vmid})?`)) return;
  try {
    await api(`/vms/${vmid}?name=${encodeURIComponent(name)}`, { method: "DELETE" });
    toast("Instance deleted");
    showView("vms");
    await refresh();
  } catch (e) {
    toast(e.message, "err");
  }
}

function renderImages() {
  const el = document.getElementById("images-grid");
  el.innerHTML = state.images
    .map(
      (img) => `<div class="image-card">
        <h3>${esc(img.name)}</h3>
        <p>${esc(img.description)}</p>
        <div class="pkg-list">${img.packages.map((p) => `<span>${esc(p)}</span>`).join("")}</div>
        <dl class="detail-dl">
          <dt>Status</dt><dd>${img.built ? `Ready (template ${img.template_id})` : "Not built"}</dd>
          <dt>Defaults</dt><dd>${img.default_cores} vCPU · ${Math.round(img.default_memory_mb / 1024)} GB · ${img.default_disk_gb} GB disk</dd>
        </dl>
        ${img.id === "homecloud-base" ? `<button class="btn primary build-btn" ${img.built ? "" : ""}>${img.built ? "Rebuild" : "Build"} base image</button>` : ""}
      </div>`
    )
    .join("");

  el.querySelector(".build-btn")?.addEventListener("click", startBuildImage);
}

async function startBuildImage() {
  try {
    const { job_id } = await api("/images/homecloud-base/build", { method: "POST" });
    state.activeJobId = job_id;
    state.selectedJobId = job_id;
    toast("Base image build started");
    showView("activity");
    startJobPolling(job_id, null);
    await refresh();
  } catch (e) {
    toast(e.message, "err");
  }
}

function renderActivity() {
  const list = document.getElementById("jobs-list");
  if (!state.jobs.length) {
    list.innerHTML = '<p class="empty">No jobs yet.</p>';
    document.getElementById("job-log").textContent = "Select a job to view logs.";
    return;
  }
  list.innerHTML = state.jobs
    .map(
      (j) => `<button class="job-item ${state.selectedJobId === j.id ? "active" : ""}" data-job-id="${j.id}">
        <div class="job-item-head"><strong>${esc(j.label)}</strong><span class="badge ${j.status === "running" ? "running-job" : j.status}">${esc(j.status)}</span></div>
        <div class="job-item-meta">${esc(j.type.replace("_", " "))} · ${formatTime(j.created_at)}</div>
      </button>`
    )
    .join("");

  list.querySelectorAll(".job-item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.selectedJobId = btn.dataset.jobId;
      renderActivity();
      const job = await api(`/jobs/${state.selectedJobId}`);
      document.getElementById("job-log").textContent = renderLogs(job.logs);
      if (job.error) document.getElementById("job-log").textContent += `\n\nERROR: ${job.error}`;
    });
  });

  if (state.selectedJobId) {
    const selected = state.jobs.find((j) => j.id === state.selectedJobId);
    if (selected) {
      api(`/jobs/${state.selectedJobId}`).then((job) => {
        document.getElementById("job-log").textContent = renderLogs(job.logs);
        if (job.error) document.getElementById("job-log").textContent += `\n\nERROR: ${job.error}`;
      });
    }
  }
}

function fqdnPreview(name) {
  const short = (name || "instance").split(".")[0];
  return state.tailnet ? `${short}.${state.tailnet}` : short;
}

function updateCreateSummary() {
  const form = document.getElementById("deploy-form");
  const fd = new FormData(form);
  const name = fd.get("name") || "instance";
  const preview = fqdnPreview(name);
  document.getElementById("preview-dns").textContent = preview;
  document.getElementById("create-summary").innerHTML = `
    <dt>Name</dt><dd>${esc(name)}</dd>
    <dt>Image</dt><dd>${esc(fd.get("image_id") || "homecloud-base")}</dd>
    <dt>Machine type</dt><dd>${fd.get("cores")} vCPU · ${fd.get("memory_gb")} GB · ${fd.get("disk_gb")} GB disk</dd>
    <dt>Region</dt><dd>${esc(state.dashboard?.proxmox_node || "—")}</dd>
    <dt>MagicDNS</dt><dd><code>${esc(preview)}</code></dd>`;
}

function bindSliders() {
  const map = [
    ["cores", "cores-out"],
    ["memory_gb", "memory-out"],
    ["disk_gb", "disk-out"],
  ];
  map.forEach(([name, outId]) => {
    const input = document.querySelector(`input[name="${name}"]`);
    const out = document.getElementById(outId);
    input.addEventListener("input", () => {
      out.textContent = input.value;
      updateCreateSummary();
    });
  });
  document.querySelector('input[name="name"]')?.addEventListener("input", updateCreateSummary);
  document.getElementById("image-select")?.addEventListener("change", updateCreateSummary);
}

function renderSettings() {
  const setup = state.dashboard;
  document.getElementById("settings-setup").classList.toggle("hidden", setup?.setup_complete);
  document.getElementById("env-info").innerHTML = `
    <dt>Tailnet</dt><dd>${esc(state.tailnet || "—")}</dd>
    <dt>Proxmox node</dt><dd>${esc(setup?.proxmox_node || "—")}</dd>
    <dt>Storage pool</dt><dd>${esc(setup?.proxmox_storage || "—")}</dd>
    <dt>SSH user</dt><dd>${esc(state.vmSshUser)}</dd>
    <dt>Base image</dt><dd>${setup?.base_image_built ? "Built" : "Not built"}</dd>`;
  api("/ssh-config").then(({ config }) => {
    document.getElementById("ssh-config-preview").textContent = config || "# No registered VMs yet";
  });
}

function startJobPolling(jobId, logEl) {
  stopJobPolling();
  state.activeJobId = jobId;
  const tick = async () => {
    const job = await api(`/jobs/${jobId}`);
    state.selectedJobId = jobId;
    const text = renderLogs(job.logs);
    if (logEl) {
      logEl.textContent = text;
      logEl.scrollTop = logEl.scrollHeight;
    }
    document.getElementById("job-log").textContent = job.error ? `${text}\n\nERROR: ${job.error}` : text;
    if (job.status === "completed") {
      stopJobPolling();
      toast(`Job completed: ${job.label}`);
      await refresh();
      if (job.type === "deploy_vm" && job.result?.vmid) openVmDetail(job.result.vmid);
      return;
    }
    if (job.status === "failed") {
      stopJobPolling();
      toast(job.error || "Job failed", "err");
      await refresh();
    }
  };
  tick();
  state.pollTimer = setInterval(tick, 1500);
}

function stopJobPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.activeJobId = null;
}

async function refresh() {
  const [dashboard, vms, jobs, images, setup] = await Promise.all([
    api("/dashboard"),
    api("/vms"),
    api("/jobs"),
    api("/images"),
    api("/setup"),
  ]);
  state.dashboard = dashboard;
  state.vms = vms;
  state.jobs = jobs;
  state.images = images;
  state.tailnet = setup.tailscale_tailnet || dashboard.tailscale_tailnet || "";
  const tailnetEl = document.getElementById("tailnet-label");
  if (tailnetEl) tailnetEl.textContent = state.tailnet || "—";
  state.vmSshUser = setup.vm_ssh_user;

  document.getElementById("health-dot").className = "status-dot ok";
  document.getElementById("health-label").textContent = "Controller online";

  renderStats();
  renderOverviewActivity();
  renderSetupBanner();
  renderVmTable(document.getElementById("vm-search")?.value || "");
  renderImages();
  renderActivity();
  renderSettings();
  updateCreateSummary();

  const select = document.getElementById("image-select");
  select.innerHTML = images
    .filter((i) => i.built)
    .map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`)
    .join("");
  if (!select.innerHTML) select.innerHTML = '<option value="homecloud-base">homecloud-base (not built)</option>';
  document.getElementById("preview-ssh-user").textContent = state.vmSshUser;
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});
document.querySelectorAll("[data-view-link]").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.viewLink));
});
document.getElementById("create-shortcut").addEventListener("click", () => showView("create"));
document.getElementById("refresh-btn").addEventListener("click", refresh);
document.getElementById("vm-detail-back").addEventListener("click", () => showView("vms"));
document.getElementById("vm-search")?.addEventListener("input", (e) => renderVmTable(e.target.value));

document.getElementById("deploy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("deploy-submit");
  const logEl = document.getElementById("create-log");
  btn.disabled = true;
  logEl.textContent = "Submitting…";
  const fd = new FormData(e.target);
  try {
    const { job_id } = await api("/vms", {
      method: "POST",
      body: JSON.stringify({
        name: fd.get("name"),
        cores: Number(fd.get("cores")),
        memory_gb: Number(fd.get("memory_gb")),
        disk_gb: Number(fd.get("disk_gb")),
        image_id: fd.get("image_id"),
      }),
    });
    toast("Provisioning started");
    startJobPolling(job_id, logEl);
    await refresh();
  } catch (err) {
    logEl.textContent = err.message;
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("setup-btn").addEventListener("click", async () => {
  const msg = document.getElementById("setup-msg");
  try {
    await api("/setup", {
      method: "POST",
      body: JSON.stringify({ ssh_public_key: document.getElementById("ssh-key").value.trim() }),
    });
    msg.textContent = "SSH key saved.";
    msg.className = "msg ok";
    await refresh();
  } catch (e) {
    msg.textContent = e.message;
    msg.className = "msg err";
  }
});

async function copySshConfig() {
  const { config } = await api("/ssh-config");
  await navigator.clipboard.writeText(config);
  toast("SSH config copied");
}
document.getElementById("ssh-export-btn").addEventListener("click", copySshConfig);
document.getElementById("copy-ssh-quick").addEventListener("click", copySshConfig);

bindSliders();
showView("overview");
refresh().catch((e) => {
  document.getElementById("health-dot").className = "status-dot err";
  document.getElementById("health-label").textContent = "Controller offline";
  toast(e.message, "err");
});
