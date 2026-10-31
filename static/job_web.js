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
