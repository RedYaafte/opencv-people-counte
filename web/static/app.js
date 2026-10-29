const $ = (id) => document.getElementById(id);
const ui = {
  uploadTab: $("tab-upload"), cameraTab: $("tab-camera"),
  uploadPanel: $("panel-upload"), cameraPanel: $("panel-camera"),
  file: $("video-file"), fileName: $("file-name"), orientation: $("orientation"),
  position: $("line-position"), positionValue: $("position-value"),
  entryDirection: $("entry-direction"), directionHint: $("direction-hint"),
  start: $("start-button"), stop: $("stop-button"), replay: $("replay-button"),
  notice: $("notice-message"), error: $("error-message"),
  source: $("source-description"), status: $("status-pill"), stageEmpty: $("stage-empty"),
  image: $("analysis-image"), camera: $("camera-preview"), video: $("result-video"),
  canvas: $("capture-canvas"), progress: $("progress-fill"),
  progressTrack: document.querySelector(".progress-track"), progressLabel: $("progress-label"),
  download: $("download-link"), entries: $("entries-value"), exits: $("exits-value"),
  occupancy: $("occupancy-value"), time: $("session-time"), chart: $("flow-chart"),
  eventsBody: $("events-body"), eventCount: $("event-count"),
  sessions: $("session-list"), sideBefore: $("side-before"), sideAfter: $("side-after"),
  sampleLine: document.querySelector(".sample-line"),
  deleteDialog: $("delete-dialog"), deleteName: $("delete-session-name"),
  deleteError: $("delete-error"), deleteCancel: $("delete-cancel"),
  deleteConfirm: $("delete-confirm"),
};

let mode = "upload";
let currentSession = null;
let currentEvents = [];
let pollingTimer = null;
let pollBusy = false;
let cameraStream = null;
let cameraSocket = null;
let cameraRunning = false;
let frameUrl = null;
let pendingDelete = null;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = null;
  try { body = await response.json(); } catch { /* Empty response. */ }
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return body;
}

function showError(message) {
  ui.error.textContent = message;
  ui.error.hidden = false;
}

function clearError() {
  ui.error.textContent = "";
  ui.error.hidden = true;
}

function showNotice(message) {
  ui.notice.textContent = message;
  ui.notice.hidden = false;
}

function clearNotice() {
  ui.notice.textContent = "";
  ui.notice.hidden = true;
}

function isActive() {
  return currentSession && ["queued", "running"].includes(currentSession.status);
}

function config() {
  return {
    orientation: ui.orientation.value,
    line_position: Number(ui.position.value) / 100,
    entry_direction: ui.entryDirection.value,
  };
}

function settingsChanged() {
  if (!currentSession || currentSession.source_type !== "upload") return false;
  const selected = config();
  return selected.orientation !== currentSession.orientation
    || selected.line_position !== currentSession.line_position
    || selected.entry_direction !== currentSession.entry_direction;
}

function canReanalyze() {
  return mode === "upload" && !ui.file.files.length && currentSession?.status === "completed"
    && Boolean(currentSession.source_sha256) && settingsChanged();
}

function updateDirectionLabels() {
  const vertical = ui.orientation.value === "vertical";
  const reverse = ui.entryDirection.value === "reverse";
  ui.entryDirection.options[0].text = vertical ? "Left → right" : "Top → bottom";
  ui.entryDirection.options[1].text = vertical ? "Right → left" : "Bottom → top";
  ui.positionValue.value = `${ui.position.value}%`;
  ui.sideBefore.textContent = reverse ? "ENTRY SIDE" : "EXIT SIDE";
  ui.sideAfter.textContent = reverse ? "EXIT SIDE" : "ENTRY SIDE";
  ui.sampleLine.classList.toggle("is-vertical", vertical);
  ui.directionHint.textContent = "The opposite direction counts as an exit.";
  refreshControls();
}

