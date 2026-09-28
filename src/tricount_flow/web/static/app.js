"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const picker = $("#tricount");

const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
};

const currentName = () => (picker ? picker.value : null);
let currency = "";

// Member names / descriptions come from shared Tricount data — escape before
// interpolating into HTML.
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function setMsg(el, text, kind) {
  el.textContent = text;
  el.className = "msg" + (kind ? " " + kind : "");
}

function fmt(n) {
  return `${Number(n).toFixed(2)} ${currency}`;
}

async function loadMembers() {
  const info = await api(`/api/tricount/${encodeURIComponent(currentName())}`);
  currency = info.currency;

  const payer = $("#payer");
  const from = $("#reimburse-from");
  const to = $("#reimburse-to");
  [payer, from, to].forEach((s) => (s.innerHTML = ""));

  info.members.forEach((m) => {
    for (const sel of [payer, from, to]) {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    }
  });
  if (info.me) {
    payer.value = info.me;
    from.value = info.me;
  }
  // "to" defaults to someone other than "me"
  if (info.me && to.options.length > 1) {
    const other = info.members.find((m) => m !== info.me);
    if (other) to.value = other;
  }

  const split = $("#split");
  split.innerHTML = "";
  info.members.forEach((m) => {
    const label = document.createElement("label");
    label.className = "chip on";
    label.innerHTML = `<input type="checkbox" value="${esc(m)}" checked /> ${esc(m)}`;
    const cb = label.querySelector("input");
    cb.addEventListener("change", () => label.classList.toggle("on", cb.checked));
    split.appendChild(label);
  });
}

async function loadBalances() {
  const data = await api(`/api/tricount/${encodeURIComponent(currentName())}/balances`);
  currency = data.currency;
  const tbody = $("#balances tbody");
  tbody.innerHTML = "";
  Object.entries(data.balances)
    .sort((a, b) => b[1] - a[1])
    .forEach(([name, val]) => {
      const tr = document.createElement("tr");
      const cls = val > 0 ? "pos" : val < 0 ? "neg" : "muted";
      tr.innerHTML = `<td>${esc(name)}</td><td class="num ${cls}">${val >= 0 ? "+" : ""}${val.toFixed(2)}</td>`;
      tbody.appendChild(tr);
    });

  const box = $("#settlements");
  box.innerHTML = "";
  if (!data.settlements.length) {
    box.innerHTML = `<div class="pos">All settled up! 🎉</div>`;
  } else {
    data.settlements.forEach((p) => {
      const d = document.createElement("div");
      d.innerHTML = `<span class="neg">${esc(p.frm)}</span> pays <span class="pos">${esc(p.to)}</span> <strong>${fmt(p.amount)}</strong>`;
      box.appendChild(d);
    });
  }
}

async function loadExpenses() {
  const rows = await api(`/api/tricount/${encodeURIComponent(currentName())}/expenses?n=10`);
  const tbody = $("#expenses tbody");
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="muted">No expenses yet.</td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    const tag = r.kind === "NORMAL" ? "" : ` <span class="muted">[${esc(r.kind.toLowerCase())}]</span>`;
    tr.innerHTML =
      `<td><strong>${esc(r.description)}</strong>${tag}<br><span class="muted">${esc(r.date)} · ${esc(r.payer)}</span></td>` +
      `<td class="num">${Number(r.amount).toFixed(2)} ${esc(r.currency)}</td>`;
    tbody.appendChild(tr);
  });
}

async function refreshAll() {
  try {
    await loadMembers();
    await Promise.all([loadBalances(), loadExpenses()]);
  } catch (e) {
    setMsg($("#expense-msg"), e.message, "err");
  }
}

