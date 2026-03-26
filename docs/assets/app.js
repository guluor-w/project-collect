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
const pageSizeSelect = document.getElementById("pageSizeSelect");
const headers = Array.from(document.querySelectorAll("th[data-key]"));

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

function normalizeRow(rawRow) {
  const pubDate = toDateOnly(rawRow.pub_time);
  const deadlineDate = toDateOnly(rawRow.deadline);
  const province = String(rawRow.province || "").trim();
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

function applyFilters() {
  const keyword = state.keyword.toLowerCase();
  const minBudget = state.budgetMin === "" ? Number.NaN : Number.parseFloat(state.budgetMin);
  const maxBudget = state.budgetMax === "" ? Number.NaN : Number.parseFloat(state.budgetMax);

  state.filteredRows = state.sourceRows.filter((row) => {
    if (!state.showNoRequirement && row.requirement_desc === "无相关要求") {
      return false;
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
    th.innerHTML = `${plainText}<span class="sort-indicator">${arrow}</span>`;
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

  tableBody.innerHTML = pageRows
    .map((row) => {
      const titleHtml = row.announcement_url
        ? `<a class="title-link" href="${escapeHtml(row.announcement_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.project_name || "(无标题)")}</a>`
        : escapeHtml(row.project_name || "(无标题)");

      return `<tr>
        <td>${escapeHtml(row.pub_time)}</td>
        <td>${escapeHtml(row.deadline)}</td>
        <td>${titleHtml}</td>
        <td>${escapeHtml(row.province_city)}</td>
        <td>${escapeHtml(row.company_name)}</td>
        <td>${escapeHtml(row.budget)}</td>
        <td class="summary-cell">${escapeHtml(row.requirement_brief || "-")}</td>
      </tr>`;
    })
    .join("");

  emptyState.hidden = pageRows.length > 0;
  renderPagination(totalPages);
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
  });

  provinceFilter.addEventListener("change", (event) => {
    state.province = event.target.value;
    state.city = "";
    refillCityOptions();
    state.page = 1;
    refreshTable();
  });

  cityFilter.addEventListener("change", (event) => {
    state.city = event.target.value;
    state.page = 1;
    refreshTable();
  });

  budgetMinInput.addEventListener("input", (event) => {
    state.budgetMin = event.target.value.trim();
    state.page = 1;
    refreshTable();
  });

  budgetMaxInput.addEventListener("input", (event) => {
    state.budgetMax = event.target.value.trim();
    state.page = 1;
    refreshTable();
  });

  showNoRequirementCheckbox.addEventListener("change", (event) => {
    state.showNoRequirement = event.target.checked;
    state.page = 1;
    refreshTable();
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
}

function loadCsvAndInit() {
  Papa.parse("data/tender_items.csv", {
    download: true,
    header: true,
    skipEmptyLines: true,
    complete: (result) => {
      const rows = Array.isArray(result.data) ? result.data : [];
      state.sourceRows = rows.map(normalizeRow);
      refillProvinceOptions();
      refillCityOptions();
      refreshTable();
    },
    error: () => {
      summaryText.textContent = "数据加载失败，请稍后刷新重试。";
      emptyState.hidden = false;
    },
  });
}

bindEvents();
loadCsvAndInit();
