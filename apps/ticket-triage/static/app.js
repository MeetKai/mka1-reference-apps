const $ = (id) => document.getElementById(id);
function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}
function busy(value, label) {
  $("submit").disabled = value;
  $("status").textContent = value ? label : "";
  $("empty").classList.toggle("busy-symbol", value);
}
async function responseData(response) {
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the input and try again.",
    );
  return data;
}

const teams = {
  billing: "Billing",
  technical_support: "Technical support",
  account_services: "Account services",
};
fetch("/api/samples")
  .then(responseData)
  .then((samples) => {
    for (const sample of samples) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sample";
      button.textContent = sample.label;
      button.addEventListener("click", () => {
        $("ticket").value = sample.ticket;
        document
          .querySelectorAll(".sample")
          .forEach((b) => b.classList.remove("selected"));
        button.classList.add("selected");
        $("ticket").focus();
      });
      $("samples").append(button);
    }
  })
  .catch(() =>
    showError(
      "Sample tickets could not load. You can still enter your own ticket.",
    ),
  );
$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("error").hidden = true;
  $("result").hidden = true;
  $("empty").hidden = false;
  busy(true, "Analyzing the ticket. This may take up to 90 seconds…");
  try {
    const data = await responseData(
      await fetch("/api/triage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket: $("ticket").value }),
      }),
    );
    const d = data.decision;
    $("team").textContent = teams[d.team];
    $("priority").textContent = d.priority;
    $("summary").textContent = d.summary;
    $("rationale").textContent = d.rationale;
    $("next-action").textContent = d.next_action;
    $("empty").hidden = true;
    $("result").hidden = false;
  } catch (error) {
    showError(error.message || "The request could not complete.");
  } finally {
    busy(false);
  }
});
