/* Avito Парсер — логика фронтенда */

const $ = (id) => document.getElementById(id);

let pollTimer = null;
let currentResults = null; // текущий массив результатов для пересортировки

/* ================= Города ================= */
async function loadCities() {
  try {
    const resp = await fetch("/api/cities");
    const cities = await resp.json();
    const select = $("city");
    for (const c of cities) {
      const opt = document.createElement("option");
      opt.value = c.slug;
      opt.textContent = c.name;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error("cities load failed", e);
  }
}

function setCity(slug, name) {
  const select = $("city");
  if (slug && [...select.options].some(o => o.value === slug)) {
    select.value = slug;
    return true;
  }
  if (name) setGeoStatus(`Город «${name}» пока не в списке — поиск по выбранному городу`, true);
  return false;
}

/* ================= Геопозиция ================= */
function setGeoStatus(text, isError = false) {
  $("geo-status").textContent = text;
  $("geo-status").style.color = isError ? "var(--danger)" : "var(--muted)";
}

function rememberCoords(lat, lng) {
  const loc = $("user-location");
  loc.dataset.lat = lat;
  loc.dataset.lng = lng;
}

$("geolocate-btn").addEventListener("click", () => {
  if (!navigator.geolocation) {
    setGeoStatus("Браузер не поддерживает геолокацию — введите адрес вручную", true);
    return;
  }
  setGeoStatus("Определяем местоположение…");
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude } = pos.coords;
    rememberCoords(latitude, longitude);
    $("user-location").value = `📍 ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
    // определяем город по координатам и подставляем в селектор
    setGeoStatus("Координаты получены, определяем город…");
    try {
      const r = await fetch(`/api/reverse?lat=${latitude}&lng=${longitude}`);
      if (r.ok) {
        const d = await r.json();
        if (setCity(d.city_slug, d.city)) {
          setGeoStatus(`📍 ${d.city} — координаты и город подставлены`);
        } else {
          setGeoStatus(`📍 координаты получены (${d.city || "город не определён"})`, !d.city);
        }
      } else {
        setGeoStatus("📍 координаты получены, город определить не удалось");
      }
    } catch {
      setGeoStatus("📍 координаты получены, город определить не удалось");
    }
  }, () => setGeoStatus("Не удалось определить — введите город или адрес вручную", true),
  { timeout: 10000 });
});

/* ручной ввод адреса: геокодируем и подставляем город */
let geoDebounce = null;
$("user-location").addEventListener("input", () => {
  const loc = $("user-location");
  delete loc.dataset.lat; // ручной ввод сбрасывает авто-координаты
  const val = loc.value.trim();
  if (geoDebounce) clearTimeout(geoDebounce);
  if (val.length < 3 || val.startsWith("📍")) return;
  geoDebounce = setTimeout(async () => {
    try {
      const r = await fetch(`/api/geocode?q=${encodeURIComponent(val)}`);
      if (!r.ok) return;
      const d = await r.json();
      rememberCoords(d.lat, d.lng);
      if (d.city_slug && setCity(d.city_slug)) {
        setGeoStatus(`Адрес найден: ${d.name.split(",").slice(0, 2).join(",")} — город подставлен`);
      } else if (d.city_name) {
        setGeoStatus(`Адрес найден, но город «${d.city_name}» не в списке — поиск по выбранному городу`);
      }
    } catch { /* тихо: подстановка города — не критичная функция */ }
  }, 800);
});

/* ================= Автодополнение запроса ================= */
const SUGGEST_KINDS = {
  query: "запрос",
  category: "категория",
  history: "история",
};

let suggestDebounce = null;
let suggestItems = [];
let suggestIndex = -1;

$("query").addEventListener("input", () => {
  const q = $("query").value.trim();
  if (suggestDebounce) clearTimeout(suggestDebounce);
  if (q.length < 2) {
    hideSuggest();
    return;
  }
  suggestDebounce = setTimeout(() => fetchSuggest(q), 300);
});

async function fetchSuggest(q) {
  try {
    const r = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`);
    if (!r.ok) return hideSuggest();
    const d = await r.json();
    suggestItems = d.items || [];
    suggestIndex = -1;
    renderSuggest(q);
  } catch { /* тихо */ }
}

