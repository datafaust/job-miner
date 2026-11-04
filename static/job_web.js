// Keep the applied list view in this tab, including after intermediate pages.
// Explicit context in a detail link always takes precedence over this fallback.
function restoreJobListNavigation() {
  try {
    const storageKey = "job-miner:list-url";
    const list = document.querySelector("[data-job-list-url]");
    if (list) {
      sessionStorage.setItem(storageKey, list.dataset.jobListUrl);
      return;
    }
    const back = document.querySelector("[data-back-to-jobs]");
    const params = new URLSearchParams(window.location.search);
    if (!back || ["q", "source", "remote", "page", "sort", "order", "availability", "application"].some((key) => params.has(key))) return;
    const saved = sessionStorage.getItem(storageKey);
    if (!saved) return;
    const target = new URL(saved, window.location.origin);
    const fallback = new URL(back.href);
    if (target.origin === fallback.origin && target.pathname === fallback.pathname) {
      back.href = target.href;
    }
  } catch {
    // Navigation still works when browser storage is unavailable.
  }
}
restoreJobListNavigation();
window.addEventListener("pageshow", restoreJobListNavigation);

document.querySelectorAll("form[data-hide-job]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm("Remove this job from the list? It will remain saved and won’t be collected again.")) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll("tr[data-href]").forEach((row) => {
  row.addEventListener("click", (event) => {
    if (event.target.closest("a, button, input, select")) return;
    window.location.href = row.dataset.href;
  });
});

document.querySelectorAll("form[data-start-search]").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Starting search…";
  });
});
const addJobDialog = document.querySelector("#add-job-dialog");
if (addJobDialog) {
  document.querySelector("[data-open-add-job]").addEventListener("click", () => addJobDialog.showModal());
  addJobDialog.querySelectorAll("[data-close-add-job]").forEach((button) => {
    button.addEventListener("click", () => addJobDialog.close());
  });
  if (addJobDialog.hasAttribute("data-open-on-load")) addJobDialog.showModal();
}

// Confirm before queuing GPU work; cancellation never submits the form.
document.querySelectorAll("form[data-run-fit-grade]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirmMessage)) {
      event.preventDefault();
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Queuing fit grade…";
  });
});