function refreshControls() {
  const busy = Boolean(isActive()) || cameraRunning;
  const needsOriginal = mode === "upload" && !ui.file.files.length
    && currentSession?.source_type === "upload" && currentSession.status === "completed"
    && settingsChanged() && !currentSession.source_sha256;
  ui.uploadTab.disabled = busy;
  ui.cameraTab.disabled = busy;
  ui.file.disabled = busy;
  ui.orientation.disabled = busy;
  ui.position.disabled = busy;
  ui.entryDirection.disabled = busy;
  ui.start.disabled = busy || (mode === "upload" && !ui.file.files.length && !canReanalyze());
  ui.start.textContent = mode === "camera" ? "Start camera"
    : canReanalyze() ? "Reanalyze with new settings"
      : needsOriginal ? "Upload original video" : "Analyze video";
  ui.stop.hidden = !cameraRunning;
  ui.replay.hidden = !(currentSession?.source_type === "upload" && currentSession.output_available);
  for (const button of ui.sessions.querySelectorAll("button")) {
    button.disabled = busy || (button.classList.contains("history-delete") && button.dataset.active === "true");
  }
}

function setMode(next) {
  if (isActive() || cameraRunning) return;
  mode = next;
  const upload = mode === "upload";
  ui.uploadPanel.hidden = !upload;
  ui.cameraPanel.hidden = upload;
  ui.uploadTab.classList.toggle("is-selected", upload);
  ui.cameraTab.classList.toggle("is-selected", !upload);
  ui.uploadTab.setAttribute("aria-selected", String(upload));
  ui.cameraTab.setAttribute("aria-selected", String(!upload));
  refreshControls();
}

function setStatus(status) {
  const labels = { idle: "Idle", queued: "Queued", running: "Analyzing", completed: "Completed", failed: "Failed" };
  ui.status.textContent = labels[status] || status;
  ui.status.dataset.status = status;
}

function showStage(element) {
  for (const item of [ui.stageEmpty, ui.image, ui.camera, ui.video]) item.hidden = item !== element;
}

function showImage(blob) {
  const next = URL.createObjectURL(blob);
  ui.image.onload = () => {
    if (frameUrl) URL.revokeObjectURL(frameUrl);
    frameUrl = next;
  };
  ui.image.src = next;
  showStage(ui.image);
}

function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(seconds || 0));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

function setProgress(session) {
  const percent = session.total_frames
    ? Math.min(100, Math.round((session.frames / session.total_frames) * 100))
    : session.status === "completed" ? 100 : 0;
  ui.progress.style.width = `${percent}%`;
  ui.progressTrack.setAttribute("aria-valuenow", String(percent));
  ui.progressLabel.textContent = session.source_type === "camera" || session.status === "completed"
    ? `${session.frames} frames analyzed`
    : session.total_frames
      ? `${percent}% · ${session.frames} of ${session.total_frames} frames`
      : `${session.frames} frames analyzed`;
}

function renderEvents(events) {
  ui.eventsBody.replaceChildren();
  ui.eventCount.textContent = String(events.length);
  if (!events.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.className = "empty-cell";
    cell.textContent = currentSession ? "No crossings recorded in this session." : "Start an analysis to see events.";
    row.append(cell);
    ui.eventsBody.append(row);
    return;
  }
  for (const event of [...events].reverse()) {
    const row = document.createElement("tr");
    const time = document.createElement("td");
    time.textContent = formatTime(event.time_seconds);
    const track = document.createElement("td");
    track.textContent = `#${event.track_id}`;
    const direction = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `direction-badge ${event.direction}`;
    badge.textContent = event.direction === "entry" ? "Entry" : "Exit";
    direction.append(badge);
    row.append(time, track, direction);
    ui.eventsBody.append(row);
  }
}

