const state = {
  template: null,
  templates: [],
  activeTemplateId: null,
  slots: [],
  assets: [],
  activeAsset: null,
  activeSlot: null,
  assignments: {},
  imageTransforms: {},
  pendingSlotFileTarget: null,
  pendingFolderMode: "number",
  soloSlot: false,
  editHotspots: false,
  dragState: null,
  createHotspotMode: false,
  pendingHotspotDraft: null,
  justDraggedHotspot: false,
  lastHitSlotIds: [],
  stateSaveTimer: null,
  stateSaveInFlight: null,
  stateRevision: 0,
  modelSettings: null,
  zoom: 1
};

const $ = (id) => document.getElementById(id);
const UPLOAD_CONCURRENCY = 3;
const IMAGE_SCALE_MIN = 0.2;
const IMAGE_SCALE_MAX = 5;

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
  const appendTemplateBtn = $("appendTemplateBtn");
  const hasAssignments = Object.keys(state.assignments).length > 0;
  if (clearHotspotsBtn) clearHotspotsBtn.disabled = !hasSlots;
  if (clearImagesBtn) clearImagesBtn.disabled = !hasAssignments;
  if (deleteHotspotBtn) deleteHotspotBtn.disabled = !hasActiveSlot;
  if (saveSlotsBtn) saveSlotsBtn.disabled = !hasSlots;
  if (saveSlotsPanelBtn) saveSlotsPanelBtn.disabled = !hasSlots;
  if (toggleSoloBtn) toggleSoloBtn.disabled = !hasActiveSlot;
  if (appendTemplateBtn) appendTemplateBtn.disabled = !state.activeTemplateId;
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

function closeModelSettingsModal() {
  const modal = $("modelSettingsModal");
  if (modal) modal.hidden = true;
}

function modelSettingsHint(settings) {
  if (!settings) return "";
  if (settings.provider === "ollama") {
    return "当前使用本地 Ollama；模型地址填写 Ollama 服务地址，通常是 http://127.0.0.1:11434。";
  }
  return settings.hasApiKey ? "已保存 API 密钥；密钥框留空会继续使用已保存密钥。" : "尚未保存 API 密钥。";
}

function populateModelSettings(settings) {
  state.modelSettings = settings;
  if ($("modelProviderInput")) $("modelProviderInput").value = settings.provider || "api";
  if ($("modelBaseUrlInput")) $("modelBaseUrlInput").value = settings.baseUrl || "";
  if ($("modelNameInput")) $("modelNameInput").value = settings.model || "";
  if ($("modelTimeoutInput")) $("modelTimeoutInput").value = String(settings.timeout || 240);
  if ($("modelApiKeyInput")) $("modelApiKeyInput").value = "";
  if ($("modelClearKeyInput")) $("modelClearKeyInput").checked = false;
  if ($("modelSettingsHint")) $("modelSettingsHint").textContent = modelSettingsHint(settings);
}

async function loadModelSettings() {
  const data = await requestJson("/api/model-settings");
  populateModelSettings(data.settings || {});
}

async function openModelSettingsModal() {
  const modal = $("modelSettingsModal");
  if (!modal) return;
  modal.hidden = false;
  if ($("modelSettingsHint")) $("modelSettingsHint").textContent = "正在读取模型设置...";
  try {
    await loadModelSettings();
    window.setTimeout(() => $("modelBaseUrlInput")?.focus(), 0);
  } catch (error) {
    console.error(error);
    if ($("modelSettingsHint")) $("modelSettingsHint").textContent = `读取失败：${error.message}`;
  }
}

