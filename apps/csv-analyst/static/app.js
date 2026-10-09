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

let selectedFile = null;
let reportUrl = null;
function selectFile(file) {
  selectedFile = file;
  $("file-meta").textContent = file
    ? file.name + " · " + Math.ceil(file.size / 1024) + " KB"
    : "Select a CSV before running analysis.";
}
$("file").addEventListener("change", () => selectFile($("file").files[0]));
$("sample").addEventListener("click", async () => {
  try {
    const r = await fetch("/api/sample");
    if (!r.ok) throw new Error("Could not load the example data.");
    selectFile(
      new File([await r.blob()], "telecom-data.csv", { type: "text/csv" }),
    );
    $("file").value = "";
  } catch (error) {
    showError(error.message);
  }
});
$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("error").hidden = true;
  if (!selectedFile)
    return showError("Choose a CSV file or select Use example data.");
  if (selectedFile.size > 1000000)
    return showError("Use a CSV smaller than 1 MB.");
  const payload = new FormData();
  payload.append("file", selectedFile);
  payload.append("question", $("question").value);
  $("result").hidden = true;
  $("empty").hidden = false;
  $("warning").hidden = true;
  busy(true, "Generating your report. This may take a few minutes…");
  try {
    const data = await responseData(
      await fetch("/api/analyze", { method: "POST", body: payload }),
    );
    if (reportUrl) URL.revokeObjectURL(reportUrl);
    const bytes = Uint8Array.from(atob(data.report_base64), (ch) =>
      ch.charCodeAt(0),
    );
    reportUrl = URL.createObjectURL(new Blob([bytes], { type: "text/html" }));
    $("download").href = reportUrl;
    $("rows").textContent = data.profile.rows.toLocaleString();
    $("columns").textContent = data.profile.columns.length;
    $("summary").textContent = data.summary;
    if (data.cleanup_warning) {
      $("warning").textContent = data.cleanup_warning;
      $("warning").hidden = false;
    }
    $("empty").hidden = true;
    $("result").hidden = false;
  } catch (error) {
    showError(error.message || "The analysis could not complete.");
  } finally {
    busy(false);
  }
});
window.addEventListener("beforeunload", () => {
  if (reportUrl) URL.revokeObjectURL(reportUrl);
});