function renderChart() {
  const canvas = ui.chart;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(280, canvas.getBoundingClientRect().width);
  const height = 260;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  const left = 42, right = width - 16, top = 18, bottom = height - 32;
  const elapsed = Math.max(1, currentSession?.elapsed_seconds || 0);
  let entries = 0, exits = 0;
  const points = [{ t: 0, entries: 0, exits: 0, occupancy: 0 }];
  for (const event of currentEvents) {
    if (event.direction === "entry") entries += 1;
    else exits += 1;
    points.push({ t: event.time_seconds, entries, exits, occupancy: entries - exits });
  }
  points.push({ t: elapsed, entries, exits, occupancy: entries - exits });
  const values = points.flatMap((p) => [p.entries, p.exits, p.occupancy]);
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const x = (t) => left + (Math.min(t, elapsed) / elapsed) * (right - left);
  const y = (v) => bottom - ((v - min) / (max - min)) * (bottom - top);
  ctx.font = '11px Cantarell, sans-serif';
  ctx.fillStyle = "#64716e";
  ctx.strokeStyle = "#e1e5df";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const value = min + ((max - min) * i) / 4;
    const py = y(value);
    ctx.beginPath(); ctx.moveTo(left, py); ctx.lineTo(right, py); ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(Number.isInteger(value) ? String(value) : value.toFixed(1), left - 8, py + 4);
  }
  ctx.textAlign = "left"; ctx.fillText("00:00", left, height - 8);
  ctx.textAlign = "right"; ctx.fillText(formatTime(elapsed), right, height - 8);
  if (!currentEvents.length) {
    ctx.textAlign = "center";
    ctx.fillStyle = "#74817c";
    ctx.font = '13px Cantarell, sans-serif';
    ctx.fillText("Crossing activity will appear here", (left + right) / 2, (top + bottom) / 2);
    return;
  }
  const colors = { entries: "#16816f", exits: "#bc4d42", occupancy: "#4d62a7" };
  for (const key of ["entries", "exits", "occupancy"]) {
    ctx.beginPath();
    ctx.moveTo(x(points[0].t), y(points[0][key]));
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(x(points[i].t), y(points[i - 1][key]));
      ctx.lineTo(x(points[i].t), y(points[i][key]));
    }
    ctx.strokeStyle = colors[key];
    ctx.lineWidth = key === "occupancy" ? 3 : 2;
    ctx.lineJoin = "round";
    ctx.stroke();
  }
}

function updateSession(session, events = currentEvents) {
  if (!session || (currentSession && session.id !== currentSession.id)) return;
  currentSession = session;
  currentEvents = events || [];
  ui.source.textContent = session.source_name;
  setStatus(session.status);
  ui.entries.textContent = String(session.entries);
  ui.exits.textContent = String(session.exits);
  ui.occupancy.textContent = String(session.occupancy);
  ui.time.textContent = `${formatTime(session.elapsed_seconds)} elapsed`;
  setProgress(session);
  renderEvents(currentEvents);
  renderChart();
  ui.download.hidden = !session.output_available;
  if (session.output_available) ui.download.href = `/api/sessions/${session.id}/video`;
  if (session.status === "failed") showError(session.error || "Analysis failed. Try a different source.");
  if (session.status === "completed" && session.output_available && ui.video.dataset.sessionId !== session.id) {
    ui.video.src = `/api/sessions/${session.id}/video`;
    ui.video.dataset.sessionId = session.id;
    showStage(ui.video);
  }
  refreshControls();
}

async function fetchPreview(sessionId) {
  const response = await fetch(`/api/sessions/${sessionId}/frame`, { cache: "no-store" });
  if (response.ok && response.status !== 204 && currentSession?.id === sessionId) showImage(await response.blob());
}

async function pollSession() {
  if (!currentSession || pollBusy) return;
  pollBusy = true;
  try {
    const id = currentSession.id;
    const session = await api(`/api/sessions/${id}`);
    if (currentSession?.id !== id) return;
    updateSession(session, session.events);
    if (session.source_type === "upload" && ["queued", "running"].includes(session.status)) await fetchPreview(id);
    if (session.source_type === "camera" && session.status === "completed" && !ui.stageEmpty.hidden) await fetchPreview(id);
    if (["completed", "failed"].includes(session.status)) {
      clearInterval(pollingTimer);
      pollingTimer = null;
      await loadRecent();
    }
  } catch (error) {
    showError(`Could not load session progress: ${error.message}`);
  } finally {
    pollBusy = false;
  }
}

function beginPolling() {
  clearInterval(pollingTimer);
  pollingTimer = setInterval(pollSession, 750);
  pollSession();
}