async function saveModelSettings(event) {
  event.preventDefault();
  const form = $("modelSettingsForm");
  const button = form?.querySelector("button[type='submit']");
  const originalText = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = "保存中...";
  }
  try {
    const payload = {
      provider: $("modelProviderInput")?.value || "api",
      baseUrl: $("modelBaseUrlInput")?.value || "",
      model: $("modelNameInput")?.value || "",
      apiKey: $("modelApiKeyInput")?.value || "",
      timeout: Number.parseInt($("modelTimeoutInput")?.value || "240", 10),
      clearApiKey: Boolean($("modelClearKeyInput")?.checked),
    };
    const data = await requestJson("/api/model-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    populateModelSettings(data.settings || {});
    closeModelSettingsModal();
    setStatus("模型设置已保存");
  } catch (error) {
    console.error(error);
    if ($("modelSettingsHint")) $("modelSettingsHint").textContent = `保存失败：${error.message}`;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function assignedAssetId(value) {
  if (!value) return null;
  if (typeof value === "object") return value.assetId || value.id || null;
  return value;
}

function currentSlotIdSet() {
  return new Set(state.slots.map((slot) => slot.id));
}

function pruneAssignmentsToCurrentSlots() {
  const valid = currentSlotIdSet();
  Object.keys(state.assignments).forEach((slotId) => {
    if (!valid.has(slotId)) {
      delete state.assignments[slotId];
      delete state.imageTransforms[slotId];
    }
  });
}

function clearCurrentSlotAssignments() {
  currentSlotIdSet().forEach((slotId) => {
    delete state.assignments[slotId];
    delete state.imageTransforms[slotId];
  });
}

function markTemplateStateChanged() {
  state.stateRevision += 1;
}

function normalizeAsset(asset) {
  if (!asset || !asset.id) return null;
  const id = String(asset.id);
  const stem = id.replace(/\.[^.]+$/, "");
  return {
    id,
    url: asset.url || `/api/upload/${id}`,
    thumbUrl: asset.thumbUrl || `/api/thumb/${stem}.jpg`,
    name: asset.name || id,
    width: Number(asset.width) || 0,
    height: Number(asset.height) || 0
  };
}

function applyTemplateWorkState(data) {
  markTemplateStateChanged();
  state.assets = Array.isArray(data.assets)
    ? data.assets.map(normalizeAsset).filter(Boolean)
    : [];
  state.assignments = data.assignments && typeof data.assignments === "object"
    ? { ...data.assignments }
    : {};
  state.imageTransforms = data.transforms && typeof data.transforms === "object"
    ? { ...data.transforms }
    : {};
  pruneAssignmentsToCurrentSlots();
  if (!state.assets.some((asset) => asset.id === state.activeAsset)) {
    state.activeAsset = state.assets[0]?.id || null;
  }
  if (data.fit && $("fitMode")) {
    $("fitMode").value = data.fit === "contain" ? "contain" : "cover";
  }
}

function templateStatePayload() {
  return {
    assets: state.assets.map(normalizeAsset).filter(Boolean),
    assignments: state.assignments,
    transforms: state.imageTransforms,
    fit: $("fitMode")?.value || "cover"
  };
}

async function saveTemplateStateNow(options = {}) {
  if (state.stateSaveTimer) {
    window.clearTimeout(state.stateSaveTimer);
    state.stateSaveTimer = null;
  }
  if (!state.activeTemplateId || !state.template) return null;
  if (state.stateSaveInFlight) {
    try {
      await state.stateSaveInFlight;
    } catch {
      // The next write carries the latest local state.
    }
  }
  const saveRevision = state.stateRevision;
  const saveTemplateId = state.activeTemplateId;
  const payload = templateStatePayload();
  const savePromise = requestJson("/api/template-state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  state.stateSaveInFlight = savePromise;
  try {
    const data = await savePromise;
    const isCurrentSave = (
      state.activeTemplateId === saveTemplateId &&
      state.stateRevision === saveRevision
    );
    if (isCurrentSave) {
      if (Array.isArray(data.assets)) {
        state.assets = data.assets.map(normalizeAsset).filter(Boolean);
      }
      if (data.assignments && typeof data.assignments === "object") {
        state.assignments = { ...data.assignments };
      }
      if (data.transforms && typeof data.transforms === "object") {
        state.imageTransforms = { ...data.transforms };
      }
    }
    return data;
  } catch (error) {
    console.error(error);
    if (!options.silent) {
      setStatus(`保存模板填充状态失败：${error.message}`);
    }
    return null;
  } finally {
    if (state.stateSaveInFlight === savePromise) {
      state.stateSaveInFlight = null;
    }
  }
}

function scheduleTemplateStateSave(delay = 500) {
  if (!state.activeTemplateId || !state.template) return;
  markTemplateStateChanged();
  if (state.stateSaveTimer) {
    window.clearTimeout(state.stateSaveTimer);
  }
  state.stateSaveTimer = window.setTimeout(() => {
    saveTemplateStateNow({ silent: true });
  }, delay);
}

function defaultImageTransform() {
  return { x: 0, y: 0, scale: 1 };
}

function ensureImageTransform(slotId) {
  const current = state.imageTransforms[slotId] || {};
  const normalized = {
    x: Number.isFinite(Number(current.x)) ? Number(current.x) : 0,
    y: Number.isFinite(Number(current.y)) ? Number(current.y) : 0,
    scale: Number.isFinite(Number(current.scale)) ? Number(current.scale) : 1
  };
  normalized.scale = Math.max(IMAGE_SCALE_MIN, Math.min(IMAGE_SCALE_MAX, normalized.scale));
  state.imageTransforms[slotId] = normalized;
  return normalized;
}

function clearImageTransform(slotId) {
  delete state.imageTransforms[slotId];
}

function resetImageTransform(slotId) {
  state.imageTransforms[slotId] = defaultImageTransform();
  applyPlacedTransform(slotId);
  scheduleTemplateStateSave();
  setStatus("图片裁切已复位");
}

function currentFitMode() {
  return $("fitMode")?.value === "contain" ? "contain" : "cover";
}

function templateScaleX() {
  return Number(state.template?.scaleX) || Number(state.template?.scale) || 1;
}

function templateScaleY() {
  return Number(state.template?.scaleY) || Number(state.template?.scale) || 1;
}

function layoutPlacedImage(slotId, img) {
  const slot = slotById(slotId);
  const asset = assetById(assignedAssetId(state.assignments[slotId]));
  if (!slot || !asset || !img) return false;
  const sourceWidth = Number(asset.width) || img.naturalWidth || 0;
  const sourceHeight = Number(asset.height) || img.naturalHeight || 0;
  if (!sourceWidth || !sourceHeight || !slot.w || !slot.h) return false;

  const scaleX = templateScaleX();
  const scaleY = templateScaleY();
  const fitScale = currentFitMode() === "contain"
    ? Math.min(slot.w / sourceWidth, slot.h / sourceHeight)
    : Math.max(slot.w / sourceWidth, slot.h / sourceHeight);
  const baseWidth = sourceWidth * fitScale * scaleX;
  const baseHeight = sourceHeight * fitScale * scaleY;
  const slotWidth = slot.w * scaleX;
  const slotHeight = slot.h * scaleY;

  img.style.width = `${baseWidth}px`;
  img.style.height = `${baseHeight}px`;
  img.style.left = `${(slotWidth - baseWidth) / 2}px`;
  img.style.top = `${(slotHeight - baseHeight) / 2}px`;
  img.style.objectFit = "fill";
  return true;
}

function applyPlacedTransform(slotId) {
  const transform = ensureImageTransform(slotId);
  const scaleX = templateScaleX();
  const scaleY = templateScaleY();
  const img = document.querySelector(`.placed[data-slot-id="${slotId}"]`);
  if (img) {
    layoutPlacedImage(slotId, img);
    img.style.transform = `translate(${transform.x * scaleX}px, ${transform.y * scaleY}px) scale(${transform.scale})`;
    img.style.transformOrigin = "center center";
  }
  const label = document.querySelector(`[data-scale-slot="${slotId}"]`);
  if (label) {
    label.textContent = `${Math.round(transform.scale * 100)}%`;
  }
}

function adjustImageScale(slotId, factor) {
  const transform = ensureImageTransform(slotId);
  transform.scale = Math.max(IMAGE_SCALE_MIN, Math.min(IMAGE_SCALE_MAX, transform.scale * factor));
  applyPlacedTransform(slotId);
  scheduleTemplateStateSave();
  setStatus(`图片缩放 ${Math.round(transform.scale * 100)}%。拖动图片可调整位置`);
}

function syncTemplateState(data) {
  if (Array.isArray(data.templates)) {
    state.templates = data.templates;
  }
  if ("activeTemplateId" in data) {
    state.activeTemplateId = data.activeTemplateId || null;
  }
  renderTemplates();
}

function activeTemplateName() {
  const active = state.templates.find((template) => template.id === state.activeTemplateId);
  return active?.name || "";
}

function renderTemplates() {
  const list = $("templateList");
  if (!list) return;
  list.innerHTML = "";

  if (!state.templates.length) {
    const empty = document.createElement("div");
    empty.className = "template-empty";
    empty.textContent = "还没有保存的模板";
    list.appendChild(empty);
    return;
  }

  state.templates.forEach((template) => {
    const item = document.createElement("div");
    item.className = `template-item ${template.id === state.activeTemplateId ? "active" : ""}`;

    const main = document.createElement("button");
    main.className = "template-main";
    main.type = "button";
    main.title = template.path || template.originalName || template.name;
    main.innerHTML = `
      <span class="template-name"></span>
      <span class="template-meta">${template.slotCount || 0} 个图片位 · ${template.sizeMB || 0} MB</span>
    `;
    main.querySelector(".template-name").textContent = template.name || "未命名模板";
    main.addEventListener("click", () => activateTemplate(template.id));

    const actions = document.createElement("div");
    actions.className = "template-actions";

    const useButton = document.createElement("button");
    useButton.type = "button";
    useButton.textContent = template.id === state.activeTemplateId ? "当前" : "使用";
    useButton.disabled = template.id === state.activeTemplateId;
    useButton.addEventListener("click", () => activateTemplate(template.id));

    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.textContent = "改名";
    renameButton.addEventListener("click", () => renameTemplate(template.id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.textContent = "删";
    deleteButton.className = "template-delete";
    deleteButton.addEventListener("click", () => deleteTemplate(template.id));

    actions.append(useButton, renameButton, deleteButton);
    item.append(main, actions);
    list.appendChild(item);
  });
}

function applyMetaData(data, options = {}) {
  syncTemplateState(data);
  if (data.empty) {
    state.template = data.template;
    state.slots = [];
    applyTemplateWorkState(data);
    state.activeSlot = null;
    $("templateImg").removeAttribute("src");
    $("topOverlayImg").removeAttribute("src");
    $("canvas").classList.add("empty");
    $("canvas").style.width = `${data.template.previewWidth}px`;
    $("canvas").style.height = `${data.template.previewHeight}px`;
    renderAssets();
    renderSlots();
    fitView();
    if (options.status !== false) {
      setStatus("空白画布。请选择已有模板或导入 PSD/PSB 模板");
    }
    return;
  }

  state.template = data.template;
  state.slots = data.slots || [];
  applyTemplateWorkState(data);
  state.activeSlot = null;
  $("templateImg").src = `${data.template.previewImage}&t=${Date.now()}`;
  $("topOverlayImg").src = `${data.template.topOverlayPreviewImage || data.template.topOverlayImage}&t=${Date.now()}`;
  $("canvas").classList.remove("empty");
  $("canvas").style.width = `${data.template.previewWidth}px`;
  $("canvas").style.height = `${data.template.previewHeight}px`;
  renderAssets();
  renderSlots();
  fitView();
  if (options.status !== false) {
    const name = activeTemplateName();
    setStatus(`${name ? `${name} · ` : ""}${data.template.width} x ${data.template.height}，${state.slots.length} 个图片位`);
  }
}

async function activateTemplate(templateId) {
  if (!templateId || templateId === state.activeTemplateId) return;
  setStatus("正在切换模板");
  try {
    await saveTemplateStateNow({ silent: true });
    const data = await requestJson(`/api/templates/${templateId}/activate`, { method: "POST" });
    state.soloSlot = false;
    state.editHotspots = false;
    state.createHotspotMode = false;
    $("toggleSoloSlot").classList.remove("active");
    $("toggleSoloSlot").textContent = "只显示选中";
    $("toggleEditHotspots").classList.remove("active");
    $("addHotspot").classList.remove("active");
    applyMetaData(data);
  } catch (error) {
    console.error(error);
    setStatus(`切换模板失败：${error.message}`);
    alert(`切换模板失败：${error.message}`);
  }
}

async function renameTemplate(templateId) {
  const template = state.templates.find((item) => item.id === templateId);
  if (!template) return;
  const name = window.prompt("请输入模板名称", template.name || "");
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) {
    setStatus("模板名称不能为空");
    return;
  }
  try {
    const data = await requestJson(`/api/templates/${templateId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: trimmed })
    });
    syncTemplateState(data);
    setStatus("模板已重命名");
  } catch (error) {
    console.error(error);
    setStatus(`重命名失败：${error.message}`);
    alert(`重命名失败：${error.message}`);
  }
}

async function deleteTemplate(templateId) {
  const template = state.templates.find((item) => item.id === templateId);
  if (!template) return;
  if (!window.confirm(`确定删除模板“${template.name}”？导入副本和它的图片位配置都会移除。`)) return;
  try {
    await requestJson(`/api/templates/${templateId}`, { method: "DELETE" });
    await loadMeta();
    setStatus("模板已删除");
  } catch (error) {
    console.error(error);
    setStatus(`删除模板失败：${error.message}`);
    alert(`删除模板失败：${error.message}`);
  }
}

async function loadMeta() {
  setStatus("正在读取项目");
  const data = await requestJson("/api/meta");
  applyMetaData(data);
}


async function newTemplate() {
  await saveTemplateStateNow({ silent: true });
  const data = await requestJson("/api/new-template", { method: "POST" });
  applyMetaData({
    ...data,
    empty: true,
    template: { width: 2400, height: 1800, previewWidth: 1200, previewHeight: 900, scale: 0.5 },
    slots: []
  });
  setStatus("已新建空白模板，请导入 PSD/PSB");
}


async function uploadTemplate(file) {
  if (!file) return;
  await saveTemplateStateNow({ silent: true });
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
    applyMetaData(data, { status: false });
    setStatus("模板已导入并保存到模板库。现在可编辑图片位或切换其他模板。");
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


async function appendTemplate(file) {
  if (!file) return;
  if (!state.activeTemplateId) {
    setStatus("请先导入一个主模板，再追加 PSD/PSB");
    return;
  }
  await saveTemplateStateNow({ silent: true });
  const button = $("appendTemplateBtn");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "追加中...";
  showTemplateLoading("正在把第二个 PSD/PSB 拼接到当前模板末尾，请保持页面打开。");
  setStatus("正在追加模板并生成组合画布");
  try {
    const body = new FormData();
    body.append("file", file);
    window.setTimeout(() => {
      showTemplateLoading("正在全尺寸渲染并上下拼接，较大的 PSB 可能需要 1-2 分钟。");
    }, 1200);
    const data = await requestJson("/api/template/append", { method: "POST", body });
    applyMetaData(data, { status: false });
    setStatus(`已追加 ${file.name}，当前画布 ${data.template.width} x ${data.template.height}`);
  } catch (error) {
    console.error(error);
    setStatus(`追加模板失败：${error.message}`);
    alert(`追加模板失败：${error.message}`);
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
    state.imageTransforms = {};
    renderSlots();
    scheduleTemplateStateSave();
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
  Object.entries(state.assignments).forEach(([slotId, assignedValue]) => {
    if (assignedAssetId(assignedValue) === assetId) {
      delete state.assignments[slotId];
      clearImageTransform(slotId);
    }
  });
  renderAssets();
  renderSlots();
  scheduleTemplateStateSave();
  setStatus("素材已删除");
}

function clearSlot(slotId) {
  delete state.assignments[slotId];
  clearImageTransform(slotId);
  state.activeSlot = slotId;
  renderSlots();
  scheduleTemplateStateSave();
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
  if ($("hotspotShapeInput")) {
    $("hotspotShapeInput").value = "rect";
  }
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
  const shape = $("hotspotShapeInput")?.value === "circle" ? "circle" : "rect";
  let x = draft.x;
  let y = draft.y;
  let w = draft.w;
  let h = draft.h;
  if (shape === "circle") {
    const diameter = Math.max(20, Math.min(w, h));
    x = Math.round(x + (w - diameter) / 2);
    y = Math.round(y + (h - diameter) / 2);
    w = diameter;
    h = diameter;
  }
  const id = `manual_${Date.now()}`;
  const slot = {
    id,
    name: `自定义图片位 ${normalizedNumber}`,
    x,
    y,
    w,
    h,
    source: "manual",
    layer_key: "",
    slot_type: "image",
    shape,
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
  if (!grid) return;
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
  const scaleX = templateScaleX();
  const scaleY = templateScaleY();

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
    const slotShape = slot.shape === "circle" ? "circle" : "rect";
    slot.shape = slotShape;
    const item = document.createElement("div");
    item.className = `slot-item ${slot.id === state.activeSlot ? "active" : ""}`;
    item.innerHTML = `
      <button class="slot-main" type="button">
        <div class="slot-name">${index + 1}. ${slot.name}</div>
        <div class="slot-meta">${slot.x}, ${slot.y}, ${slot.w} x ${slot.h} · ${slotShape === "circle" ? "圆形" : "矩形"}${assigned ? " · 已放入" : ""}</div>
        <select class="slot-type">
          <option value="image" selected>图片位</option>
        </select>
        <select class="slot-shape">
          <option value="rect" ${slotShape === "rect" ? "selected" : ""}>矩形</option>
          <option value="circle" ${slotShape === "circle" ? "selected" : ""}>圆形</option>
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
    item.querySelector(".slot-shape").addEventListener("click", (event) => event.stopPropagation());
    item.querySelector(".slot-shape").addEventListener("change", (event) => {
      slot.shape = event.target.value === "circle" ? "circle" : "rect";
      state.activeSlot = slot.id;
      renderSlots();
      scheduleTemplateStateSave(100);
      setStatus("图片位形状已修改，导出时会按该形状裁剪");
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
    if (assigned) {
      const currentTransform = ensureImageTransform(slot.id);
      const imageActions = document.createElement("div");
      imageActions.className = "image-actions";
      imageActions.innerHTML = `
        <button type="button" data-action="zoomOut" title="缩小图片">-</button>
        <span class="image-scale" data-scale-slot="${slot.id}">${Math.round(currentTransform.scale * 100)}%</span>
        <button type="button" data-action="zoomIn" title="放大图片">+</button>
        <button type="button" data-action="reset" title="复位图片裁切">复位</button>
      `;
      imageActions.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          state.activeSlot = slot.id;
          if (button.dataset.action === "zoomOut") {
            adjustImageScale(slot.id, 1 / 1.08);
          } else if (button.dataset.action === "zoomIn") {
            adjustImageScale(slot.id, 1.08);
          } else {
            resetImageTransform(slot.id);
          }
          renderSlots();
        });
      });
      item.appendChild(imageActions);
    }
    list.appendChild(item);

    const box = document.createElement("div");
    box.className = `slot-box shape-${slotShape} ${slot.id === state.activeSlot ? "active" : ""} ${assigned ? "assigned" : ""}`;
    box.dataset.slotId = slot.id;
    applySlotBoxRect(box, slot);
    box.style.zIndex = String(state.slots.length - index);
    box.innerHTML = `<button class="label" type="button" title="选中图片位 ${index + 1}">${index + 1}</button>`;
    if (state.editHotspots && slot.id === state.activeSlot) {
      const handle = document.createElement("div");
      handle.className = "resize-handle";
      box.appendChild(handle);
    }
    if (assigned) {
      const asset = assetById(assignedAssetId(assigned));
      if (asset) {
        const transform = ensureImageTransform(slot.id);
        const img = document.createElement("img");
        img.className = "placed";
        img.dataset.slotId = slot.id;
        img.src = asset.thumbUrl || asset.url;
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.style.transform = `translate(${transform.x * scaleX}px, ${transform.y * scaleY}px) scale(${transform.scale})`;
        img.style.transformOrigin = "center center";
        img.addEventListener("load", () => applyPlacedTransform(slot.id), { once: true });
        box.appendChild(img);
        applyPlacedTransform(slot.id);

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
    const draft = state.dragState.draft;
    const box = document.createElement("div");
    box.className = "slot-box draft-hotspot";
    applySlotBoxRect(box, draft);
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

function isSlotResizeHit(slot, point) {
  const tolerance = 35;
  const nearCorner = (
    Math.abs(point.x - (slot.x + slot.w)) <= tolerance &&
    Math.abs(point.y - (slot.y + slot.h)) <= tolerance
  );
  if (nearCorner) return true;
  if (slot.shape !== "circle") return false;
  const handleX = slot.x + slot.w * 0.86;
  const handleY = slot.y + slot.h * 0.86;
  return (
    point.x >= slot.x + slot.w * 0.5 &&
    point.y >= slot.y + slot.h * 0.5 &&
    Math.abs(point.x - handleX) <= tolerance &&
    Math.abs(point.y - handleY) <= tolerance
  );
}

function applySlotBoxRect(box, rect) {
  const scaleX = templateScaleX();
  const scaleY = templateScaleY();
  box.style.left = `${rect.x * scaleX}px`;
  box.style.top = `${rect.y * scaleY}px`;
  box.style.width = `${rect.w * scaleX}px`;
  box.style.height = `${rect.h * scaleY}px`;
}

function slotBoxElement(slotId) {
  return Array.from($("overlay").querySelectorAll(".slot-box[data-slot-id]"))
    .find((box) => box.dataset.slotId === slotId);
}

function updateSlotBoxRect(slot) {
  const box = slotBoxElement(slot.id);
  if (!box) return false;
  applySlotBoxRect(box, slot);
  if (assignedAssetId(state.assignments[slot.id])) {
    applyPlacedTransform(slot.id);
  }
  return true;
}

function updateDraftHotspotBox(draft) {
  const overlay = $("overlay");
  let box = overlay.querySelector(".draft-hotspot");
  if (!box) {
    box = document.createElement("div");
    box.className = "slot-box draft-hotspot";
    overlay.appendChild(box);
  }
  applySlotBoxRect(box, draft);
}

function canvasPoint(event) {
  const rect = $("canvas").getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) / (templateScaleX() * state.zoom),
    y: (event.clientY - rect.top) / (templateScaleY() * state.zoom)
  };
}

function startImageAdjustDrag(event) {
  if (state.editHotspots || state.createHotspotMode) return false;
  const matches = hitSlotsAt(event.clientX, event.clientY)
    .filter(({ slot }) => assignedAssetId(state.assignments[slot.id]));
  if (!matches.length) return false;
  const activeMatch = matches.find(({ slot }) => slot.id === state.activeSlot);
  const slot = (activeMatch || matches[0]).slot;
  const point = canvasPoint(event);
  const transform = ensureImageTransform(slot.id);
  markTemplateStateChanged();
  state.activeSlot = slot.id;
  state.dragState = {
    mode: "image-pan",
    slotId: slot.id,
    startX: point.x,
    startY: point.y,
    original: { x: transform.x, y: transform.y }
  };
  closeHitMenu();
  renderSlots();
  setStatus("拖动图片调整位置，滚轮或 +/- 调整缩放");
  return true;
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
  state.dragState = {
    mode: isSlotResizeHit(slot, point) ? "resize" : "move",
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
  if (state.dragState.mode === "image-pan") {
    const point = canvasPoint(event);
    const dx = Math.round(point.x - state.dragState.startX);
    const dy = Math.round(point.y - state.dragState.startY);
    const transform = ensureImageTransform(state.dragState.slotId);
    transform.x = state.dragState.original.x + dx;
    transform.y = state.dragState.original.y + dy;
    state.justDraggedHotspot = true;
    applyPlacedTransform(state.dragState.slotId);
    setStatus(`图片位置：${transform.x}, ${transform.y}。滚轮或 +/- 可缩放`);
    return;
  }
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
    updateDraftHotspotBox(state.dragState.draft);
    setStatus(`新图片位：${x1}, ${y1}, ${x2 - x1} x ${y2 - y1}`);
    return;
  }
  const slot = slotById(state.dragState.slotId);
  if (!slot) return;
  const point = canvasPoint(event);
  const dx = Math.round(point.x - state.dragState.startX);
  const dy = Math.round(point.y - state.dragState.startY);
  if (state.dragState.mode === "resize") {
    if (slot.shape === "circle") {
      const delta = Math.abs(dx) >= Math.abs(dy) ? dx : dy;
      const baseSize = Math.max(state.dragState.original.w, state.dragState.original.h);
      const size = Math.max(20, baseSize + delta);
      slot.w = size;
      slot.h = size;
    } else {
      slot.w = Math.max(20, state.dragState.original.w + dx);
      slot.h = Math.max(20, state.dragState.original.h + dy);
    }
  } else {
    slot.x = state.dragState.original.x + dx;
    slot.y = state.dragState.original.y + dy;
  }
  state.justDraggedHotspot = true;
  if (!updateSlotBoxRect(slot)) {
    renderSlots();
  }
  setStatus(`图片位：${slot.x}, ${slot.y}, ${slot.w} x ${slot.h}`);
}

function stopHotspotEditDrag() {
  if (!state.dragState) return;
  if (state.dragState.mode === "image-pan") {
    state.dragState = null;
    scheduleTemplateStateSave(100);
    setStatus("图片位置已调整，导出会按当前裁切生成");
    return;
  }
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

function handleImageWheel(event) {
  if (state.editHotspots || state.createHotspotMode) return;
  const matches = hitSlotsAt(event.clientX, event.clientY)
    .filter(({ slot }) => assignedAssetId(state.assignments[slot.id]));
  if (!matches.length) return;
  event.preventDefault();
  const slot = matches[0].slot;
  const previousActiveSlot = state.activeSlot;
  state.activeSlot = slot.id;
  adjustImageScale(slot.id, event.deltaY < 0 ? 1.08 : 1 / 1.08);
  if (previousActiveSlot !== slot.id) {
    renderSlots();
  }
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
  clearImageTransform(slotId);
  if (state.activeSlot === slotId) {
    state.activeSlot = state.slots[0]?.id || null;
  }
  renderSlots();
  scheduleTemplateStateSave();
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
  state.imageTransforms = {};
  renderSlots();
  scheduleTemplateStateSave();
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
  state.imageTransforms = {};
  state.activeSlot = null;
  state.pendingSlotFileTarget = null;
  state.soloSlot = false;
  state.editHotspots = false;
  state.createHotspotMode = false;
  markTemplateStateChanged();
  closeHitMenu();
  $("toggleSoloSlot").classList.remove("active");
  $("toggleSoloSlot").textContent = "只显示选中";
  $("toggleEditHotspots").classList.remove("active");
  $("addHotspot").classList.remove("active");
  renderSlots();
  setStatus("正在清空图片位");
  try {
    await requestJson("/api/slots/clear", { method: "POST" });
    await saveTemplateStateNow({ silent: true });
    setStatus("图片位已清空");
  } catch (error) {
    console.error(error);
    setStatus(`清空图片位失败：${error.message}`);
    alert(`清空图片位失败：${error.message}`);
  }
}

function hitSlotsAt(clientX, clientY) {
  const canvasRect = $("canvas").getBoundingClientRect();
  const x = (clientX - canvasRect.left) / (templateScaleX() * state.zoom);
  const y = (clientY - canvasRect.top) / (templateScaleY() * state.zoom);
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
    name: data.name || file.name,
    width: Number(data.width) || 0,
    height: Number(data.height) || 0
  });
  state.activeAsset = data.id;
  markTemplateStateChanged();
  renderAssets();
  return data.id;
}

async function uploadForSlot(file, slotId) {
  setStatus("正在上传并放入图片位");
  const assetId = await uploadOne(file, 0, 1);
  state.assignments[slotId] = assetId;
  state.imageTransforms[slotId] = defaultImageTransform();
  markTemplateStateChanged();
  state.activeSlot = slotId;
  renderAssets();
  renderSlots();
  scheduleTemplateStateSave(100);
  setStatus("已放入图片位");
}

async function uploadFilesToAssetLibrary(fileList) {
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
  scheduleTemplateStateSave(100);
}

function uploadTargetSlots(count) {
  const targets = [];
  const active = state.activeSlot ? slotById(state.activeSlot) : null;
  if (active) {
    targets.push(active);
  }
  state.slots.forEach((slot) => {
    if (targets.some((target) => target.id === slot.id)) return;
    if (!assignedAssetId(state.assignments[slot.id])) {
      targets.push(slot);
    }
  });
  return targets.slice(0, count);
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
  if (!files.length) {
    setStatus("没有找到可上传的图片");
    return;
  }
  if (!state.slots.length) {
    setStatus("请先新建或识别图片位，再上传图片");
    return;
  }
  const targetSlots = uploadTargetSlots(files.length);
  if (!targetSlots.length) {
    setStatus("没有可填充的图片位：请选择一个图片位，或先清空/新增图片位");
    return;
  }
  const filesToUpload = files.slice(0, targetSlots.length);
  const assetIds = new Array(filesToUpload.length);
  let next = 0;
  async function worker() {
    while (next < filesToUpload.length) {
      const index = next;
      next += 1;
      assetIds[index] = await uploadOne(filesToUpload[index], index, filesToUpload.length);
    }
  }
  const workers = Array.from(
    { length: Math.min(UPLOAD_CONCURRENCY, filesToUpload.length) },
    () => worker()
  );
  try {
    await Promise.all(workers);
  } catch (error) {
    setStatus(error.message);
    throw error;
  }
  assetIds.forEach((assetId, index) => {
    const slot = targetSlots[index];
    if (!assetId || !slot) return;
    state.assignments[slot.id] = assetId;
    state.imageTransforms[slot.id] = defaultImageTransform();
  });
  if (assetIds.length) {
    state.activeSlot = targetSlots[assetIds.length - 1]?.id || state.activeSlot;
    markTemplateStateChanged();
  }
  renderSlots();
  scheduleTemplateStateSave(100);
  const skipped = files.length - filesToUpload.length;
  setStatus(`已上传并放入画布 ${assetIds.filter(Boolean).length} 张${skipped ? `，${skipped} 张没有空图片位已跳过` : ""}`);
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
      state.imageTransforms[slot.id] = defaultImageTransform();
      markTemplateStateChanged();
      matched += 1;
    } else {
      skipped += 1;
    }
  }

  renderAssets();
  renderSlots();
  scheduleTemplateStateSave(100);
  setStatus(`目录匹配完成：${matched}/${files.length} 张已放入图片位${skipped ? `，${skipped} 张没有对应图片位` : ""}`);
}

async function uploadFolderAndStyleMatch(fileList) {
  if (!state.slots.length) {
    setStatus("当前模板还没有图片位，先识别或新增图片位");
    return;
  }
  const files = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
  if (!files.length) {
    setStatus("目录里没有找到图片素材");
    return;
  }

  const assetIds = [];
  try {
    for (let i = 0; i < files.length; i += 1) {
      setStatus(`正在读取素材 ${i + 1}/${files.length}，稍后按视觉风格匹配`);
      const assetId = await uploadOne(files[i], i, files.length);
      assetIds.push(assetId);
    }

    setStatus("正在调用远端 API 读取素材内容，并按参考图文字意图匹配");
    const uploadedAssets = state.assets
      .filter((asset) => assetIds.includes(asset.id))
      .map((asset) => ({
        id: asset.id,
        name: asset.name,
        width: asset.width,
        height: asset.height
      }));
    const data = await requestJson("/api/auto-match-style", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slots: state.slots,
        assets: uploadedAssets,
        assetIds,
        assignments: state.assignments
      })
    });

    const matches = Array.isArray(data.matches) ? data.matches : [];
    clearCurrentSlotAssignments();
    matches.forEach((match) => {
      if (!match.slotId || !match.assetId) return;
      state.assignments[match.slotId] = match.assetId;
      state.imageTransforms[match.slotId] = defaultImageTransform();
    });

    renderAssets();
    renderSlots();
    scheduleTemplateStateSave(100);
    if (!matches.length) {
      setStatus("视觉匹配没有找到可用结果");
      return;
    }
    const scores = matches.map((match) => Number(match.score)).filter(Number.isFinite);
    const minScore = scores.length ? Math.min(...scores) : 0;
    const maxScore = scores.length ? Math.max(...scores) : 0;
    const learned = Number(data.learnedMatched) || 0;
    let sourceText = "";
    if (data.engine === "vision-api") {
      sourceText = `，视觉 API${data.model ? ` ${data.model}` : ""}`;
    } else if (data.engine === "qwen-vl") {
      sourceText = `，Qwen-VL${data.model ? ` ${data.model}` : ""}`;
    } else if (data.qwenError) {
      sourceText = `，Qwen-VL 失败已回退：${data.qwenError}`;
    } else {
      sourceText = learned ? `，${learned} 个使用成片学习` : "，使用本地特征兜底";
    }
    setStatus(`视觉风格匹配完成：${matches.length}/${state.slots.length} 个图片位，匹配分 ${minScore}-${maxScore}${sourceText}`);
  } catch (error) {
    console.error(error);
    setStatus(`视觉风格匹配失败：${error.message}`);
    alert(`视觉风格匹配失败：${error.message}`);
  }
}

