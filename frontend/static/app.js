// The VMs page: a list that refreshes itself, and the form to make a new one.
// Everything here is built with textContent, never innerHTML, so nothing from the API is
// ever treated as markup.

let cfg = null;
let os = 'ubuntu';
const $ = id => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c);
  return node;
}

// ---------- status ----------

const STEP_TEXT = {
  ubuntu: { create: 'Creating', start: 'Starting', wait: 'Booting, running cloud-init', cleanup: 'Finishing up' },
  windows: { create: 'Creating', start: 'Starting', wait: 'Installing Windows (20–40 min)', cleanup: 'Finishing up' },
};

function status(vm) {
  if (vm.state === 'creating') return ['busy', STEP_TEXT[vm.os][vm.step] || 'Creating'];
  if (vm.state === 'deleting') return ['busy', vm.error ? 'Deleting (retrying)' : 'Deleting'];
  if (vm.state === 'failed') return ['bad', 'Failed'];
  if (vm.power === 'running') return ['ok', 'Running · ', uptimeClock(vm.uptime)];
  if (vm.power === 'stopped') return ['', 'Stopped'];
  return ['', vm.power || 'Unknown'];
}

// Uptime to the second, any length: "42s", "5m 03s", "2h 05m 03s", "100d 02h 05m 03s".
function uptime(s) {
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
  const p = n => String(n).padStart(2, '0');
  if (d) return `${d}d ${p(h)}h ${p(m)}m ${p(sec)}s`;
  if (h) return `${h}h ${p(m)}m ${p(sec)}s`;
  if (m) return `${m}m ${p(sec)}s`;
  return `${sec}s`;
}

// Proxmox reports uptime when the list loads; between loads, count up here every second.
function uptimeClock(seconds) {
  return el('span', { class: 'uptime', 'data-base': seconds, 'data-at': Date.now() }, uptime(seconds));
}
setInterval(() => {
  for (const node of document.querySelectorAll('.uptime')) {
    node.textContent = uptime(+node.dataset.base + (Date.now() - +node.dataset.at) / 1000);
  }
}, 1000);

function svgIcon(paths) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of Object.entries({ width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(k, v);
  for (const d of paths) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}
const COPY_ICON = ['M8 8h11a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z', 'M4 16V5a1 1 0 0 1 1-1h11'];
const CHECK_ICON = ['M20 6 9 17l-5-5'];

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch { }
  // No clipboard API (a plain-http page): the old way.
  const t = el('textarea', { style: 'position:fixed;opacity:0' });
  t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
}

function copyButton(text, label) {
  const btn = el('button', { class: 'copy', type: 'button', title: label, 'aria-label': label }, svgIcon(COPY_ICON));
  btn.addEventListener('click', async () => {
    await copyText(text);
    btn.replaceChildren(svgIcon(CHECK_ICON)); btn.classList.add('done');
    setTimeout(() => { btn.replaceChildren(svgIcon(COPY_ICON)); btn.classList.remove('done'); }, 1500);
  });
  return btn;
}

function ipLine(vm) {
  if (!vm.ip) return null;
  const how = vm.os === 'ubuntu' ? `ssh ubuntu@${vm.ip}` : `RDP · Administrator`;
  return el('div', { class: 'vm-ip' },
    el('span', { class: 'mono' }, vm.ip), copyButton(vm.ip, 'Copy IP'),
    el('span', { class: 'vm-connect' }, how));
}

// The VM's page in the Proxmox UI (Summary, with Console, Hardware and the rest one click away).
// The hash is Proxmox's own "which resource is selected" state. Proxmox asks you to sign in first.
function proxmoxUrl(vm) {
  return `${cfg.proxmox_ui}/#v1:0:=qemu%2F${vm.vmid}:4:::::::`;
}

// ---------- each VM's log ----------

// Open log panels, by VM name. A panel stays open across refreshes and only fetches what's new.
const logs = new Map();

function logLine(e) {
  const t = new Date(e.at);
  return el('div', { class: 'log-line ' + e.level },
    el('time', { datetime: e.at, title: t.toLocaleString() }, t.toLocaleTimeString([], { hour12: false })),
    el('span', { class: 'log-msg' }, e.message));
}

function logText(l) {
  return l.lines.map(e => `${e.at}  ${e.level.toUpperCase().padEnd(5)}  ${e.message}`).join('\n');
}

