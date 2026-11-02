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