async function uploadStyleExamples(fileList) {
  if (!state.slots.length) {
    setStatus("当前模板还没有图片位，先识别或新增图片位");
    return;
  }
  const files = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
  if (!files.length) {
    setStatus("目录里没有找到成片图片");
    return;
  }
  const button = $("styleLearnBtn");
  const originalText = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = "学习中...";
  }
  setStatus(`正在学习 ${files.length} 张历史成片`);
  try {
    const body = new FormData();
    files.forEach((file) => body.append("files", file, file.webkitRelativePath || file.name));
    body.append("slots", JSON.stringify(state.slots));
    const data = await requestJson("/api/style-examples", { method: "POST", body });
    const skipped = Array.isArray(data.skipped) ? data.skipped.length : 0;
    setStatus(
      `成片学习完成：接收 ${data.accepted || 0} 张，覆盖 ${data.profiledSlots || 0} 个图片位，累计样本 ${data.exampleCount || 0}${skipped ? `，跳过 ${skipped} 张` : ""}`
    );
    if (!data.accepted && skipped) {
      alert(`没有学到有效样本。\n\n跳过原因：\n${data.skipped.slice(0, 8).join("\n")}`);
    }
  } catch (error) {
    console.error(error);
    setStatus(`成片学习失败：${error.message}`);
    alert(`成片学习失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function clearStyleProfile() {
  if (!window.confirm("确定清空当前模板的风格学习画像？素材和图片位不会删除。")) return;
  const button = $("clearStyleProfileBtn");
  const originalText = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = "清空中...";
  }
  try {
    await requestJson("/api/style-profile/clear", { method: "POST" });
    setStatus("当前模板的风格学习画像已清空，请重新导入标注样本学习");
  } catch (error) {
    console.error(error);
    setStatus(`清空风格学习失败：${error.message}`);
    alert(`清空风格学习失败：${error.message}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
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
    await saveTemplateStateNow({ silent: true });
    const data = await requestJson("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assignments: state.assignments,
        transforms: state.imageTransforms,
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
  const appendTemplateInput = $("appendTemplateInput");
  const folderInput = $("folderInput");
  const styleExampleInput = $("styleExampleInput");
  const slotInput = getSlotFileInput();
  const dropzone = $("dropzone");
  const modelSettingsModal = $("modelSettingsModal");
  const modelSettingsForm = $("modelSettingsForm");

  input.addEventListener("change", () => uploadFiles(input.files));
  $("modelSettingsBtn")?.addEventListener("click", openModelSettingsModal);
  $("cancelModelSettings")?.addEventListener("click", closeModelSettingsModal);
  modelSettingsForm?.addEventListener("submit", saveModelSettings);
  modelSettingsModal?.addEventListener("click", (event) => {
    if (event.target === modelSettingsModal) {
      closeModelSettingsModal();
    }
  });
  $("modelProviderInput")?.addEventListener("change", () => {
    const settings = {
      ...(state.modelSettings || {}),
      provider: $("modelProviderInput").value,
      hasApiKey: state.modelSettings?.hasApiKey,
    };
    if ($("modelSettingsHint")) $("modelSettingsHint").textContent = modelSettingsHint(settings);
  });
  $("newTemplateBtn").addEventListener("click", newTemplate);
  $("templateBtn").addEventListener("click", () => {
    templateInput.value = "";
    templateInput.click();
  });
  templateInput.addEventListener("change", () => uploadTemplate(templateInput.files[0]));
  $("appendTemplateBtn").addEventListener("click", () => {
    appendTemplateInput.value = "";
    appendTemplateInput.click();
  });
  appendTemplateInput.addEventListener("change", () => appendTemplate(appendTemplateInput.files[0]));
  $("detectSlotsBtn").addEventListener("click", detectSlots);
  $("folderMatchBtn").addEventListener("click", () => {
    state.pendingFolderMode = "number";
    folderInput.value = "";
    folderInput.click();
  });
  $("folderStyleMatchBtn").addEventListener("click", () => {
    state.pendingFolderMode = "style";
    folderInput.value = "";
    folderInput.click();
  });
  $("styleLearnBtn").addEventListener("click", () => {
    styleExampleInput.value = "";
    styleExampleInput.click();
  });
  $("clearStyleProfileBtn").addEventListener("click", clearStyleProfile);
  styleExampleInput.addEventListener("change", () => uploadStyleExamples(styleExampleInput.files));
  folderInput.addEventListener("change", () => {
    if (state.pendingFolderMode === "style") {
      uploadFolderAndStyleMatch(folderInput.files);
    } else {
      uploadFolderAndMatch(folderInput.files);
    }
  });
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
  $("fitMode").addEventListener("change", () => {
    renderSlots();
    scheduleTemplateStateSave();
  });

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
    if (startHotspotEditDrag(event) || startImageAdjustDrag(event)) {
      event.preventDefault();
    }
  });
  $("overlay").addEventListener("wheel", handleImageWheel, { passive: false });
  window.addEventListener("pointermove", updateHotspotEditDrag);
  window.addEventListener("pointerup", (event) => {
    const dragMode = state.dragState?.mode;
    stopHotspotEditDrag(event);
    if (dragMode === "move" || dragMode === "resize") {
      renderSlots();
    }
  });
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


