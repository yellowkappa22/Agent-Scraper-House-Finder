const status = document.querySelector("#status");

fetch("/api/health")
  .then((response) => {
    if (!response.ok) {
      throw new Error("Health check failed");
    }
    return response.json();
  })
  .then((health) => {
    status.textContent =
      health.status === "ok" ? "Application is running." : "Application is unavailable.";
  })
  .catch(() => {
    status.textContent = "Application is unavailable.";
  });
