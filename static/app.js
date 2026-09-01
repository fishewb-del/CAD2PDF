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

  const viewerPanel = document.getElementById("viewer-panel");
  const viewer = document.getElementById("viewer");
  const stage = document.getElementById("viewer-stage");
  const viewerNote = document.getElementById("viewer-note");
  const zoomLabel = document.getElementById("zoom-level");

  let objectUrl = null;
  let previewToken = 0;

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
      viewerPanel.hidden = true;
      return;
    }
    setStatus(null);
    fileName.textContent = file.name;
    fileName.hidden = false;
    submitBtn.disabled = false;
    resultBox.hidden = true;
    loadPreview(file);
  }

  // ================= drawing viewer =================================
  // Pan/zoom over whatever the server rendered (inline SVG, or an <img>
  // for drawings too dense to send as vectors). Both are just an element
  // inside #viewer-stage, so one set of gestures drives either.

  const view = { scale: 1, x: 0, y: 0, fitScale: 1 };
  const MIN_SCALE = 0.05;
  const MAX_SCALE = 200;

  function applyView() {
    stage.style.transform =
      "translate(" + view.x + "px," + view.y + "px) scale(" + view.scale + ")";
    // Percentages are relative to the fitted view, which is what "100%"
    // means to someone looking at the drawing, not the SVG's own units.
    const pct = (view.scale / view.fitScale) * 100;
    zoomLabel.textContent = (pct < 10 ? pct.toFixed(1) : Math.round(pct)) + "%";
  }

  function fitToViewer() {
    const content = stage.firstElementChild;
    if (!content) return;
    // Reset first so we measure the untransformed size.
    stage.style.transform = "none";
    const box = viewer.getBoundingClientRect();
    const inner = content.getBoundingClientRect();
    if (!inner.width || !inner.height) return;
    const scale = Math.min(box.width / inner.width, box.height / inner.height) * 0.96;
    view.fitScale = scale;
    view.scale = scale;
    view.x = (box.width - inner.width * scale) / 2;
    view.y = (box.height - inner.height * scale) / 2;
    applyView();
  }

  function zoomAt(clientX, clientY, factor) {
    const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
    if (next === view.scale) return;
    const box = viewer.getBoundingClientRect();
    // Keep the point under the cursor fixed while the scale changes.
    const px = clientX - box.left;
    const py = clientY - box.top;
    const ratio = next / view.scale;
    view.x = px - (px - view.x) * ratio;
    view.y = py - (py - view.y) * ratio;
    view.scale = next;
    applyView();
  }

  function zoomCentre(factor) {
    const box = viewer.getBoundingClientRect();
    zoomAt(box.left + box.width / 2, box.top + box.height / 2, factor);
  }

  viewer.addEventListener("wheel", (e) => {
    e.preventDefault();
    // Trackpads report small deltas and mice report large ones; damping
    // the exponent keeps both feeling the same.
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.002));
  }, { passive: false });

  viewer.addEventListener("dblclick", (e) => zoomAt(e.clientX, e.clientY, 1.6));

  document.getElementById("zoom-in").addEventListener("click", () => zoomCentre(1.3));
  document.getElementById("zoom-out").addEventListener("click", () => zoomCentre(1 / 1.3));
  document.getElementById("zoom-fit").addEventListener("click", fitToViewer);

  viewer.addEventListener("keydown", (e) => {
    if (e.key === "+" || e.key === "=") { zoomCentre(1.3); e.preventDefault(); }
    else if (e.key === "-") { zoomCentre(1 / 1.3); e.preventDefault(); }
    else if (e.key === "0") { fitToViewer(); e.preventDefault(); }
  });

  // Pointer events cover mouse, trackpad, pen and touch with one path.
  // Two active pointers means a pinch.
  const pointers = new Map();
  let pinchStart = null;

  function pointerMid() {
    const pts = [...pointers.values()];
    return {
      x: (pts[0].x + pts[1].x) / 2,
      y: (pts[0].y + pts[1].y) / 2,
      dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y),
    };
  }

  viewer.addEventListener("pointerdown", (e) => {
    viewer.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      pinchStart = { mid: pointerMid(), scale: view.scale };
    }
    viewer.classList.add("grabbing");
  });

  viewer.addEventListener("pointermove", (e) => {
    const prev = pointers.get(e.pointerId);
    if (!prev) return;
    const next = { x: e.clientX, y: e.clientY };
    pointers.set(e.pointerId, next);

    if (pointers.size === 2 && pinchStart) {
      const mid = pointerMid();
      if (pinchStart.mid.dist > 0) {
        const target = pinchStart.scale * (mid.dist / pinchStart.mid.dist);
        zoomAt(mid.x, mid.y, target / view.scale);
      }
      return;
    }
    view.x += next.x - prev.x;
    view.y += next.y - prev.y;
    applyView();
  });

  function endPointer(e) {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinchStart = null;
    if (pointers.size === 0) viewer.classList.remove("grabbing");
  }
  viewer.addEventListener("pointerup", endPointer);
  viewer.addEventListener("pointercancel", endPointer);

  window.addEventListener("resize", () => {
    if (!viewerPanel.hidden) fitToViewer();
  });

  async function loadPreview(file) {
    const token = ++previewToken;
    viewerPanel.hidden = false;
    viewerNote.hidden = true;
    stage.innerHTML = "";
    viewer.classList.add("loading");
    zoomLabel.textContent = "…";
    setStatus({ text: "Opening drawing…", busy: true }, false);

    const body = new FormData();
    body.append("file", file);
    body.append("units", document.getElementById("units").value);

    try {
      const res = await fetch("/api/preview", { method: "POST", body: body });
      // A newer file was picked while this was in flight; drop the result.
      if (token !== previewToken) return;
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Preview failed.");

      // Size the stage from the aspect ratio the server measured, rather
      // than relying on the browser to infer an SVG's intrinsic height
      // from its viewBox. Both formats then measure identically.
      const BASE_WIDTH = 1200;
      stage.style.width = BASE_WIDTH + "px";
      stage.style.height = BASE_WIDTH / (data.aspect || 1) + "px";

      if (data.format === "svg") {
        stage.innerHTML = data.svg;
      } else {
        const img = document.createElement("img");
        img.alt = "Preview of the drawing";
        img.src = "data:image/png;base64," + data.png_b64;
        stage.appendChild(img);
        await img.decode().catch(() => {});
      }
      if (data.note) {
        viewerNote.textContent = data.note;
        viewerNote.hidden = false;
      }
      setStatus(null);
      // Wait for layout so the fit measurement sees real dimensions.
      requestAnimationFrame(fitToViewer);
    } catch (err) {
      if (token !== previewToken) return;
      // A failed preview must not block converting: the PDF path may well
      // succeed, and the drawing is still perfectly valid.
      viewerPanel.hidden = true;
      setStatus("Preview unavailable: " + err.message, true);
    } finally {
      if (token === previewToken) viewer.classList.remove("loading");
    }
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
