// Province normalization: map variants to canonical names
const PROVINCE_NORMALIZE = {
  "北京市": "北京",
  "天津市": "天津",
  "上海市": "上海",
  "重庆市": "重庆",
  "河北省": "河北",
  "山西省": "山西",
  "辽宁省": "辽宁",
  "吉林省": "吉林",
  "黑龙江省": "黑龙江",
  "江苏省": "江苏",
  "浙江省": "浙江",
  "安徽省": "安徽",
  "福建省": "福建",
  "江西省": "江西",
  "山东省": "山东",
  "河南省": "河南",
  "湖北省": "湖北",
  "湖南省": "湖南",
  "广东省": "广东",
  "海南省": "海南",
  "四川省": "四川",
  "贵州省": "贵州",
  "云南省": "云南",
  "陕西省": "陕西",
  "甘肃省": "甘肃",
  "青海省": "青海",
  "内蒙古自治区": "内蒙古",
  "广西壮族自治区": "广西",
  "西藏自治区": "西藏",
  "宁夏回族自治区": "宁夏",
  "新疆维吾尔自治区": "新疆",
  "香港特别行政区": "香港",
  "澳门特别行政区": "澳门",
  "台湾省": "台湾",
  "台湾": "台湾",
};

const MS_PER_DAY = 86400000;
const DAYS_IN_WEEK = 7;

const state = {
  sourceRows: [],
  filteredRows: [],
  sortKey: "pub_time",
  sortDirection: "desc",
  page: 1,
  pageSize: 50,
  keyword: "",
  province: "",
  city: "",
  budgetMin: "",
  budgetMax: "",
  showNoRequirement: false,
  showExpired: false,
};

const tableBody = document.getElementById("tableBody");
const summaryText = document.getElementById("summaryText");
const emptyState = document.getElementById("emptyState");
const pageNumbers = document.getElementById("pageNumbers");
const searchInput = document.getElementById("searchInput");
const provinceFilter = document.getElementById("provinceFilter");
const cityFilter = document.getElementById("cityFilter");
const budgetMinInput = document.getElementById("budgetMinInput");
const budgetMaxInput = document.getElementById("budgetMaxInput");
const showNoRequirementCheckbox = document.getElementById("showNoRequirement");
const showExpiredCheckbox = document.getElementById("showExpired");
const pageSizeSelect = document.getElementById("pageSizeSelect");
const headers = Array.from(document.querySelectorAll("th[data-key]"));
const detailModal = document.getElementById("detailModal");
const modalClose = document.getElementById("modalClose");

function parseBudgetToWan(rawValue) {
  const text = String(rawValue || "").trim();
  if (!text) {
    return Number.NaN;
  }

  const numeric = Number.parseFloat(text.replace(/[^\d.]/g, ""));
  if (!Number.isFinite(numeric)) {
    return Number.NaN;
  }

  if (text.includes("万元")) {
    return numeric;
  }
  if (text.includes("亿元")) {
    return numeric * 10000;
  }
  if (text.includes("元")) {
    return numeric / 10000;
  }
  return numeric;
}