async function loadRecent() {
  try {
    const sessions = await api("/api/sessions");
    ui.sessions.replaceChildren();
    if (!sessions.length) {
      const item = document.createElement("li");
      item.className = "history-empty";
      item.textContent = "No sessions yet.";
      ui.sessions.append(item);
      return sessions;
    }
    for (const session of sessions) {
      const item = document.createElement("li");
      const row = document.createElement("div");
      row.className = "history-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history-select";
      button.classList.toggle("is-current", session.id === currentSession?.id);
      button.disabled = Boolean(isActive()) || cameraRunning;
      const title = document.createElement("strong");
      title.textContent = session.source_name;
      const meta = document.createElement("span");
      meta.textContent = `${new Date(session.created_at).toLocaleString()} · ${session.entries} in / ${session.exits} out`;
      button.append(title, meta);
      button.addEventListener("click", () => selectSession(session.id));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "history-delete";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete session ${session.source_name}`);
      remove.dataset.active = String(["queued", "running"].includes(session.status));
      remove.disabled = Boolean(isActive()) || cameraRunning || ["queued", "running"].includes(session.status);
      remove.addEventListener("click", () => confirmDelete(session));
      row.append(button, remove);
      item.append(row);
      ui.sessions.append(item);
    }
    return sessions;
  } catch (error) {
    showError(`Could not load session history: ${error.message}`);
    return [];
  }
}

function confirmDelete(session) {
  if (isActive() || cameraRunning || ["queued", "running"].includes(session.status)) return;
  pendingDelete = session;
  ui.deleteName.textContent = session.source_name;
  ui.deleteError.hidden = true;
  ui.deleteError.textContent = "";
  ui.deleteDialog.showModal();
}

function resetSelectedSession() {
  clearInterval(pollingTimer);
  pollingTimer = null;
  currentSession = null;
  currentEvents = [];
  if (frameUrl) { URL.revokeObjectURL(frameUrl); frameUrl = null; }
  ui.video.pause();
  ui.video.removeAttribute("src");
  ui.video.dataset.sessionId = "";
  ui.video.load();
  ui.image.removeAttribute("src");
  ui.file.value = "";
  ui.fileName.textContent = "Choose a video file";
  ui.source.textContent = "No source selected";
  ui.download.hidden = true;
  ui.replay.hidden = true;
  ui.entries.textContent = "0";
  ui.exits.textContent = "0";
  ui.occupancy.textContent = "0";
  ui.time.textContent = "00:00 elapsed";
  ui.progress.style.width = "0%";
  ui.progressTrack.setAttribute("aria-valuenow", "0");
  ui.progressLabel.textContent = "Ready when you are";
  setStatus("idle");
  showStage(ui.stageEmpty);
  renderEvents([]);
  renderChart();
  refreshControls();
}

async function deletePendingSession() {
  if (!pendingDelete) return;
  const session = pendingDelete;
  const videoWasSelected = currentSession?.id === session.id && Boolean(ui.video.getAttribute("src"));
  ui.deleteConfirm.disabled = true;
  ui.deleteCancel.disabled = true;
  ui.deleteConfirm.textContent = "Deleting…";
  try {
    if (videoWasSelected) {
      ui.video.pause();
      ui.video.removeAttribute("src");
      ui.video.load();
    }
    await api(`/api/sessions/${session.id}`, { method: "DELETE" });
    pendingDelete = null;
    ui.deleteDialog.close();
    if (currentSession?.id === session.id) resetSelectedSession();
    const sessions = await loadRecent();
    if (!currentSession && sessions[0]) await selectSession(sessions[0].id);
    showNotice("Session and its stored data were deleted.");
    clearError();
  } catch (error) {
    if (videoWasSelected) ui.video.src = `/api/sessions/${session.id}/video`;
    ui.deleteError.textContent = `Could not delete session: ${error.message}`;
    ui.deleteError.hidden = false;
  } finally {
    ui.deleteConfirm.disabled = false;
    ui.deleteCancel.disabled = false;
    ui.deleteConfirm.textContent = "Delete session";
  }
}

async function selectSession(id) {
  if (isActive() || cameraRunning) return;
  clearError();
  clearNotice();
  if (frameUrl) { URL.revokeObjectURL(frameUrl); frameUrl = null; }
  ui.video.removeAttribute("src");
  ui.video.dataset.sessionId = "";
  showStage(ui.stageEmpty);
  try {
    const session = await api(`/api/sessions/${id}`);
    setMode(session.source_type === "camera" ? "camera" : "upload");
    ui.file.value = "";
    ui.fileName.textContent = "Choose a video file";
    ui.orientation.value = session.orientation;
    ui.position.value = String(Math.round(session.line_position * 100));
    ui.entryDirection.value = session.entry_direction;
    currentSession = session;
    updateDirectionLabels();
    updateSession(session, session.events);
    if (session.source_type === "camera") await fetchPreview(id);
    if (["queued", "running"].includes(session.status)) beginPolling();
    await loadRecent();
  } catch (error) {
    showError(error.message);
  }
}

async function activateUploadSession(response) {
  ui.file.value = "";
  ui.fileName.textContent = "Choose another video file";
  if (response.reused) {
    const session = await api(`/api/sessions/${response.id}`);
    currentSession = session;
    updateSession(session, session.events);
    showStage(session.output_available ? ui.video : ui.stageEmpty);
    showNotice(session.output_available
      ? "Saved result reused. No new analysis was run."
      : "This video is already being analyzed in another session.");
    if (["queued", "running"].includes(session.status)) beginPolling();
  } else {
    currentSession = response;
    currentEvents = [];
    showStage(ui.stageEmpty);
    updateSession(response, []);
    beginPolling();
  }
  await loadRecent();
}

async function startUpload() {
  if (!ui.file.files.length) return;
  clearError();
  clearNotice();
  const previous = currentSession;
  ui.start.disabled = true;
  ui.start.textContent = "Uploading…";
  ui.source.textContent = ui.file.files[0].name;
  setStatus("queued");
  const params = new URLSearchParams({ filename: ui.file.files[0].name, ...config() });
  try {
    const session = await api(`/api/sessions/upload?${params}`, { method: "POST", body: ui.file.files[0] });
    await activateUploadSession(session);
  } catch (error) {
    setStatus(previous?.status || "idle");
    ui.source.textContent = previous?.source_name || "No source selected";
    showError(`Upload failed: ${error.message}`);
  } finally {
    refreshControls();
  }
}

async function startReanalysis() {
  if (!canReanalyze()) return;
  clearError();
  clearNotice();
  ui.start.disabled = true;
  ui.start.textContent = "Preparing analysis…";
  try {
    const session = await api(`/api/sessions/${currentSession.id}/reanalyze`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config()),
    });
    await activateUploadSession(session);
  } catch (error) {
    showError(`Could not reanalyze video: ${error.message}`);
  } finally {
    refreshControls();
  }
}

function replayResult() {
  if (!currentSession?.output_available || currentSession.source_type !== "upload") return;
  clearError();
  if (ui.video.dataset.sessionId !== currentSession.id) {
    ui.video.src = `/api/sessions/${currentSession.id}/video`;
    ui.video.dataset.sessionId = currentSession.id;
  }
  if (ui.video.error) ui.video.load();
  showStage(ui.video);
  ui.video.currentTime = 0;
  ui.video.play().catch(() => showError("Playback could not start. Use the video controls to try again."));
  showNotice(settingsChanged()
    ? "Playing the saved result with its original line. Reanalyze to apply your changes."
    : "Playing the saved result. No analysis was run.");
}

function stopCamera() {
  const id = currentSession?.source_type === "camera" ? currentSession.id : null;
  cameraRunning = false;
  if (cameraSocket && cameraSocket.readyState === WebSocket.OPEN) cameraSocket.send("stop");
  if (cameraSocket) cameraSocket.close();
  cameraSocket = null;
  if (cameraStream) {
    for (const track of cameraStream.getTracks()) track.stop();
    cameraStream = null;
  }
  ui.camera.srcObject = null;
  if (id) fetch(`/api/sessions/${id}/cancel`, { method: "POST", keepalive: true }).catch(() => {});
  refreshControls();
  pollSession();
}

function sendCameraFrame() {
  if (!cameraRunning || cameraSocket?.readyState !== WebSocket.OPEN) return;
  if (ui.camera.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    setTimeout(sendCameraFrame, 150);
    return;
  }
  const width = Math.min(640, ui.camera.videoWidth);
  const height = Math.round((width / ui.camera.videoWidth) * ui.camera.videoHeight);
  ui.canvas.width = width;
  ui.canvas.height = height;
  ui.canvas.getContext("2d").drawImage(ui.camera, 0, 0, width, height);
  ui.canvas.toBlob((blob) => {
    if (blob && cameraRunning && cameraSocket?.readyState === WebSocket.OPEN) cameraSocket.send(blob);
  }, "image/jpeg", 0.75);
}

async function startCamera() {
  clearError();
  clearNotice();
  ui.start.disabled = true;
  ui.start.textContent = "Opening camera…";
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    ui.camera.srcObject = cameraStream;
    await ui.camera.play();
    showStage(ui.camera);
    const session = await api("/api/sessions/camera", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config()),
    });
    currentSession = session;
    currentEvents = [];
    cameraRunning = true;
    updateSession(session, []);
    await loadRecent();
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    cameraSocket = new WebSocket(`${protocol}//${location.host}/ws/sessions/${session.id}`);
    cameraSocket.binaryType = "blob";
    cameraSocket.onopen = () => sendCameraFrame();
    cameraSocket.onmessage = (message) => {
      if (typeof message.data === "string") {
        const payload = JSON.parse(message.data);
        if (payload.error) { showError(payload.error); stopCamera(); return; }
        updateSession(payload.session, payload.events);
      } else {
        showImage(message.data);
        setTimeout(sendCameraFrame, 140);
      }
    };
    cameraSocket.onerror = () => showError("The camera connection failed. Stop and try again.");
    cameraSocket.onclose = () => {
      if (cameraRunning) {
        showError("Camera connection closed. Start a new session to continue.");
        stopCamera();
      }
    };
    beginPolling();
    refreshControls();
  } catch (error) {
    if (cameraRunning) stopCamera();
    else if (cameraStream) {
      for (const track of cameraStream.getTracks()) track.stop();
      cameraStream = null;
    }
    ui.camera.srcObject = null;
    showStage(ui.stageEmpty);
    setStatus("idle");
    showError(`Could not start camera: ${error.message}`);
    refreshControls();
  }
}

ui.uploadTab.addEventListener("click", () => setMode("upload"));
ui.cameraTab.addEventListener("click", () => setMode("camera"));
for (const tab of [ui.uploadTab, ui.cameraTab]) {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "upload" : event.key === "End" ? "camera" : mode === "upload" ? "camera" : "upload";
    setMode(next);
    (next === "upload" ? ui.uploadTab : ui.cameraTab).focus();
  });
}
ui.file.addEventListener("change", () => {
  ui.fileName.textContent = ui.file.files[0]?.name || "Choose a video file";
  refreshControls();
});
ui.orientation.addEventListener("change", updateDirectionLabels);
ui.entryDirection.addEventListener("change", updateDirectionLabels);
ui.position.addEventListener("input", updateDirectionLabels);
ui.start.addEventListener("click", () => {
  if (mode === "camera") startCamera();
  else if (ui.file.files.length) startUpload();
  else startReanalysis();
});
ui.stop.addEventListener("click", stopCamera);
ui.replay.addEventListener("click", replayResult);
ui.deleteCancel.addEventListener("click", () => ui.deleteDialog.close());
ui.deleteConfirm.addEventListener("click", deletePendingSession);
ui.deleteDialog.addEventListener("close", () => { pendingDelete = null; });
ui.deleteDialog.addEventListener("cancel", (event) => {
  if (ui.deleteConfirm.disabled) event.preventDefault();
});
window.addEventListener("beforeunload", () => {
  if (cameraRunning) stopCamera();
  if (frameUrl) URL.revokeObjectURL(frameUrl);
});
new ResizeObserver(renderChart).observe(ui.chart);

updateDirectionLabels();
refreshControls();
renderEvents([]);
renderChart();
loadRecent().then((sessions) => {
  if (sessions[0]) selectSession(sessions[0].id);
});