function wire() {
  if (!picker) return; // no config

  // Default both date pickers to today (editable, to backdate past expenses).
  const today = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local
  document.querySelectorAll('input[type="date"]').forEach((el) => (el.value = today));

  picker.addEventListener("change", refreshAll);
  $("#refresh").addEventListener("click", () =>
    Promise.all([loadBalances(), loadExpenses()]).catch((e) =>
      setMsg($("#expense-msg"), e.message, "err")
    )
  );

  $("#expense-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const msg = $("#expense-msg");
    const split = [...form.querySelectorAll("#split input:checked")].map((c) => c.value);
    if (!split.length) return setMsg(msg, "Pick at least one person to split among.", "err");
    const body = {
      description: form.description.value.trim(),
      amount: parseFloat(form.amount.value),
      payer: form.payer.value,
      split,
      category: form.category.value || null,
      date: form.date.value || null,
    };
    const btn = form.querySelector("button");
    btn.disabled = true;
    setMsg(msg, "Adding…");
    try {
      const res = await api(`/api/tricount/${encodeURIComponent(currentName())}/expense`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setMsg(msg, `Added — each owes ${fmt(res.per_person)}.`, "ok");
      form.description.value = "";
      form.amount.value = "";
      await Promise.all([loadBalances(), loadExpenses()]);
    } catch (e) {
      setMsg(msg, e.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  $("#reimburse-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const msg = $("#reimburse-msg");
    const body = {
      amount: parseFloat(form.amount.value),
      frm: form.frm.value,
      to: form.to.value,
      date: form.date.value || null,
    };
    if (body.frm === body.to) return setMsg(msg, "From and To must differ.", "err");
    const btn = form.querySelector("button");
    btn.disabled = true;
    setMsg(msg, "Saving…");
    try {
      await api(`/api/tricount/${encodeURIComponent(currentName())}/reimburse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setMsg(msg, "Recorded.", "ok");
      form.amount.value = "";
      await Promise.all([loadBalances(), loadExpenses()]);
    } catch (e) {
      setMsg(msg, e.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  wireImport();
  refreshAll();
}

function renderImportResults(data) {
  const box = $("#csv-results");
  const rows = data.results
    .map((r) => {
      const mark = r.ok ? '<span class="pos">✓</span>' : '<span class="neg">✗</span>';
      const amt = r.amount == null ? "-" : Number(r.amount).toFixed(2);
      return `<tr><td>${r.line}</td><td>${esc(r.description) || "-"}</td><td class="num">${amt}</td><td>${esc(r.action)}</td><td>${mark} ${esc(r.detail)}</td></tr>`;
    })
    .join("");
  box.innerHTML = `<table><tbody>${rows}</tbody></table>`;
}

function wireImport() {
  const fileEl = $("#csv-file");
  const previewBtn = $("#csv-preview");
  const importBtn = $("#csv-import");
  const msg = $("#csv-msg");
  if (!fileEl) return;
  let csvText = null;

  const readFile = () =>
    new Promise((resolve, reject) => {
      const f = fileEl.files && fileEl.files[0];
      if (!f) return reject(new Error("Choose a CSV file first."));
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("Could not read the file."));
      reader.readAsText(f);
    });

  const post = (dry) =>
    api(`/api/tricount/${encodeURIComponent(currentName())}/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv: csvText, dry_run: dry }),
    });

  fileEl.addEventListener("change", () => {
    importBtn.disabled = true;
    $("#csv-results").innerHTML = "";
    setMsg(msg, "");
  });

  previewBtn.addEventListener("click", async () => {
    setMsg(msg, "Reading…");
    try {
      csvText = await readFile();
      const data = await post(true);
      renderImportResults(data);
      const { ok, failed } = data.summary;
      setMsg(msg, `${ok} to import, ${failed} invalid. Review, then Confirm.`, ok ? "ok" : "err");
      importBtn.disabled = ok === 0;
    } catch (e) {
      setMsg(msg, e.message, "err");
    }
  });

  importBtn.addEventListener("click", async () => {
    importBtn.disabled = true;
    setMsg(msg, "Importing…");
    try {
      const data = await post(false);
      renderImportResults(data);
      setMsg(msg, `Imported ${data.summary.ok}, ${data.summary.failed} skipped.`, "ok");
      await Promise.all([loadBalances(), loadExpenses()]);
    } catch (e) {
      setMsg(msg, e.message, "err");
      importBtn.disabled = false;
    }
  });
}

wire();