function openLog(name) {
  const body = el('div', { class: 'log-body', role: 'log' }, el('div', { class: 'log-empty' }, 'Loading…'));
  const l = { after: 0, lines: [], body, scroll: null };
  const copy = el('button', { class: 'btn small', type: 'button', onclick: async e => {
    await copyText(`homecloud log for ${name}\n` + logText(l));
    e.target.textContent = 'Copied'; setTimeout(() => { e.target.textContent = 'Copy log'; }, 1500);
  } }, 'Copy log');
  l.panel = el('div', { class: 'vm-log' },
    el('div', { class: 'log-head' }, el('span', { class: 'label' }, 'Log'), copy), body);
  logs.set(name, l);
}

async function loadLog(name) {
  const l = logs.get(name);
  const { events } = await auth.api(`/api/vms/${encodeURIComponent(name)}/events?after=${l.after}`);
  if (!events.length) {
    if (!l.lines.length) l.body.replaceChildren(el('div', { class: 'log-empty' }, 'Nothing logged yet.'));
    return;
  }
  const b = l.body, atBottom = !l.lines.length || b.scrollHeight - b.scrollTop - b.clientHeight < 24;
  if (!l.lines.length) b.replaceChildren();
  for (const e of events) { l.lines.push(e); b.append(logLine(e)); }
  l.after = events[events.length - 1].id;
  if (atBottom) b.scrollTop = b.scrollHeight;  // follow along, unless you've scrolled up to read
}

// ---------- the list ----------

async function act(button, fn) {
  button.disabled = true;
  try { await fn(); await refresh(); }
  catch (e) { alert(e.message); }
  finally { button.disabled = false; }
}

function vmRow(vm) {
  const [dot, ...text] = status(vm);
  const actions = [];
  if (vm.state === 'ready') {
    if (vm.power === 'running') {
      actions.push(el('button', { class: 'btn small', type: 'button', onclick: e =>
        act(e.target, () => auth.api(`/api/vms/${vm.name}/shutdown`, { method: 'POST' })) }, 'Shut down'));
    } else {
      actions.push(el('button', { class: 'btn small', type: 'button', onclick: e =>
        act(e.target, () => auth.api(`/api/vms/${vm.name}/start`, { method: 'POST' })) }, 'Start'));
    }
  }
  if (vm.vmid && cfg) {
    // Only opens from the LAN or tailnet, where the Proxmox UI is.
    actions.push(el('a', { class: 'btn small', target: '_blank', rel: 'noopener', href: proxmoxUrl(vm),
      title: `VM ${vm.vmid} in the Proxmox UI` }, 'Proxmox ↗'));
  }
  const open = logs.has(vm.name);
  actions.push(el('button', { class: 'btn small', type: 'button', 'aria-expanded': String(open), onclick: () => {
    if (open) logs.delete(vm.name); else openLog(vm.name);
    refresh();
  } }, open ? 'Hide log' : 'Log'));
  if (vm.state !== 'deleting') {
    actions.push(el('button', { class: 'btn small danger', type: 'button', onclick: e => {
      if (confirm(`Delete ${vm.name}? Its disk is deleted too. This can't be undone.`)) {
        act(e.target, () => auth.api(`/api/vms/${vm.name}`, { method: 'DELETE' }));
      }
    } }, 'Delete'));
  }

  return el('div', { class: 'vm' },
    el('div', {},
      el('div', { class: 'vm-name' }, vm.name),
      el('div', { class: 'vm-sub' }, vm.os_label + (vm.vmid ? ` · VM ${vm.vmid}` : '')),
      ipLine(vm),
    ),
    el('div', { class: 'vm-sub' }, `${vm.cores} vCPU · ${vm.memory_gb} GB · ${vm.disk_gb} GB disk`),
    el('div', {},
      el('div', { class: 'vm-status' }, el('span', { class: 'dot ' + dot }), el('span', {}, text)),
      vm.error && el('div', { class: 'vm-error' }, vm.error),
      // While it's working, the latest thing the worker did.
      !vm.error && vm.last_event && (vm.state === 'creating' || vm.state === 'deleting') &&
        el('div', { class: 'vm-last', title: vm.last_event }, vm.last_event),
    ),
    el('div', { class: 'vm-actions' }, actions),
  );
}

