const state = {
  template: null,
  slots: [],
  assets: [],
  activeAsset: null,
  activeSlot: null,
  assignments: {},
  pendingSlotFileTarget: null,
  soloSlot: false,
  editHotspots: false,
  dragState: null,
  createHotspotMode: false,
  pendingHotspotDraft: null,
  justDraggedHotspot: false,
  lastHitSlotIds: [],
  zoom: 1
};

const $ = (id) => document.getElementById(id);
const UPLOAD_CONCURRENCY = 3;

function getSlotFileInput() {
  let input = $("slotFileInput");
  if (!input) {
    input = document.createElement("input");
    input.id = "slotFileInput";
    input.type = "file";
    input.accept = "image/*";
    input.className = "file-input-hidden";
    document.body.appendChild(input);
  }
  return input;
}

function setStatus(text) {
  $("status").textContent = text;
}

function showTemplateLoading(message) {
  const modal = $("templateLoadingModal");
  const text = $("templateLoadingText");
  if (text && message) text.textContent = message;
  if (modal) modal.hidden = false;
}

function hideTemplateLoading() {
  const modal = $("templateLoadingModal");
  if (modal) modal.hidden = true;
}

function syncControls() {
  const hasSlots = state.slots.length > 0;
  const hasActiveSlot = Boolean(state.activeSlot && slotById(state.activeSlot));
  const clearHotspotsBtn = $("clearHotspots");
  const clearImagesBtn = $("clearImages");
  const deleteHotspotBtn = $("deleteHotspot");
  const saveSlotsBtn = $("saveSlots");
  const saveSlotsPanelBtn = $("saveSlotsPanel");
  const toggleSoloBtn = $("toggleSoloSlot");
  const hasAssignments = Object.keys(state.assignments).length > 0;
  if (clearHotspotsBtn) clearHotspotsBtn.disabled = !hasSlots;
  if (clearImagesBtn) clearImagesBtn.disabled = !hasAssignments;
  if (deleteHotspotBtn) deleteHotspotBtn.disabled = !hasActiveSlot;
  if (saveSlotsBtn) saveSlotsBtn.disabled = !hasSlots;
  if (saveSlotsPanelBtn) saveSlotsPanelBtn.disabled = !hasSlots;
  if (toggleSoloBtn) toggleSoloBtn.disabled = !hasActiveSlot;
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`服务返回了非 JSON 内容：${text.slice(0, 120)}`);
  }
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function loadMeta() {
  setStatus("正在读取项目");
  const data = await requestJson("/api/meta");
  if (data.empty) {
    state.template = data.template;
    state.slots = [];
    state.assignments = {};
    $("templateImg").removeAttribute("src");
    $("topOverlayImg").removeAttribute("src");
    $("canvas").classList.add("empty");
    $("canvas").style.width = `${data.template.previewWidth}px`;
    $("canvas").style.height = `${data.template.previewHeight}px`;
    renderSlots();
    fitView();
    setStatus("空白画布。请新建/导入 PSD 或 PSB 模板");
    return;
  }
  state.template = data.template;
  state.slots = data.slots;
  $("templateImg").src = `${data.template.previewImage}&t=${Date.now()}`;
  $("topOverlayImg").src = `${data.template.topOverlayImage}&t=${Date.now()}`;
  $("canvas").classList.remove("empty");
  $("canvas").style.width = `${data.template.previewWidth}px`;
  $("canvas").style.height = `${data.template.previewHeight}px`;
  setStatus(`${data.template.width} x ${data.template.height}，${data.slots.length} 个图片位`);
  renderSlots();
  fitView();
}

async function newTemplate() {
  await requestJson("/api/new-template", { method: "POST" });
  state.template = { width: 2400, height: 1800, previewWidth: 1200, previewHeight: 900, scale: 0.5 };
  state.slots = [];
  state.assignments = {};
  $("templateImg").removeAttribute("src");
  $("topOverlayImg").removeAttribute("src");
  $("canvas").classList.add("empty");
  $("canvas").style.width = "1200px";
  $("canvas").style.height = "900px";
  renderSlots();
  fitView();
  setStatus("已新建空白模板，请导入 PSD/PSB");
}

