(() => {
  setUpCopyButtons();

  const panels = [...document.querySelectorAll("[data-live-tag]")];
  if (panels.length === 0) return;

  function openLinkedPanel() {
    if (!window.location.hash.startsWith("#tag-")) return;
    const selected = document.getElementById(window.location.hash.slice(1));
    if (selected instanceof HTMLDetailsElement) {
      selected.open = true;
      window.requestAnimationFrame(() => selected.scrollIntoView({ block: "start" }));
    }
  }
  openLinkedPanel();
  window.addEventListener("hashchange", openLinkedPanel);

  const states = ["pending", "waiting", "received", "applied"];
  const syncStates = ["synced", "changed", "unseen", "unconfirmed"];
  const historyColumns = [
    ["Seq", (item) => `#${item.seq}`],
    ["Versão", (item) => item.version, "code"],
    ["Motivo", (item) => item.reason],
    ["O que mudou", (item) => item.changes.join("; ")],
    ["Preparada", (item) => item.prepared],
    ["Publicada (ACK)", (item) => item.published],
  ];
  let refreshing = false;

  function updateFields(panel, tag) {
    for (const field of panel.querySelectorAll("[data-live-field]")) {
      const name = field.dataset.liveField;
      const value = name === "state" ? tag.label : tag[name];
      if (typeof value === "string" && field.textContent !== value) field.textContent = value;
      if (name === "state") {
        for (const state of states) field.classList.remove(`mqtt-badge-${state}`);
        field.classList.add(`mqtt-badge-${tag.state}`);
      }
      if (name === "sync_label" && syncStates.includes(tag.sync_state)) {
        for (const state of syncStates) field.classList.remove(`sync-badge-${state}`);
        field.classList.add(`sync-badge-${tag.sync_state}`);
      }
    }
    // Styling hooks such as data-state="late" or data-state="weak".
    for (const element of panel.querySelectorAll("[data-live-state]")) {
      const value = tag[element.dataset.liveState];
      if (typeof value === "string") element.dataset.state = value;
    }
    // data-live-show-when="field=value" shows the element only when it matches.
    for (const element of panel.querySelectorAll("[data-live-show-when]")) {
      const [name, expected] = element.dataset.liveShowWhen.split("=");
      if (name in tag) element.hidden = String(tag[name]) !== expected;
    }
  }

  function updateTimeline(panel, tag) {
    if (!Array.isArray(tag.timeline)) return;
    for (const step of tag.timeline) {
      const item = panel.querySelector(`[data-live-step="${step.key}"]`);
      if (!item) continue;
      item.dataset.done = step.done ? "true" : "false";
      const time = item.querySelector(".step-time");
      if (time && time.textContent !== step.time) time.textContent = step.time;
      const status = item.querySelector(".step-status");
      if (status) status.textContent = step.done ? "concluída:" : "pendente:";
    }
  }

  function historyRow(item) {
    const row = document.createElement("tr");
    for (const [label, value, wrapper] of historyColumns) {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      const content = wrapper ? document.createElement(wrapper) : cell;
      content.textContent = value(item);
      if (wrapper) cell.append(content);
      if (label === "Publicada (ACK)" && item.republished) {
        const detail = document.createElement("span");
        detail.className = "cell-detail";
        detail.textContent = `Reenviada: ${item.republished}`;
        cell.append(detail);
      }
      row.append(cell);
    }
    return row;
  }

  function updateHistory(panel, tag) {
    const body = panel.querySelector("[data-live-history]");
    if (!body || !Array.isArray(tag.history)) return;
    // Rebuild only when the content changed, so text selection is not lost every 5 s.
    const signature = JSON.stringify(tag.history);
    if (body.dataset.signature === signature) return;
    body.dataset.signature = signature;
    if (tag.history.length === 0) return;
    body.replaceChildren(...tag.history.map(historyRow));
  }

  async function refreshStatus() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    try {
      const response = await fetch("/mqtt/estado", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) return;
      const snapshot = await response.json();
      const byId = new Map(snapshot.tags.map((tag) => [tag.identifier, tag]));

      for (const panel of panels) {
        const tag = byId.get(panel.dataset.liveTag);
        if (!tag || !states.includes(tag.state)) continue;
        if (syncStates.includes(tag.sync_state)) panel.dataset.syncState = tag.sync_state;
        updateFields(panel, tag);
        updateTimeline(panel, tag);
        updateHistory(panel, tag);
      }

      for (const count of document.querySelectorAll("[data-live-count]")) {
        const value = snapshot.counts[count.dataset.liveCount];
        if (Number.isInteger(value)) count.textContent = String(value);
      }
    } catch (_) {
      // The rendered page remains usable while the server or network is unavailable.
    } finally {
      refreshing = false;
    }
  }

  refreshStatus();
  window.setInterval(refreshStatus, 5000);
  document.addEventListener("visibilitychange", refreshStatus);

  function setUpCopyButtons() {
    document.addEventListener("click", async (event) => {
      const button = event.target instanceof Element ? event.target.closest("[data-copy-target]") : null;
      if (!button) return;
      const source = document.getElementById(button.dataset.copyTarget);
      const feedback = document.querySelector(`[data-copy-feedback="${button.dataset.copyTarget}"]`);
      if (!source) return;
      let copied = false;
      try {
        await navigator.clipboard.writeText(source.textContent);
        copied = true;
      } catch (_) {
        // Clipboard API needs a secure context (localhost or HTTPS); fall back to a selection.
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(source);
        selection.removeAllRanges();
        selection.addRange(range);
        copied = document.execCommand("copy");
      }
      if (feedback) feedback.textContent = copied ? "Copiado." : "Selecione o texto e copie com Ctrl+C / ⌘C.";
    });
  }
})();
