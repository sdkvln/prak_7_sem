const val = (id) => document.getElementById(id).value;
const num = (id) => Number(val(id));

// Запрос к Web Master через прокси; ответ или ошибка выводятся в блок outId
async function api(method, path, body, outId) {
  const out = document.getElementById(outId);
  out.className = "";
  out.textContent = "Выполняется…";
  const resp = await fetch("/api/" + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json();
  if (!resp.ok) {
    out.className = "error";
    out.textContent = "Ошибка: " + (data.detail || data.error);
    return null;
  }
  return data;
}

function show(outId, text) {
  document.getElementById(outId).textContent = text;
}

async function collect() {
  const r = await api("POST", "scenarios/collect",
    { batch_size: num("c_size"), batches: num("c_batches") }, "collect_out");
  if (r) show("collect_out", `Загружено строк: ${r.loaded}\nОсталось в источнике: ${r.remaining}\nВсего в хранилище: ${r.total_in_storage}`);
}

async function clearData() {
  const r = await api("DELETE", "data", null, "collect_out");
  if (r) show("collect_out", `Удалено строк: ${r.deleted}`);
}

async function train() {
  const r = await api("POST", "scenarios/train",
    { model_name: val("t_name"), model_type: val("t_type") }, "train_out");
  if (!r) return;
  show("train_out", `Модель ${r.name} обучена на ${r.rows_train} строках\n` +
    `MAPE: ${(r.metrics.mape * 100).toFixed(1)}%   R²: ${r.metrics.r2}`);
  loadModels();
}

async function predict() {
  const apartment = {};
  for (const f of ["region", "area", "rooms", "kitchen_area", "level", "levels", "building_type", "object_type"]) {
    apartment[f] = num(f);
  }
  const r = await api("POST", "scenarios/predict", { model_name: val("p_model"), apartment }, "predict_out");
  if (r) show("predict_out", `Оценка: ${r.price.toLocaleString("ru")} ₽ (${r.price_per_m2.toLocaleString("ru")} ₽/м²)`);
}

async function showReport() {
  const r = await api("GET", "scenarios/report?model_name=" + encodeURIComponent(val("r_model")), null, "report_out");
  if (!r) return;
  const imp = Object.entries(r.feature_importance || {}).map(([k, v]) => `  ${k}: ${v.toFixed(3)}`).join("\n");
  show("report_out", `Модель: ${r.name} (${r.model_type}), статус: ${r.status}\n` +
    (r.metrics ? `MAE: ${r.metrics.mae.toLocaleString("ru")} ₽   MAPE: ${(r.metrics.mape * 100).toFixed(1)}%   R²: ${r.metrics.r2}\n` : "") +
    (imp ? `Значимость признаков:\n${imp}` : ""));
}

async function loadModels() {
  const resp = await fetch("/api/models");
  if (!resp.ok) return;
  const models = await resp.json();
  for (const sel of document.querySelectorAll(".models")) {
    sel.innerHTML = models.map((m) => `<option>${m.name}</option>`).join("");
  }
}

async function init() {
  const status = await fetch("/api/status").then((r) => r.json()).catch(() => ({}));
  document.getElementById("status").textContent =
    Object.entries(status).map(([k, ok]) => `${k} ${ok ? "✅" : "❌"}`).join("  ") || "Web Master недоступен";
  const types = await fetch("/api/model-types").then((r) => r.json()).catch(() => []);
  document.getElementById("t_type").innerHTML = types.map((t) => `<option>${t}</option>`).join("");
  document.getElementById("t_type").value = "random_forest";
  loadModels();
}

init();