function toDateOnly(rawValue) {
  if (!rawValue) {
    return "";
  }
  const text = String(rawValue).trim();
  const dateMatch = text.match(/\d{4}-\d{2}-\d{2}/);
  return dateMatch ? dateMatch[0] : text.slice(0, 10);
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function highlightHtml(text, keyword) {
  const str = String(text || "");
  if (!keyword || keyword.length > 200) {
    return escapeHtml(str);
  }
  const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(escapedKeyword, "gi");
  let last = 0;
  let result = "";
  let match;
  while ((match = regex.exec(str)) !== null) {
    result += escapeHtml(str.slice(last, match.index));
    result += `<mark class="hl">${escapeHtml(match[0])}</mark>`;
    last = match.index + match[0].length;
  }
  result += escapeHtml(str.slice(last));
  return result;
}

function normalizeProvince(raw) {
  const s = String(raw || "").trim();
  return PROVINCE_NORMALIZE[s] || s;
}

function normalizeRow(rawRow) {
  const pubDate = toDateOnly(rawRow.pub_time);
  const deadlineDate = toDateOnly(rawRow.deadline);
  const province = normalizeProvince(rawRow.province);
  const city = String(rawRow.city || "").trim();

  return {
    ...rawRow,
    pub_time: pubDate,
    deadline: deadlineDate,
    project_name: String(rawRow.project_name || "").trim(),
    province,
    city,
    province_city: [province, city].filter(Boolean).join(" / "),
    company_name: String(rawRow.company_name || "").trim(),
    budget: String(rawRow.budget || "").trim(),
    budget_wan: parseBudgetToWan(rawRow.budget),
    requirement_brief: String(rawRow.requirement_brief || "").trim(),
    requirement_desc: String(rawRow.requirement_desc || "").trim(),
    announcement_url: String(rawRow.announcement_url || "").trim(),
  };
}

function getSortableValue(row, key) {
  if (key === "pub_time" || key === "deadline") {
    return row[key] || "0000-00-00";
  }
  if (key === "budget") {
    const numeric = row.budget_wan;
    return Number.isFinite(numeric) ? numeric : -1;
  }
  return String(row[key] || "").toLowerCase();
}

function parseLocalDateOnly(dateStr) {
  if (!dateStr) return null;
  const match = String(dateStr).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (match) {
    const year = Number.parseInt(match[1], 10);
    const month = Number.parseInt(match[2], 10);
    const day = Number.parseInt(match[3], 10);
    const date = new Date(year, month - 1, day);
    if (
      date.getFullYear() !== year ||
      date.getMonth() !== month - 1 ||
      date.getDate() !== day
    ) {
      return null;
    }
    return date;
  }
  const fallback = new Date(dateStr);
  return Number.isNaN(fallback.getTime()) ? null : fallback;
}

function getDaysUntilDeadline(deadlineStr) {
  if (!deadlineStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const deadline = parseLocalDateOnly(deadlineStr);
  if (!deadline) return null;
  return Math.floor((deadline - today) / MS_PER_DAY);
}

function applyFilters() {
  const keyword = state.keyword.toLowerCase();
  const minBudget = state.budgetMin === "" ? Number.NaN : Number.parseFloat(state.budgetMin);
  const maxBudget = state.budgetMax === "" ? Number.NaN : Number.parseFloat(state.budgetMax);

  state.filteredRows = state.sourceRows.filter((row) => {
    if (!state.showNoRequirement && (row.requirement_desc.includes("无相关要求") || row.requirement_brief.includes("无相关要求"))) {
      return false;
    }

    if (!state.showExpired) {
      const days = getDaysUntilDeadline(row.deadline);
      if (days !== null && days < 0) {
        return false;
      }
    }

    if (state.province && row.province !== state.province) {
      return false;
    }

    if (state.city && row.city !== state.city) {
      return false;
    }

    if (Number.isFinite(minBudget)) {
      if (!Number.isFinite(row.budget_wan) || row.budget_wan < minBudget) {
        return false;
      }
    }

    if (Number.isFinite(maxBudget)) {
      if (!Number.isFinite(row.budget_wan) || row.budget_wan > maxBudget) {
        return false;
      }
    }

    if (!keyword) {
      return true;
    }

    const haystack = [
      row.project_name,
      row.province_city,
      row.company_name,
      row.budget,
      row.requirement_brief,
      row.requirement_desc,
      row.pub_time,
      row.deadline,
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(keyword);
  });
}

function applySort() {
  state.filteredRows.sort((a, b) => {
    const left = getSortableValue(a, state.sortKey);
    const right = getSortableValue(b, state.sortKey);

    if (left < right) {
      return state.sortDirection === "asc" ? -1 : 1;
    }
    if (left > right) {
      return state.sortDirection === "asc" ? 1 : -1;
    }
    return 0;
  });
}

function renderSummary(totalRows, visibleRows) {
  summaryText.textContent = `共 ${totalRows} 条数据，当前筛选后 ${visibleRows} 条。`;
}

function renderSortIndicators() {
  headers.forEach((th) => {
    const key = th.dataset.key;
    const arrow = key === state.sortKey ? (state.sortDirection === "asc" ? "▲" : "▼") : "";
    const plainText = th.textContent.replace(/[▲▼]/g, "").trim();
    th.innerHTML = `${escapeHtml(plainText)}<span class="sort-indicator">${arrow}</span>`;
  });
}

function renderTablePage() {
  const total = state.filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));

  if (state.page > totalPages) {
    state.page = totalPages;
  }

  const start = (state.page - 1) * state.pageSize;
  const pageRows = state.filteredRows.slice(start, start + state.pageSize);
  const keyword = state.keyword;

  tableBody.innerHTML = pageRows
    .map((row, i) => {
      const filteredIdx = start + i;
      const days = getDaysUntilDeadline(row.deadline);
      const isExpired = days !== null && days < 0;
      const isUrgent = days !== null && days >= 0 && days <= 3;

      let rowClass = "";
      if (isUrgent) rowClass = "row-urgent";
      else if (isExpired) rowClass = "row-expired";

      let deadlineBadge = "";
      if (isUrgent) {
        deadlineBadge = `<span class="badge-urgent">即将截止</span>`;
      } else if (isExpired) {
        deadlineBadge = `<span class="badge-expired">已截止</span>`;
      }

      const titleText = highlightHtml(row.project_name || "(无标题)", keyword);
      const isSafeTitleUrl = row.announcement_url && /^https?:\/\//i.test(row.announcement_url);
      const titleHtml = isSafeTitleUrl
        ? `<a class="title-link" data-row-index="${filteredIdx}" href="${escapeHtml(row.announcement_url)}">${titleText}</a>`
        : `<span class="title-link" data-row-index="${filteredIdx}">${titleText}</span>`;

      return `<tr class="${rowClass}">
        <td>${highlightHtml(row.pub_time, keyword)}</td>
        <td>${highlightHtml(row.deadline, keyword)}${deadlineBadge}</td>
        <td>${titleHtml}</td>
        <td>${highlightHtml(row.province_city, keyword)}</td>
        <td>${highlightHtml(row.company_name, keyword)}</td>
        <td>${highlightHtml(row.budget, keyword)}</td>
        <td class="summary-cell">${highlightHtml(row.requirement_brief || "-", keyword)}</td>
      </tr>`;
    })
    .join("");

  emptyState.hidden = pageRows.length > 0;
  renderPagination(totalPages);
}

function renderSkeletonRows(count = 5) {
  tableBody.innerHTML = Array.from({ length: count }, () => `<tr class="skeleton-row">
    <td><span class="skeleton-cell narrow"></span></td>
    <td><span class="skeleton-cell narrow"></span></td>
    <td><span class="skeleton-cell wide"></span></td>
    <td><span class="skeleton-cell medium"></span></td>
    <td><span class="skeleton-cell medium"></span></td>
    <td><span class="skeleton-cell narrow"></span></td>
    <td><span class="skeleton-cell full"></span></td>
  </tr>`).join("");
  emptyState.hidden = true;
}

function renderStats() {
  const total = state.sourceRows.length;

  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const weekAgo = new Date(now);
  weekAgo.setDate(weekAgo.getDate() - DAYS_IN_WEEK);
  const weekAgoStr = weekAgo.toISOString().slice(0, 10);
  const weekNew = state.sourceRows.filter((r) => r.pub_time >= weekAgoStr).length;

  const budgets = state.sourceRows.map((r) => r.budget_wan).filter((b) => Number.isFinite(b));
  const avgBudget = budgets.length ? budgets.reduce((a, b) => a + b, 0) / budgets.length : 0;
  const avgBudgetStr = avgBudget > 0 ? `${Math.round(avgBudget).toLocaleString("zh-CN")} 万元` : "—";

  const provinces = new Set(state.sourceRows.map((r) => r.province).filter(Boolean));

  const maxPubTime = state.sourceRows
    .map((r) => r.pub_time)
    .filter(Boolean)
    .sort()
    .slice(-1)[0] || "—";

  document.getElementById("statTotal").textContent = total.toLocaleString("zh-CN");
  document.getElementById("statWeekNew").textContent = weekNew.toLocaleString("zh-CN");
  document.getElementById("statAvgBudget").textContent = avgBudgetStr;
  document.getElementById("statProvinces").textContent = provinces.size;
  document.getElementById("lastUpdateTime").textContent = maxPubTime;
}

function openDetailModal(row) {
  document.getElementById("modalTitle").textContent = row.project_name || "(无标题)";

  const metaParts = [
    row.pub_time ? `发布：${escapeHtml(row.pub_time)}` : "",
    row.deadline ? `截止：${escapeHtml(row.deadline)}` : "",
    row.province_city ? `地区：${escapeHtml(row.province_city)}` : "",
    row.company_name ? `采购单位：${escapeHtml(row.company_name)}` : "",
    row.budget ? `预算：${escapeHtml(row.budget)}` : "",
  ].filter(Boolean);
  document.getElementById("modalMeta").innerHTML = metaParts.map((p) => `<span>${p}</span>`).join("");

  const brief = row.requirement_brief;
  const briefSection = document.getElementById("modalBriefSection");
  briefSection.hidden = !brief || brief === "-";
  document.getElementById("modalBrief").textContent = brief || "";

  const desc = row.requirement_desc;
  const descSection = document.getElementById("modalDescSection");
  const hideDesc = !desc || desc === "无相关要求" || desc === "-";
  descSection.hidden = hideDesc;
  document.getElementById("modalDesc").textContent = desc || "";

  const modalLink = document.getElementById("modalLink");
  const isSafeUrl = row.announcement_url && /^https?:\/\//i.test(row.announcement_url);
  if (isSafeUrl) {
    modalLink.href = row.announcement_url;
    modalLink.hidden = false;
  } else {
    modalLink.hidden = true;
  }

  detailModal.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDetailModal() {
  detailModal.hidden = true;
  document.body.style.overflow = "";
}

function refillProvinceOptions() {
  const provinces = [...new Set(state.sourceRows.map((row) => row.province).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-Hans-CN")
  );

  provinceFilter.innerHTML = `<option value="">全部</option>${provinces
    .map((province) => `<option value="${escapeHtml(province)}">${escapeHtml(province)}</option>`)
    .join("")}`;
}

function refillCityOptions() {
  const citySource = state.sourceRows.filter((row) => {
    if (!state.province) {
      return true;
    }
    return row.province === state.province;
  });

  const cities = [...new Set(citySource.map((row) => row.city).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-Hans-CN")
  );

  cityFilter.innerHTML = `<option value="">全部</option>${cities
    .map((city) => `<option value="${escapeHtml(city)}">${escapeHtml(city)}</option>`)
    .join("")}`;

  if (state.city && !cities.includes(state.city)) {
    state.city = "";
    cityFilter.value = "";
  }
}

function buildPageItems(totalPages) {
  const pages = [];
  const current = state.page;
  const start = Math.max(1, current - 2);
  const end = Math.min(totalPages, current + 2);

  pages.push(1);
  if (start > 2) {
    pages.push("...");
  }
  for (let page = start; page <= end; page += 1) {
    if (page !== 1 && page !== totalPages) {
      pages.push(page);
    }
  }
  if (end < totalPages - 1) {
    pages.push("...");
  }
  if (totalPages > 1) {
    pages.push(totalPages);
  }

  return [...new Set(pages)];
}

function renderPagination(totalPages) {
  const items = buildPageItems(totalPages);

  pageNumbers.innerHTML = items
    .map((item) => {
      if (item === "...") {
        return '<span class="page-ellipsis">...</span>';
      }
      const page = Number(item);
      const activeClass = page === state.page ? " active" : "";
      return `<button type="button" class="page-btn${activeClass}" data-page="${page}">${page}</button>`;
    })
    .join("");
}

function syncStateToUrl() {
  const params = new URLSearchParams();
  if (state.keyword) params.set("q", state.keyword);
  if (state.province) params.set("province", state.province);
  if (state.city) params.set("city", state.city);
  if (state.budgetMin) params.set("budgetMin", state.budgetMin);
  if (state.budgetMax) params.set("budgetMax", state.budgetMax);
  if (state.showNoRequirement) params.set("showNoReq", "1");
  if (state.showExpired) params.set("showExpired", "1");
  const str = params.toString();
  window.history.replaceState(null, "", str ? `?${str}` : window.location.pathname);
}

function loadStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("q")) state.keyword = params.get("q");
  if (params.has("province")) state.province = params.get("province");
  if (params.has("city")) state.city = params.get("city");
  if (params.has("budgetMin")) state.budgetMin = params.get("budgetMin");
  if (params.has("budgetMax")) state.budgetMax = params.get("budgetMax");
  if (params.has("showNoReq")) state.showNoRequirement = true;
  if (params.has("showExpired")) state.showExpired = true;
}

function applyUrlStateToInputs() {
  if (state.keyword) searchInput.value = state.keyword;
  if (state.budgetMin) budgetMinInput.value = state.budgetMin;
  if (state.budgetMax) budgetMaxInput.value = state.budgetMax;
  if (state.showNoRequirement) showNoRequirementCheckbox.checked = true;
  if (state.showExpired) showExpiredCheckbox.checked = true;
}

function refreshTable() {
  applyFilters();
  applySort();
  renderSortIndicators();
  renderSummary(state.sourceRows.length, state.filteredRows.length);
  renderTablePage();
}

function bindEvents() {
  searchInput.addEventListener("input", (event) => {
    state.keyword = event.target.value.trim();
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  provinceFilter.addEventListener("change", (event) => {
    state.province = event.target.value;
    state.city = "";
    refillCityOptions();
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  cityFilter.addEventListener("change", (event) => {
    state.city = event.target.value;
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  budgetMinInput.addEventListener("input", (event) => {
    state.budgetMin = event.target.value.trim();
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  budgetMaxInput.addEventListener("input", (event) => {
    state.budgetMax = event.target.value.trim();
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  showNoRequirementCheckbox.addEventListener("change", (event) => {
    state.showNoRequirement = event.target.checked;
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  showExpiredCheckbox.addEventListener("change", (event) => {
    state.showExpired = event.target.checked;
    state.page = 1;
    refreshTable();
    syncStateToUrl();
  });

  pageSizeSelect.addEventListener("change", (event) => {
    state.pageSize = Number.parseInt(event.target.value, 10) || 50;
    state.page = 1;
    refreshTable();
  });

  headers.forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDirection = key === "pub_time" || key === "deadline" ? "desc" : "asc";
      }
      refreshTable();
    });
  });

  pageNumbers.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-page]");
    if (!btn) {
      return;
    }
    const page = Number.parseInt(btn.dataset.page || "", 10);
    if (Number.isFinite(page)) {
      state.page = page;
      renderTablePage();
    }
  });

  // Detail modal: open on title click
  tableBody.addEventListener("click", (event) => {
    const link = event.target.closest(".title-link");
    if (!link) return;
    event.preventDefault();
    const idx = Number.parseInt(link.dataset.rowIndex || "", 10);
    if (Number.isFinite(idx) && state.filteredRows[idx]) {
      openDetailModal(state.filteredRows[idx]);
    }
  });

  modalClose.addEventListener("click", closeDetailModal);

  detailModal.addEventListener("click", (event) => {
    if (event.target === detailModal) {
      closeDetailModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !detailModal.hidden) {
      closeDetailModal();
    }
  });
}

function loadCsvAndInit() {
  loadStateFromUrl();
  applyUrlStateToInputs();
  renderSkeletonRows();

  Papa.parse("data/tender_items.csv", {
    download: true,
    header: true,
    skipEmptyLines: true,
    complete: (result) => {
      const rows = Array.isArray(result.data) ? result.data : [];
      state.sourceRows = rows.map(normalizeRow);
      refillProvinceOptions();
      const availableProvinces = Array.from(provinceFilter.options).map((opt) => opt.value);
      if (state.province && !availableProvinces.includes(state.province)) {
        state.province = "";
        provinceFilter.value = "";
      } else if (state.province) {
        provinceFilter.value = state.province;
      }
      refillCityOptions();
      if (state.city) cityFilter.value = state.city;
      renderStats();
      refreshTable();
    },
    error: () => {
      summaryText.textContent = "数据加载失败，请稍后刷新重试。";
      tableBody.innerHTML = "";
      emptyState.hidden = false;
    },
  });
}

bindEvents();
loadCsvAndInit();