function renderSuggest(q) {
  const box = $("suggest-box");
  if (!suggestItems.length) return hideSuggest();
  box.innerHTML = "";
  suggestItems.forEach((item, i) => {
    const row = document.createElement("div");
    row.className = "suggest-item";
    row.dataset.index = i;

    const text = document.createElement("span");
    text.className = "suggest-text";
    // выделяем совпавший префикс
    const low = item.text.toLowerCase();
    const pos = low.indexOf(q.toLowerCase());
    if (pos === 0 && item.text.length > q.length) {
      text.append(
        document.createTextNode(item.text.slice(0, q.length)),
        Object.assign(document.createElement("b"), { textContent: item.text.slice(q.length) }),
      );
    } else {
      text.textContent = item.text;
    }

    const tag = document.createElement("span");
    tag.className = "suggest-tag tag-" + item.kind;
    tag.textContent = SUGGEST_KINDS[item.kind] || item.kind;

    row.append(text, tag);
    row.addEventListener("mousedown", (e) => {
      e.preventDefault(); // до blur
      applySuggest(i);
    });
    box.appendChild(row);
  });
  box.classList.remove("hidden");
}

function hideSuggest() {
  $("suggest-box").classList.add("hidden");
  suggestIndex = -1;
}

function applySuggest(i) {
  const item = suggestItems[i];
  if (!item) return;
  $("query").value = item.text;
  hideSuggest();
}

$("query").addEventListener("keydown", (e) => {
  const box = $("suggest-box");
  if (box.classList.contains("hidden")) return;
  const rows = [...box.querySelectorAll(".suggest-item")];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    suggestIndex = e.key === "ArrowDown"
      ? Math.min(suggestIndex + 1, rows.length - 1)
      : Math.max(suggestIndex - 1, 0);
    rows.forEach((r, i) => r.classList.toggle("active", i === suggestIndex));
    rows[suggestIndex]?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter" && suggestIndex >= 0) {
    e.preventDefault();
    applySuggest(suggestIndex);
  } else if (e.key === "Escape") {
    hideSuggest();
  }
});

$("query").addEventListener("blur", () => setTimeout(hideSuggest, 150));

/* ================= Ползунки весов (в сумме 100%) ================= */
const WEIGHT_IDS = ["w-rel", "w-price", "w-dist"];

function readWeights() {
  return Object.fromEntries(WEIGHT_IDS.map((id) => [id, Number($(id).value)]));
}

function setWeights(values) {
  WEIGHT_IDS.forEach((id) => {
    $(id).value = values[id];
    $(id + "-val").textContent = values[id] + "%";
  });
  const v = readWeights();
  $("weights-formula").textContent =
    `Итоговый балл = ${v["w-rel"]}% надёжность + ${v["w-price"]}% цена + ${v["w-dist"]}% близость`;
}

/* при движении одного ползунка остальные пропорционально подстраиваются,
   чтобы сумма всегда оставалась 100% */
function normalizeAround(changedId) {
  const changed = Number($(changedId).value);
  const rest = WEIGHT_IDS.filter((id) => id !== changedId);
  const restSum = rest.reduce((s, id) => s + Number($(id).value), 0);
  const target = 100 - changed;

  if (target === 0) {
    setWeights({ ...readWeights(), [rest[0]]: 0, [rest[1]]: 0 });
    return;
  }
  if (restSum === 0) {
    setWeights({ ...readWeights(), [rest[0]]: Math.round(target / 2), [rest[1]]: target - Math.round(target / 2) });
    return;
  }
  const values = readWeights();
  let acc = 0;
  rest.forEach((id, i) => {
    if (i === rest.length - 1) {
      values[id] = target - acc; // последний absorbs округление
    } else {
      values[id] = Math.round((values[id] / restSum) * target);
      acc += values[id];
    }
  });
  values[changedId] = changed;
  setWeights(values);
}

