(function () {
  "use strict";

  const form = document.getElementById("convert-form");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const fileName = document.getElementById("file-name");
  const submitBtn = document.getElementById("submit-btn");
  const statusBox = document.getElementById("status");
  const resultBox = document.getElementById("result");
  const resultInfo = document.getElementById("result-info");
  const preview = document.getElementById("preview");
  const downloadLink = document.getElementById("download-link");

  let objectUrl = null;

  function setStatus(message, isError) {
    if (!message) {
      statusBox.hidden = true;
      statusBox.textContent = "";
      return;
    }
    statusBox.hidden = false;
    statusBox.classList.toggle("error", Boolean(isError));
    statusBox.innerHTML = "";
    if (!isError && message.busy) {
      const spinner = document.createElement("span");
      spinner.className = "spinner";
      statusBox.appendChild(spinner);
    }
    statusBox.appendChild(
      document.createTextNode(message.text !== undefined ? message.text : message)
    );
  }

  function showFile(file) {
    if (!file) return;
    if (!/\.(dxf|dwg)$/i.test(file.name)) {
      setStatus("Please choose a .dxf or .dwg file.", true);
      submitBtn.disabled = true;
      fileName.hidden = true;
      return;
    }
    setStatus(null);
    fileName.textContent = file.name;
    fileName.hidden = false;
    submitBtn.disabled = false;
  }

  // --- file picking -------------------------------------------------
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => showFile(fileInput.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    })
  );
  dropZone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) {
      fileInput.files = e.dataTransfer.files;
      showFile(file);
    }
  });

  // --- helpers ------------------------------------------------------
  function b64ToBlob(b64, type) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: type });
  }

  function addInfo(label, value) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    wrap.append(dt, dd);
    resultInfo.appendChild(wrap);
  }

  function renderResult(data) {
    const info = data.info;
    resultInfo.innerHTML = "";
    addInfo("Scale", info.scale + (info.auto_scale ? " (auto-fit)" : ""));
    addInfo("Paper", info.paper + " " + info.orientation);
    addInfo(
      "Units",
      info.units + (info.units_autodetected ? " (detected)" : " (set manually)")
    );
    addInfo(
      "Drawing size",
      info.drawing_display ||
        info.drawing_mm[0] + " × " + info.drawing_mm[1] + " mm"
    );
    addInfo("Printed size", info.plotted_mm[0] + " × " + info.plotted_mm[1] + " mm");

    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(b64ToBlob(data.pdf_b64, "application/pdf"));
    downloadLink.href = objectUrl;
    downloadLink.download = data.filename;

    if (data.preview_b64) {
      preview.src = "data:image/png;base64," + data.preview_b64;
      preview.hidden = false;
    } else {
      preview.hidden = true;
    }
    resultBox.hidden = false;
  }

  // --- submit -------------------------------------------------------
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    if (!file) {
      setStatus("Please choose a .dxf file first.", true);
      return;
    }

    const body = new FormData();
    body.append("file", file);
    body.append("scale", document.getElementById("scale").value);
    body.append("paper", document.getElementById("paper").value);
    body.append("orientation", document.getElementById("orientation").value);
    body.append("units", document.getElementById("units").value);
    body.append("margin", document.getElementById("margin").value);
    body.append(
      "line_width_scale",
      document.getElementById("line_width_scale").value
    );
    body.append(
      "show_label",
      document.getElementById("show_label").checked ? "true" : "false"
    );

    submitBtn.disabled = true;
    resultBox.hidden = true;
    setStatus({ text: "Converting…", busy: true }, false);

    try {
      const res = await fetch("/api/convert", { method: "POST", body: body });
      let data;
      try {
        data = await res.json();
      } catch (err) {
        throw new Error(
          res.status === 413
            ? "That file is too large to upload."
            : "Server error (" + res.status + ")."
        );
      }
      if (!res.ok || !data.ok) {
        throw new Error(data.error || "Conversion failed.");
      }
      setStatus(null);
      renderResult(data);
      resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
