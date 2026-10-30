document.querySelectorAll("tr[data-href]").forEach((row) => {
  row.addEventListener("click", (event) => {
    if (event.target.closest("a, button, input, select")) return;
    window.location.href = row.dataset.href;
  });
});