WEIGHT_IDS.forEach((id) => {
  $(id).addEventListener("input", () => {
    $(id + "-val").textContent = $(id).value + "%";
    normalizeAround(id);
  });
});

/* пресеты */
document.querySelectorAll(".preset-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const [rel, price, dist] = btn.dataset.preset.split(",").map(Number);
    setWeights({ "w-rel": rel, "w-price": price, "w-dist": dist });
  });
});

/* ================= Запуск поиска ================= */
$("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAll();
  hideSuggest();

  const btn = $("submit-btn");
  btn.disabled = true;
  btn.textContent = "Идёт поиск…";

  const loc = $("user-location");
  const payload = {
    query: $("query").value.trim(),
    city: $("city").value,
    price_min: Number($("price-min").value) || null,
    price_max: Number($("price-max").value) || null,
    max_items: Math.min(50, Math.max(1, Number($("max-items").value) || 20)),
    weight_reliability: Number($("w-rel").value) / 100,
    weight_price: Number($("w-price").value) / 100,
    weight_distance: Number($("w-dist").value) / 100,
  };

  // геопозиция: точные координаты от браузера/адреса или геокодирование на бэкенде
  if (loc.dataset.lat && loc.dataset.lng && loc.value.startsWith("📍")) {
    payload.user_lat = parseFloat(loc.dataset.lat);
    payload.user_lng = parseFloat(loc.dataset.lng);
  } else if (loc.value.trim()) {
    payload.user_location = loc.value.trim();
  }

  try {
    const resp = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || "Сервер вернул ошибку");
    }
    const { id } = await resp.json();
    $("progress-card").classList.remove("hidden");
    startPolling(id);
  } catch (e) {
    showError(e.message);
    resetSubmitButton();
  }
});