async function uploadTemplate(file) {
  if (!file) return;
  const button = $("templateBtn");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "导入中...";
  showTemplateLoading("正在上传并解析 PSD/PSB，大文件可能需要 30-60 秒。");
  setStatus("正在导入模板，请等待");
  try {
    const body = new FormData();
    body.append("file", file);
    window.setTimeout(() => {
      showTemplateLoading("正在读取图层并生成预览，请保持页面打开。");
    }, 1200);
    const data = await requestJson("/api/template", { method: "POST", body });
    state.template = data.template;
    state.slots = [];
    state.assignments = {};
    $("templateImg").src = `${data.template.previewImage}&t=${Date.now()}`;
    $("topOverlayImg").src = `${data.template.topOverlayImage}&t=${Date.now()}`;
    $("canvas").classList.remove("empty");
    $("canvas").style.width = `${data.template.previewWidth}px`;
    $("canvas").style.height = `${data.template.previewHeight}px`;
    renderSlots();
    fitView();
    setStatus("模板已导入。现在可手动框选图片位，或点击一键识别图片位");
  } catch (error) {
    console.error(error);
    setStatus(`模板导入失败：${error.message}`);
    alert(`模板导入失败：${error.message}`);
  } finally {
    hideTemplateLoading();
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function detectSlots() {
  const button = $("detectSlotsBtn");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "识别中...";
  setStatus("正在识别图片位，请等待");
  try {
    const data = await requestJson("/api/detect-slots", { method: "POST" });
    state.slots = data.slots || [];
    state.assignments = {};
    renderSlots();
    setStatus(`已识别 ${state.slots.length} 个图片位，可继续编辑后保存`);
  } catch (error) {
    console.error(error);
    setStatus(`识别图片位失败：${error.message}`);
    alert(`识别图片位失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function assetById(assetId) {
  return state.assets.find((asset) => asset.id === assetId);
}

function removeAsset(assetId) {
  state.assets = state.assets.filter((asset) => asset.id !== assetId);
  if (state.activeAsset === assetId) {
    state.activeAsset = state.assets[0]?.id || null;
  }
  Object.entries(state.assignments).forEach(([slotId, assignedAssetId]) => {
    if (assignedAssetId === assetId) {
      delete state.assignments[slotId];
    }
  });
  renderAssets();
  renderSlots();
  setStatus("素材已删除");
}

function clearSlot(slotId) {
  delete state.assignments[slotId];
  state.activeSlot = slotId;
  renderSlots();
  setStatus("图片位已清空");
}

function closeHitMenu() {
  const menu = $("hitMenu");
  menu.hidden = true;
  menu.innerHTML = "";
}

function recommendedHotspotNumber() {
  return state.slots.length + 1;
}

function closeHotspotNumberModal() {
  const modal = $("hotspotNumberModal");
  if (modal) modal.hidden = true;
  state.pendingHotspotDraft = null;
}

function openHotspotNumberModal(draft) {
  const recommended = recommendedHotspotNumber();
  state.pendingHotspotDraft = draft;
  if (!$("hotspotNumberModal") || !$("hotspotNumberInput")) {
    const value = window.prompt(`请输入新图片位编号（推荐 ${recommended}）`, String(recommended));
    if (value === null) {
      state.pendingHotspotDraft = null;
      renderSlots();
      setStatus("已取消新增图片位");
      return;
    }
    const number = Number.parseInt(value, 10);
    if (!Number.isFinite(number)) {
      state.pendingHotspotDraft = null;
      renderSlots();
      setStatus("编号无效，已取消新增图片位");
      return;
    }
    createHotspotFromDraft(number);
    return;
  }
  $("hotspotNumberInput").max = String(state.slots.length + 1);
  $("hotspotNumberInput").value = String(recommended);
  $("hotspotNumberHint").textContent = `系统推荐编号：${recommended}。可改为 1-${state.slots.length + 1}，确认后按编号插入图片位。`;
  $("hotspotNumberModal").hidden = false;
  window.setTimeout(() => {
    $("hotspotNumberInput").focus();
    $("hotspotNumberInput").select();
  }, 0);
}

function normalizeHotspotNames() {
  state.slots.forEach((slot, index) => {
    if (slot.source === "manual" || /^自定义图片位\s+\d+$/.test(slot.name || "")) {
      slot.name = `自定义图片位 ${index + 1}`;
    }
  });
}

function createHotspotFromDraft(number) {
  const draft = state.pendingHotspotDraft;
  if (!draft) return;
  const maxNumber = state.slots.length + 1;
  const normalizedNumber = Math.max(1, Math.min(maxNumber, number));
  const id = `manual_${Date.now()}`;
  const slot = {
    id,
    name: `自定义图片位 ${normalizedNumber}`,
    x: draft.x,
    y: draft.y,
    w: draft.w,
    h: draft.h,
    source: "manual",
    layer_key: "",
    slot_type: "image",
    visible: true
  };
  state.slots.splice(normalizedNumber - 1, 0, slot);
  normalizeHotspotNames();
  state.activeSlot = id;
  state.editHotspots = true;
  $("toggleEditHotspots").classList.add("active");
  closeHotspotNumberModal();
  renderSlots();
  setStatus(`已新增第 ${normalizedNumber} 个图片位，记得保存图片位`);
}

function clearActiveSlot() {
  if (!state.activeSlot) return;
  clearSlot(state.activeSlot);
}

function renderAssets() {
  const grid = $("assetGrid");
  grid.innerHTML = "";
  state.assets.forEach((asset) => {
    const item = document.createElement("div");
    item.className = `asset ${asset.id === state.activeAsset ? "active" : ""}`;
    item.title = asset.name;
    item.innerHTML = `
      <button class="asset-main" type="button">
        <img src="${asset.thumbUrl || asset.url}" alt="" loading="lazy" decoding="async">
      </button>
      <button class="asset-remove" type="button" title="删除素材">×</button>
    `;
    item.querySelector(".asset-main").addEventListener("click", () => {
      state.activeAsset = asset.id;
      renderAssets();
    });
    item.querySelector(".asset-remove").addEventListener("click", (event) => {
      event.stopPropagation();
      removeAsset(asset.id);
    });
    grid.appendChild(item);
  });
}

function renderSlots() {
  const list = $("slotList");
  const overlay = $("overlay");
  list.innerHTML = "";
  overlay.innerHTML = "";
  closeHitMenu();
  const scale = state.template.scale;

  if (!state.slots.length) {
    const empty = document.createElement("div");
    empty.className = "empty-list";
    empty.textContent = "还没有图片位。点击新增图片位，或一键识别。";
    list.appendChild(empty);
  }

  state.slots.forEach((slot, index) => {
    if (state.soloSlot && state.activeSlot && slot.id !== state.activeSlot) {
      return;
    }
    const assigned = state.assignments[slot.id];
    const item = document.createElement("div");
    item.className = `slot-item ${slot.id === state.activeSlot ? "active" : ""}`;
    item.innerHTML = `
      <button class="slot-main" type="button">
        <div class="slot-name">${index + 1}. ${slot.name}</div>
        <div class="slot-meta">${slot.x}, ${slot.y}, ${slot.w} x ${slot.h}${assigned ? " · 已放入" : ""}</div>
        <select class="slot-type">
          <option value="image" selected>图片位</option>
        </select>
      </button>
      <div class="layer-actions">
        <button type="button" class="choose-slot-file" title="为这个图片位选择图片" data-action="choose">选图</button>
        <button type="button" title="上移一层" data-action="up">↑</button>
        <button type="button" title="下移一层" data-action="down">↓</button>
        <button type="button" title="置顶" data-action="top">顶</button>
        <button type="button" title="置底" data-action="bottom">底</button>
        <button type="button" class="clear-slot" title="清空图片位" data-action="clear">清</button>
        <button type="button" class="delete-slot" title="删除图片位" data-action="delete">删</button>
      </div>
    `;
    item.querySelector(".slot-main").addEventListener("click", () => selectSlot(slot.id));
    item.querySelector(".slot-main").addEventListener("dblclick", () => chooseFileForSlot(slot.id));
    item.querySelector(".slot-type").addEventListener("click", (event) => event.stopPropagation());
    item.querySelector(".slot-type").addEventListener("change", (event) => {
      slot.slot_type = event.target.value;
      state.activeSlot = slot.id;
      renderSlots();
      setStatus("图片位类型已修改，记得保存图片位");
    });
    item.querySelectorAll(".layer-actions button").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (button.dataset.action === "choose") {
          chooseFileForSlot(slot.id);
        } else if (button.dataset.action === "clear") {
          clearSlot(slot.id);
        } else if (button.dataset.action === "delete") {
          deleteHotspot(slot.id);
        } else {
          moveSlot(slot.id, button.dataset.action);
        }
      });
    });
    list.appendChild(item);

    const box = document.createElement("div");
    box.className = `slot-box ${slot.id === state.activeSlot ? "active" : ""} ${assigned ? "assigned" : ""}`;
    box.style.left = `${slot.x * scale}px`;
    box.style.top = `${slot.y * scale}px`;
    box.style.width = `${slot.w * scale}px`;
    box.style.height = `${slot.h * scale}px`;
    box.style.zIndex = String(state.slots.length - index);
    box.innerHTML = `<button class="label" type="button" title="选中图片位 ${index + 1}">${index + 1}</button>`;
    if (state.editHotspots && slot.id === state.activeSlot) {
      const handle = document.createElement("div");
      handle.className = "resize-handle";
      box.appendChild(handle);
    }
    if (assigned) {
      const asset = assetById(assigned);
      if (asset) {
        const img = document.createElement("img");
        img.className = "placed";
        img.src = asset.thumbUrl || asset.url;
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.style.objectFit = $("fitMode").value === "contain" ? "contain" : "cover";
        box.appendChild(img);

        const clear = document.createElement("button");
        clear.className = "slot-clear-overlay";
        clear.type = "button";
        clear.title = "清空图片";
        clear.textContent = "×";
        clear.addEventListener("pointerdown", (event) => {
          event.stopPropagation();
        });
        clear.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          clearSlot(slot.id);
        });
        box.appendChild(clear);
      }
    }
    overlay.appendChild(box);
  });
  if (state.dragState?.mode === "create") {
    const scale = state.template.scale;
    const draft = state.dragState.draft;
    const box = document.createElement("div");
    box.className = "slot-box draft-hotspot";
    box.style.left = `${draft.x * scale}px`;
    box.style.top = `${draft.y * scale}px`;
    box.style.width = `${draft.w * scale}px`;
    box.style.height = `${draft.h * scale}px`;
    overlay.appendChild(box);
  }
  syncControls();
}

function visibleSlotsForHitTest() {
  return state.slots.filter((slot) => {
    if (state.soloSlot && state.activeSlot && slot.id !== state.activeSlot) return false;
    return true;
  });
}

function slotById(slotId) {
  return state.slots.find((slot) => slot.id === slotId);
}

function canvasPoint(event) {
  const rect = $("canvas").getBoundingClientRect();
  const scale = state.template.scale * state.zoom;
  return {
    x: (event.clientX - rect.left) / scale,
    y: (event.clientY - rect.top) / scale
  };
}

function startHotspotEditDrag(event) {
  if (state.createHotspotMode) {
    const point = canvasPoint(event);
    state.dragState = {
      mode: "create",
      startX: point.x,
      startY: point.y,
      draft: { x: Math.round(point.x), y: Math.round(point.y), w: 1, h: 1 }
    };
    closeHitMenu();
    return true;
  }
  if (!state.editHotspots || !state.activeSlot) return false;
  const matches = hitSlotsAt(event.clientX, event.clientY);
  if (!matches.some(({ slot }) => slot.id === state.activeSlot)) return false;
  const slot = slotById(state.activeSlot);
  if (!slot) return false;
  const point = canvasPoint(event);
  const nearRight = Math.abs(point.x - (slot.x + slot.w)) <= 35;
  const nearBottom = Math.abs(point.y - (slot.y + slot.h)) <= 35;
  state.dragState = {
    mode: nearRight && nearBottom ? "resize" : "move",
    slotId: slot.id,
    startX: point.x,
    startY: point.y,
    original: { x: slot.x, y: slot.y, w: slot.w, h: slot.h }
  };
  closeHitMenu();
  return true;
}

function updateHotspotEditDrag(event) {
  if (!state.dragState) return;
  if (state.dragState.mode === "create") {
    const point = canvasPoint(event);
    const x1 = Math.round(Math.min(state.dragState.startX, point.x));
    const y1 = Math.round(Math.min(state.dragState.startY, point.y));
    const x2 = Math.round(Math.max(state.dragState.startX, point.x));
    const y2 = Math.round(Math.max(state.dragState.startY, point.y));
    state.dragState.draft = {
      x: x1,
      y: y1,
      w: Math.max(1, x2 - x1),
      h: Math.max(1, y2 - y1)
    };
    state.justDraggedHotspot = true;
    renderSlots();
    setStatus(`新图片位：${x1}, ${y1}, ${x2 - x1} x ${y2 - y1}`);
    return;
  }
  const slot = slotById(state.dragState.slotId);
  if (!slot) return;
  const point = canvasPoint(event);
  const dx = Math.round(point.x - state.dragState.startX);
  const dy = Math.round(point.y - state.dragState.startY);
  if (state.dragState.mode === "resize") {
    slot.w = Math.max(20, state.dragState.original.w + dx);
    slot.h = Math.max(20, state.dragState.original.h + dy);
  } else {
    slot.x = state.dragState.original.x + dx;
    slot.y = state.dragState.original.y + dy;
  }
  state.justDraggedHotspot = true;
  renderSlots();
  setStatus(`图片位：${slot.x}, ${slot.y}, ${slot.w} x ${slot.h}`);
}

function stopHotspotEditDrag() {
  if (!state.dragState) return;
  if (state.dragState.mode === "create") {
    const draft = state.dragState.draft;
    state.dragState = null;
    state.createHotspotMode = false;
    $("addHotspot").classList.remove("active");
    if (draft.w < 20 || draft.h < 20) {
      renderSlots();
      setStatus("框选太小，已取消新增图片位");
      return;
    }
    renderSlots();
    openHotspotNumberModal(draft);
    setStatus("请确认新图片位编号");
    return;
  }
  state.dragState = null;
  setStatus("图片位已调整，记得保存图片位");
}

function addHotspot() {
  state.createHotspotMode = true;
  state.editHotspots = true;
  $("toggleEditHotspots").classList.add("active");
  $("addHotspot").classList.add("active");
  closeHitMenu();
  setStatus("在模板上按住拖动，框选新增图片位");
}

function deleteActiveHotspot() {
  if (!state.activeSlot) return;
  deleteHotspot(state.activeSlot);
}

function deleteHotspot(slotId) {
  state.slots = state.slots.filter((slot) => slot.id !== slotId);
  delete state.assignments[slotId];
  if (state.activeSlot === slotId) {
    state.activeSlot = state.slots[0]?.id || null;
  }
  renderSlots();
  setStatus("图片位已删除，记得保存图片位");
}

function clearImages() {
  const count = Object.keys(state.assignments).length;
  if (!count) {
    setStatus("当前没有已放入的图片");
    return;
  }
  if (!window.confirm(`确定清空 ${count} 个图片位里的图片？图片位会保留。`)) return;
  state.assignments = {};
  renderSlots();
  setStatus("已清空图片，图片位已保留");
}

async function clearHotspots() {
  if (!state.slots.length) {
    setStatus("当前没有图片位");
    return;
  }
  if (!window.confirm(`确定清空全部 ${state.slots.length} 个图片位？`)) return;
  state.slots = [];
  state.assignments = {};
  state.activeSlot = null;
  state.pendingSlotFileTarget = null;
  state.soloSlot = false;
  state.editHotspots = false;
  state.createHotspotMode = false;
  closeHitMenu();
  $("toggleSoloSlot").classList.remove("active");
  $("toggleSoloSlot").textContent = "只显示选中";
  $("toggleEditHotspots").classList.remove("active");
  $("addHotspot").classList.remove("active");
  renderSlots();
  setStatus("正在清空图片位");
  try {
    await requestJson("/api/slots/clear", { method: "POST" });
    setStatus("图片位已清空");
  } catch (error) {
    console.error(error);
    setStatus(`清空图片位失败：${error.message}`);
    alert(`清空图片位失败：${error.message}`);
  }
}

function hitSlotsAt(clientX, clientY) {
  const canvasRect = $("canvas").getBoundingClientRect();
  const scale = state.template.scale * state.zoom;
  const x = (clientX - canvasRect.left) / scale;
  const y = (clientY - canvasRect.top) / scale;
  return visibleSlotsForHitTest()
    .map((slot, index) => ({ slot, index }))
    .filter(({ slot }) => {
      return x >= slot.x && x <= slot.x + slot.w && y >= slot.y && y <= slot.y + slot.h;
    });
}

function showHitMenu(event, matches, mode) {
  const menu = $("hitMenu");
  menu.innerHTML = "";
  const canvasRect = $("canvas").getBoundingClientRect();
  const left = Math.max(0, (event.clientX - canvasRect.left) / state.zoom);
  const top = Math.max(0, (event.clientY - canvasRect.top) / state.zoom);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;

  matches.forEach(({ slot, index }) => {
    const row = document.createElement("div");
    row.className = "hit-menu-row";
    row.innerHTML = `
      <button type="button" class="hit-select">${index + 1}. ${slot.name}</button>
      <button type="button" class="hit-choose">选图</button>
    `;
    row.querySelector(".hit-select").addEventListener("click", () => {
      selectSlot(slot.id);
      closeHitMenu();
    });
    row.querySelector(".hit-choose").addEventListener("click", () => {
      closeHitMenu();
      chooseFileForSlot(slot.id);
    });
    menu.appendChild(row);
  });

  if (mode === "choose" && matches.length === 1) {
    closeHitMenu();
    chooseFileForSlot(matches[0].slot.id);
    return;
  }

  menu.hidden = false;
}

function handleCanvasHit(event, mode) {
  const matches = hitSlotsAt(event.clientX, event.clientY);
  if (!matches.length) {
    closeHitMenu();
    return;
  }
  state.lastHitSlotIds = matches.map(({ slot }) => slot.id);
  if (matches.length === 1) {
    closeHitMenu();
    if (mode === "choose") {
      chooseFileForSlot(matches[0].slot.id);
    } else {
      selectSlot(matches[0].slot.id);
    }
    return;
  }
  showHitMenu(event, matches, mode);
}

function moveSlot(slotId, action) {
  const index = state.slots.findIndex((slot) => slot.id === slotId);
  if (index < 0) return;
  const [slot] = state.slots.splice(index, 1);
  if (action === "up") {
    state.slots.splice(Math.max(0, index - 1), 0, slot);
  } else if (action === "down") {
    state.slots.splice(Math.min(state.slots.length, index + 1), 0, slot);
  } else if (action === "top") {
    state.slots.unshift(slot);
  } else if (action === "bottom") {
    state.slots.push(slot);
  }
  state.activeSlot = slotId;
  renderSlots();
}

function selectSlot(slotId) {
  state.activeSlot = slotId;
  closeHitMenu();
  renderSlots();
}

function chooseFileForSlot(slotId) {
  state.activeSlot = slotId;
  state.pendingSlotFileTarget = slotId;
  renderSlots();
  const input = getSlotFileInput();
  input.value = "";
  input.click();
}

async function uploadOne(file, index, total) {
  setStatus(`正在上传 ${index + 1}/${total}`);
  const body = new FormData();
  body.append("file", file);
  const data = await requestJson("/api/upload", { method: "POST", body });
  state.assets.push({
    id: data.id,
    url: data.url,
    thumbUrl: data.thumbUrl || data.url,
    name: file.name
  });
  state.activeAsset = data.id;
  renderAssets();
  return data.id;
}

async function uploadForSlot(file, slotId) {
  setStatus("正在上传并放入图片位");
  const assetId = await uploadOne(file, 0, 1);
  state.assignments[slotId] = assetId;
  state.activeSlot = slotId;
  renderAssets();
  renderSlots();
  setStatus("已放入图片位");
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
  let next = 0;
  async function worker() {
    while (next < files.length) {
      const index = next;
      next += 1;
      await uploadOne(files[index], index, files.length);
    }
  }
  const workers = Array.from(
    { length: Math.min(UPLOAD_CONCURRENCY, files.length) },
    () => worker()
  );
  try {
    await Promise.all(workers);
    setStatus(`已上传 ${files.length} 张图`);
  } catch (error) {
    setStatus(error.message);
    throw error;
  }
  renderSlots();
}

function numberedFileIndex(file) {
  const baseName = file.name.replace(/\.[^.]+$/, "").trim();
  if (!/^\d+$/.test(baseName)) return null;
  return Number.parseInt(baseName, 10);
}

async function uploadFolderAndMatch(fileList) {
  const files = Array.from(fileList)
    .filter((file) => file.type.startsWith("image/"))
    .map((file) => ({ file, index: numberedFileIndex(file) }))
    .filter((item) => item.index && item.index >= 1)
    .sort((a, b) => a.index - b.index);

  if (!files.length) {
    setStatus("目录里没有找到 1、2、3 这种编号图片");
    return;
  }

  let matched = 0;
  let skipped = 0;
  for (let i = 0; i < files.length; i += 1) {
    const { file, index } = files[i];
    const slot = state.slots[index - 1];
    setStatus(`正在匹配 ${file.name} -> 第 ${index} 个图片位`);
    const assetId = await uploadOne(file, i, files.length);
    if (slot) {
      state.assignments[slot.id] = assetId;
      matched += 1;
    } else {
      skipped += 1;
    }
  }

  renderAssets();
  renderSlots();
  setStatus(`目录匹配完成：${matched}/${files.length} 张已放入图片位${skipped ? `，${skipped} 张没有对应图片位` : ""}`);
}

function setZoom(value) {
  state.zoom = Math.max(0.12, Math.min(2.5, value));
  $("canvas").style.transform = `scale(${state.zoom})`;
  $("zoomLabel").textContent = `${Math.round(state.zoom * 100)}%`;
}

function fitView() {
  if (!state.template) return;
  const viewport = $("viewport");
  const widthScale = (viewport.clientWidth - 48) / state.template.previewWidth;
  setZoom(Math.min(1, widthScale));
}

async function saveSlots() {
  const buttons = [$("saveSlots"), $("saveSlotsPanel")].filter(Boolean);
  const originalTexts = buttons.map((button) => button.textContent);
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "保存中...";
  });
  setStatus("正在保存图片位");
  try {
    const data = await requestJson("/api/slots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slots: state.slots })
    });
    state.slots = data.slots || state.slots;
    renderSlots();
    setStatus(`图片位已保存，共 ${state.slots.length} 个`);
  } catch (error) {
    console.error(error);
    setStatus(`保存图片位失败：${error.message}`);
    alert(`保存图片位失败：${error.message}`);
  } finally {
    buttons.forEach((button, index) => {
      button.textContent = originalTexts[index];
    });
    syncControls();
  }
}

async function exportImage() {
  const button = $("exportBtn");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "导出中...";
  setStatus("正在导出，请等待 30-60 秒");
  try {
    const data = await requestJson("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assignments: state.assignments,
        slots: state.slots,
        fit: $("fitMode").value,
        renderMode: "fast",
        format: $("format").value
      })
    });
    const link = $("downloadLink");
    link.href = `${data.url}?t=${Date.now()}`;
    link.hidden = false;
    setStatus("导出完成，已生成链接");
    window.open(link.href, "_blank");
  } catch (error) {
    console.error(error);
    setStatus(`导出失败：${error.message}`);
    alert(`导出失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function bindEvents() {
  const input = $("fileInput");
  const templateInput = $("templateInput");
  const folderInput = $("folderInput");
  const slotInput = getSlotFileInput();
  const dropzone = $("dropzone");

  input.addEventListener("change", () => uploadFiles(input.files));
  $("newTemplateBtn").addEventListener("click", newTemplate);
  $("templateBtn").addEventListener("click", () => {
    templateInput.value = "";
    templateInput.click();
  });
  templateInput.addEventListener("change", () => uploadTemplate(templateInput.files[0]));
  $("detectSlotsBtn").addEventListener("click", detectSlots);
  $("folderMatchBtn").addEventListener("click", () => {
    folderInput.value = "";
    folderInput.click();
  });
  folderInput.addEventListener("change", () => uploadFolderAndMatch(folderInput.files));
  slotInput.addEventListener("change", async () => {
    const file = slotInput.files[0];
    const slotId = state.pendingSlotFileTarget;
    slotInput.value = "";
    state.pendingSlotFileTarget = null;
    if (file && slotId) {
      await uploadForSlot(file, slotId);
    }
  });
  ["dragenter", "dragover"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragging");
    });
  });
  dropzone.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));

  $("zoomOut").addEventListener("click", () => setZoom(state.zoom - 0.1));
  $("zoomIn").addEventListener("click", () => setZoom(state.zoom + 0.1));
  $("fitView").addEventListener("click", fitView);
  $("toggleSoloSlot").addEventListener("click", () => {
    state.soloSlot = !state.soloSlot;
    $("toggleSoloSlot").classList.toggle("active", state.soloSlot);
    $("toggleSoloSlot").textContent = state.soloSlot ? "显示全部图片位" : "只显示选中";
    renderSlots();
  });
  $("toggleEditHotspots").addEventListener("click", () => {
    state.editHotspots = !state.editHotspots;
    $("toggleEditHotspots").classList.toggle("active", state.editHotspots);
    setStatus(state.editHotspots ? "编辑图片位：拖动选中框，右下角缩放" : "已退出图片位编辑");
    renderSlots();
  });
  $("addHotspot").addEventListener("click", addHotspot);
  $("deleteHotspot").addEventListener("click", deleteActiveHotspot);
  $("clearImages").addEventListener("click", clearImages);
  $("clearHotspots").addEventListener("click", clearHotspots);
  $("saveSlots").addEventListener("click", saveSlots);
  $("saveSlotsPanel").addEventListener("click", saveSlots);
  $("exportBtn").addEventListener("click", exportImage);
  $("fitMode").addEventListener("change", renderSlots);

  const hotspotNumberForm = $("hotspotNumberForm");
  const cancelHotspotNumber = $("cancelHotspotNumber");
  const hotspotNumberModal = $("hotspotNumberModal");
  if (hotspotNumberForm && cancelHotspotNumber && hotspotNumberModal) {
    hotspotNumberForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const number = Number.parseInt($("hotspotNumberInput").value, 10);
      if (!Number.isFinite(number)) {
        setStatus("请输入有效编号");
        return;
      }
      createHotspotFromDraft(number);
    });
    cancelHotspotNumber.addEventListener("click", () => {
      closeHotspotNumberModal();
      renderSlots();
      setStatus("已取消新增图片位");
    });
    hotspotNumberModal.addEventListener("click", (event) => {
      if (event.target === hotspotNumberModal) {
        closeHotspotNumberModal();
        renderSlots();
        setStatus("已取消新增图片位");
      }
    });
  }
  $("overlay").addEventListener("pointerdown", (event) => {
    if (startHotspotEditDrag(event)) {
      event.preventDefault();
    }
  });
  window.addEventListener("pointermove", updateHotspotEditDrag);
  window.addEventListener("pointerup", stopHotspotEditDrag);
  $("overlay").addEventListener("click", (event) => {
    if (state.justDraggedHotspot) {
      state.justDraggedHotspot = false;
      return;
    }
    handleCanvasHit(event, "select");
  });
  $("overlay").addEventListener("dblclick", (event) => handleCanvasHit(event, "choose"));
  document.addEventListener("click", (event) => {
    if (!$("canvas").contains(event.target)) closeHitMenu();
  });
  window.addEventListener("keydown", (event) => {
    if ((event.key === "Delete" || event.key === "Backspace") && state.activeSlot) {
      event.preventDefault();
      clearActiveSlot();
    }
  });
  window.addEventListener("resize", fitView);
}

bindEvents();
loadMeta().catch((error) => {
  console.error(error);
  setStatus(error.message);
});