let timer = null;
async function refresh() {
  clearTimeout(timer);
  let busy = false;
  try {
    const data = await auth.api('/api/vms');
    $('pve-down').hidden = data.proxmox;
    const list = $('vms');
    const names = new Set(data.vms.map(v => v.name));
    for (const name of logs.keys()) if (!names.has(name)) logs.delete(name);  // VM's gone
    for (const l of logs.values()) l.scroll = l.body.scrollTop;  // re-adding a node resets it
    list.replaceChildren(...(data.vms.length
      ? data.vms.flatMap(vm => logs.has(vm.name) ? [vmRow(vm), logs.get(vm.name).panel] : [vmRow(vm)])
      : [el('div', { class: 'empty' }, 'No VMs yet. Make one with New VM.')]));
    for (const l of logs.values()) if (l.scroll != null) l.body.scrollTop = l.scroll;
    busy = data.vms.some(v => v.state === 'creating' || v.state === 'deleting');
    await Promise.all([...logs.keys()].map(name => loadLog(name).catch(() => {})));
  } catch (e) {
    $('vms').replaceChildren(el('div', { class: 'empty' }, 'Couldn’t load VMs: ' + e.message));
  }
  // Quick while something's happening, slow otherwise; not at all in a hidden tab.
  timer = setTimeout(() => document.hidden ? null : refresh(), busy ? 4000 : 15000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

// ---------- the form ----------

function pressed(container, value) {
  for (const b of container.children) b.setAttribute('aria-pressed', String(b.dataset.value === value));
}

function setSize(p) {
  const min = cfg.oses[os];
  $('cores').value = p.cores;
  $('memory_gb').value = Math.max(p.memory_gb, min.min_memory_gb);
  $('disk_gb').value = Math.max(p.disk_gb, min.min_disk_gb);
  pressed($('presets'), p.label);
}

function chooseOs(value) {
  os = value;
  pressed($('os-choices'), value);
  const min = cfg.oses[os];
  $('memory_gb').min = min.min_memory_gb; $('memory_gb').max = cfg.limits.memory_gb;
  $('disk_gb').min = min.min_disk_gb; $('disk_gb').max = cfg.limits.disk_gb;
  $('cores').max = cfg.limits.cores;
  setSize({
    label: '', cores: +$('cores').value || 2,
    memory_gb: +$('memory_gb').value || 4, disk_gb: +$('disk_gb').value || 40,
  });
  const notReady = os === 'windows' ? !cfg.windows_ready : !cfg.ubuntu_ready;
  $('os-note').textContent = os === 'windows'
    ? (notReady ? 'HOMECLOUD_WINDOWS_ADMIN_PASSWORD isn’t set, so Windows VMs can’t be made yet.'
      : 'Unattended install from the Windows 11 ISO. Sign in as Administrator with the password from Infisical. Needs 64 GB of disk and 4 GB of memory.')
    : (notReady ? 'HOMECLOUD_SSH_KEYS isn’t set, so Ubuntu VMs can’t be made yet.'
      : 'Ubuntu 26.04 cloud image. Sign in as ubuntu with your SSH key; there’s no password.');
  $('create-submit').disabled = notReady;
}

function buildForm() {
  $('os-choices').replaceChildren(...Object.entries(cfg.oses).map(([value, o]) =>
    el('button', { class: 'choice', type: 'button', 'data-value': value, onclick: () => chooseOs(value) }, o.label)));
  $('presets').replaceChildren(...cfg.presets.map(p =>
    el('button', { class: 'choice', type: 'button', 'data-value': p.label, onclick: () => setSize(p) },
      p.label, el('small', {}, `${p.cores} vCPU · ${p.memory_gb} GB · ${p.disk_gb} GB`))));
  for (const id of ['cores', 'memory_gb', 'disk_gb']) $(id).addEventListener('input', () => pressed($('presets'), ''));
  setSize(cfg.presets[1]);
  chooseOs('ubuntu');
}

$('new-vm').onclick = () => { $('create').hidden = false; $('new-vm').hidden = true; $('name').focus(); };
$('create-cancel').onclick = () => { $('create').hidden = true; $('new-vm').hidden = false; $('create-error').hidden = true; };
$('name').addEventListener('input', e => { e.target.value = e.target.value.toLowerCase(); });

$('create').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target, err = $('create-error');
  err.hidden = true;
  $('create-submit').disabled = true;
  try {
    await auth.api('/api/vms', { method: 'POST', body: JSON.stringify({
      name: $('name').value.trim(), os,
      cores: +f.cores.value, memory_gb: +f.memory_gb.value, disk_gb: +f.disk_gb.value,
    }) });
    $('name').value = '';
    $('create-cancel').click();
    refresh();
  } catch (ex) {
    err.textContent = ex.message; err.hidden = false;
  } finally {
    $('create-submit').disabled = false;
  }
});

$('sign-out').onclick = () => auth.signOut();

(async () => {
  try {
    cfg = await auth.api('/api/config');
    buildForm();
  } catch (e) {
    $('new-vm').disabled = true;
  }
  refresh();
})();