function startPolling(id) {
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/search/${id}`);
      if (!resp.ok) throw new Error("статус недоступен");
      const st = await resp.json();
      updateProgress(st);

      if (st.status === "done") {
        stopPolling();
        renderResults(st);
        resetSubmitButton();
      } else if (st.status === "error") {
        stopPolling();
        showError(st.error || "Неизвестная ошибка");
        resetSubmitButton();
      }
    } catch (e) {
      stopPolling();
      showError("Потеряна связь с сервером: " + e.message);
      resetSubmitButton();
    }
  }, 2000);
}

function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

function resetSubmitButton() {
  const btn = $("submit-btn");
  btn.disabled = false;
  btn.textContent = "Найти и отсортировать";
}

/* ================= Прогресс ================= */
function updateProgress(st) {
  $("progress-step").textContent = st.current_step || "Работаем…";
  if (st.total > 0) {
    const pct = Math.round((st.processed / st.total) * 100);
    $("progress-count").textContent = `${st.processed} / ${st.total}`;
    $("progress-fill").style.width = pct + "%";
  } else {
    $("progress-count").textContent = "";
    $("progress-fill").style.width = "8%";
  }
}

function showError(text) {
  hideAll();
  $("error-card").classList.remove("hidden");
  $("error-text").textContent = text;
}

function hideAll() {
  for (const id of ["progress-card", "error-card", "results-section"]) {
    $(id).classList.add("hidden");
  }
  $("progress-fill").style.width = "0%";
}

/* ================= Результаты ================= */
function scoreClass(v) { return v >= 70 ? "score-good" : v >= 45 ? "score-mid" : "score-low"; }

function fmtDistance(km) {
  if (km == null) return "—";
  return km < 1 ? `${Math.round(km * 1000)} м` : `${km.toFixed(1)} км`;
}

function fmtPrice(p) {
  if (p == null) return "Цена не указана";
  return p.toLocaleString("ru-RU") + " ₽";
}

function renderResults(st) {
  hideAll();
  currentResults = st.results;

  if (!st.results.length) {
    showError("Объявления не найдены. Попробуйте изменить запрос, город или фильтры цены.");
    return;
  }

  $("results-section").classList.remove("hidden");
  $("results-title").textContent = `Найдено ${st.results.length} объявлений`;
  renderList(sortResults($("sort-select").value));
}

function sortResults(mode) {
  const items = [...(currentResults || [])];
  switch (mode) {
    case "price": items.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity)); break;
    case "distance": items.sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity)); break;
    case "rating": items.sort((a, b) => (b.seller.rating ?? -1) - (a.seller.rating ?? -1)); break;
    default: items.sort((a, b) => b.scores.total - a.scores.total);
  }
  return items;
}

$("sort-select").addEventListener("change", () => {
  if (currentResults) renderList(sortResults($("sort-select").value));
});

function renderList(items) {
  const list = $("results-list");
  list.innerHTML = "";

  for (const it of items) {
    const card = document.createElement("div");
    card.className = "listing-card";

    const imgBox = document.createElement("div");
    imgBox.className = "img-box";
    if (it.image_url) {
      const img = document.createElement("img");
      img.src = it.image_url;
      img.alt = it.title;
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      imgBox.appendChild(img);
    }

    const main = document.createElement("div");
    main.className = "listing-main";

    const title = document.createElement("h3");
    const link = document.createElement("a");
    link.href = it.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = it.title || "(без заголовка)";
    title.appendChild(link);

    const price = document.createElement("p");
    price.className = "listing-price";
    price.textContent = fmtPrice(it.price);

    const metaLoc = document.createElement("p");
    metaLoc.className = "listing-meta";
    metaLoc.textContent = `📍 ${it.location_text || "—"} · ${fmtDistance(it.distance_km)} от вас`;

    const s = it.seller;
    const metaSeller = document.createElement("p");
    metaSeller.className = "listing-meta";
    const ratingStr = s.rating != null ? `★ ${s.rating}` : "★ —";
    const reviewsStr = s.reviews ? ` · ${s.reviews} отз.` : "";
    const sinceStr = s.member_since ? ` · на Avito с ${s.member_since}` : "";
    metaSeller.textContent = `${s.name || "Продавец"} · ${ratingStr}${reviewsStr}${sinceStr}`;

    main.append(title, price, metaLoc, metaSeller);

    if (it.description) {
      const desc = document.createElement("p");
      desc.className = "listing-desc";
      desc.textContent = it.description;
      main.appendChild(desc);
    }

    for (const badge of s.badges || []) {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = badge;
      main.appendChild(b);
    }

    const panel = document.createElement("div");
    panel.className = "score-panel";

    const total = document.createElement("div");
    total.className = "total-score";
    const num = document.createElement("span");
    num.className = "num " + scoreClass(it.scores.total);
    num.textContent = it.scores.total.toFixed(0);
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = "итоговый балл";
    total.append(num, lbl);

    const pill = (name, val) => {
      const p = document.createElement("div");
      p.className = "score-pill";
      const left = document.createElement("span");
      left.textContent = name;
      const right = document.createElement("b");
      right.className = scoreClass(val);
      right.textContent = val != null ? val.toFixed(0) : "—";
      p.append(left, right);
      return p;
    };
    panel.append(
      total,
      pill("Надёжность", it.scores.reliability),
      pill("Цена", it.scores.price),
      pill("Близость", it.scores.distance),
    );

    card.append(imgBox, main, panel);
    list.appendChild(card);
  }
}

/* ================= init ================= */
loadCities();
setWeights({ "w-rel": 40, "w-price": 30, "w-dist": 30 });
