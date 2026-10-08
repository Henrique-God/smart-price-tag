(() => {
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
  let refreshing = false;

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
})();
