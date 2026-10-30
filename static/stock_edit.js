(function () {
  const form = document.getElementById("stock-form");
  if (!form) return;

  const marketSelect = document.getElementById("stock-market");
  const initialMarketInput = document.getElementById("initial-market");
  const fieldGroups = document.querySelectorAll(".market-fields");

  // Read the market value that was embedded by the template, and set
  // the dropdown to it before doing anything else.
  const initialMarket =
    (initialMarketInput && initialMarketInput.value) || "United States";
  marketSelect.value = initialMarket;

  function syncFields() {
    const chosen = marketSelect.value;
    fieldGroups.forEach(function (group) {
      const match = group.dataset.market === chosen;
      group.hidden = !match;
      group.querySelectorAll("input, select, textarea").forEach(function (el) {
        el.disabled = !match;
      });
    });
  }

  // ---- US: live returns ----
  const usInvested = document.getElementById("us_total_invested");
  const usValue = document.getElementById("us_current_value");
  const usReturnsAmount = document.getElementById("us_returns_amount");
  const usReturnsPct = document.getElementById("us_returns_pct");

  function computeUS() {
    if (!usInvested || !usValue || !usReturnsAmount || !usReturnsPct) return;
    const invested = parseFloat(usInvested.value) || 0;
    const value = parseFloat(usValue.value) || 0;
    const returns = value - invested;
    const pct = invested ? (returns / invested) * 100 : 0;

    usReturnsAmount.value =
      (returns >= 0 ? "+" : "-") + "$" + Math.abs(returns).toFixed(2);
    usReturnsPct.value = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";

    usReturnsAmount.classList.toggle("negative", returns < 0);
    usReturnsAmount.classList.toggle("positive", returns >= 0);
    usReturnsPct.classList.toggle("negative", returns < 0);
    usReturnsPct.classList.toggle("positive", returns >= 0);
  }

  // ---- India: live value/return ----
  const inQty = document.getElementById("number_of_shares");
  const inBuyPrice = document.getElementById("buy_price");
  const inCurrentPrice = document.getElementById("current_price");
  const inValueCost = document.getElementById("india_value_cost");
  const inValueMarket = document.getElementById("india_value_market");
  const inUnrealized = document.getElementById("india_unrealized");
  const inUnrealizedPct = document.getElementById("india_unrealized_pct");

  function computeIndia() {
    if (!inQty || !inBuyPrice || !inCurrentPrice) return;
    const qty = parseFloat(inQty.value) || 0;
    const buy = parseFloat(inBuyPrice.value) || 0;
    const current = parseFloat(inCurrentPrice.value) || 0;

    const valueCost = qty * buy;
    const valueMarket = qty * current;
    const unrealized = valueMarket - valueCost;
    const pct = valueCost ? (unrealized / valueCost) * 100 : 0;

    inValueCost.value = "\u20B9" + valueCost.toFixed(2);
    inValueMarket.value = "\u20B9" + valueMarket.toFixed(2);
    inUnrealized.value =
      (unrealized >= 0 ? "+" : "-") +
      "\u20B9" +
      Math.abs(unrealized).toFixed(2);
    inUnrealizedPct.value = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";

    inUnrealized.classList.toggle("negative", unrealized < 0);
    inUnrealized.classList.toggle("positive", unrealized >= 0);
    inUnrealizedPct.classList.toggle("negative", unrealized < 0);
    inUnrealizedPct.classList.toggle("positive", unrealized >= 0);
  }

  function recompute() {
    syncFields();
    computeUS();
    computeIndia();
  }

  marketSelect.addEventListener("change", recompute);

  [usInvested, usValue, inQty, inBuyPrice, inCurrentPrice].forEach(
    function (el) {
      if (el) el.addEventListener("input", recompute);
    },
  );

  recompute();
})();
