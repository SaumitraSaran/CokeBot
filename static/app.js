/* ═══════════════════════════════════════════════════════════════════
   Cokebot AI — Financial AI Chatbot
   Client-side logic
   ═══════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────
  const chatArea      = document.getElementById("chat-area");
  const messagesEl    = document.getElementById("messages");
  const welcomeEl     = document.getElementById("welcome");
  const askForm       = document.getElementById("askForm");
  const questionInput = document.getElementById("questionInput");
  const askBtn        = document.getElementById("askBtn");
  const statusDot     = document.getElementById("statusDot");
  const statusLabel   = document.getElementById("statusLabel");
  const welcomeChips  = document.getElementById("welcomeChips");
  const commandCards  = document.getElementById("commandCards");
  const freshnessLabel = document.getElementById("freshnessLabel");

  let isProcessing = false;
  // Only short, user-visible conversation context is sent for follow-up questions.
  const conversation = [];

  loadCommandCenter();

  async function loadCommandCenter() {
    try {
      const response = await fetch("/api/command-center");
      const payload = await response.json();
      if (!response.ok) throw new Error("Command center unavailable");
      freshnessLabel.textContent = payload.freshness;
      const cards = [
        ["Latest revenue", payload.cards.latest_amount],
        ["Prior-day revenue", payload.cards.yesterday_amount],
        ["Active customers", payload.cards.active_customers],
        ["Top customer", payload.cards.largest_customer],
      ];
      cards.forEach(([label, result]) => {
        const row = result?.rows?.[0] || [];
        const card = document.createElement("button");
        card.className = "command-card";
        card.innerHTML = `<span>${label}</span><strong></strong><small></small>`;
        card.querySelector("strong").textContent = row[1] ?? row[0] ?? "—";
        card.querySelector("small").textContent = row[0] && row[1] ? row[0] : "Verified data";
        card.addEventListener("click", () => sendQuestion(label === "Top customer" ? "Show top 10 customers this month" : `Explain ${label.toLowerCase()}`));
        commandCards.appendChild(card);
      });
    } catch (_) {
      freshnessLabel.textContent = "Metrics load when the data service is online";
    }
  }

  // ── Auto-resize textarea ──────────────────────────────────────────
  questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 160) + "px";
  });

  // ── Keyboard handling ─────────────────────────────────────────────
  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      askForm.requestSubmit();
    }
  });

  // ── Suggestion chips ──────────────────────────────────────────────
  welcomeChips.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    questionInput.value = chip.dataset.q;
    questionInput.dispatchEvent(new Event("input"));
    askForm.requestSubmit();
  });

  // ── Form submit ───────────────────────────────────────────────────
  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    if (!question || isProcessing) return;
    await sendQuestion(question);
  });

  // ── Send question flow ────────────────────────────────────────────
  async function sendQuestion(question) {
    isProcessing = true;
    setStatus("thinking");
    askBtn.disabled = true;

    // Hide welcome, show messages
    welcomeEl.style.display = "none";
    messagesEl.style.display = "flex";

    // Add user message
    appendMessage("user", question);
    conversation.push({ role: "user", content: question });
    questionInput.value = "";
    questionInput.style.height = "auto";

    // Show thinking indicator
    const thinkingEl = appendThinking();
    scrollToBottom();

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, context: conversation.slice(-6, -1) }),
      });

      const data = await res.json();

      // Remove thinking indicator
      thinkingEl.remove();

      if (data.error) {
        appendMessage("error", data.error);
      } else if (data.options && data.options.length > 0) {
        // Clarification flow
        appendMessage("ai", data.answer, null, data.options);
      } else if (data.answer && !data.data) {
        appendMessage("ai", data.answer);
      } else {
        const msgEl = appendMessage("ai", data.answer, data.sql, null, data.data, data.insight, data.meta, data.query_type, data.explanation, data.trust, question);
        
        if (data.data) {
           const answerThinkingEl = document.createElement("div");
           answerThinkingEl.className = "answer-loading";
           answerThinkingEl.innerHTML = `<img class="loading-can" src="assets/can.jpeg" alt="" aria-hidden="true" /> Generating summary...`;
           msgEl.querySelector('.msg-body').appendChild(answerThinkingEl);
           scrollToBottom();
           
           try {
             const answerRes = await fetch("/api/answer", {
               method: "POST",
               headers: { "Content-Type": "application/json" },
               body: JSON.stringify({ question, data: data.data }),
             });
             const answerData = await answerRes.json();
             answerThinkingEl.remove();
             if (answerData.error) {
               const errorBubble = document.createElement("div");
               errorBubble.className = "msg-bubble error-bubble";
               errorBubble.textContent = answerData.error;
               msgEl.querySelector('.msg-body').appendChild(errorBubble);
             } else {
               const answerBubble = document.createElement("div");
               answerBubble.className = "msg-bubble";
               answerBubble.textContent = answerData.answer;
               msgEl.querySelector('.msg-body').appendChild(answerBubble);
               conversation.push({ role: "assistant", content: answerData.answer });
               
               // Add Feedback UI (Correct / Incorrect)
               const feedbackContainer = document.createElement("div");
               feedbackContainer.className = "feedback-container";
               const currentIntent = data.intent || "";

               const renderFeedbackButtons = () => {
                 feedbackContainer.innerHTML = `
                   <div class="feedback-actions">
                     <button class="feedback-btn feedback-btn--correct" title="Mark response as correct">
                       <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                       Correct
                     </button>
                     <button class="feedback-btn feedback-btn--incorrect" title="Report response as incorrect">
                       <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                       Report as incorrect
                     </button>
                   </div>
                 `;

                 // Handle Correct button click
                 feedbackContainer.querySelector('.feedback-btn--correct').addEventListener('click', async () => {
                   feedbackContainer.innerHTML = `
                     <span class="feedback-success feedback-success--correct">
                       <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                       Marked as correct. Thank you!
                     </span>
                   `;
                   try {
                     await fetch('/api/report', {
                       method: 'POST',
                       headers: { 'Content-Type': 'application/json' },
                       body: JSON.stringify({
                         question,
                         intent: currentIntent,
                         is_correct: true
                       })
                     });
                   } catch (e) {
                     console.error("Feedback error:", e);
                   }

                 });

                 // Handle Incorrect button click
                 feedbackContainer.querySelector('.feedback-btn--incorrect').addEventListener('click', () => {
                   feedbackContainer.innerHTML = `
                     <div class="report-form">
                       <input type="text" class="report-input" placeholder="What is wrong with this response? (e.g. wrong column, ordering)" />
                       <button class="report-submit-btn">Submit</button>
                       <button class="report-cancel-btn">Cancel</button>
                     </div>
                   `;
                   const input = feedbackContainer.querySelector('.report-input');
                   input.focus();

                   feedbackContainer.querySelector('.report-cancel-btn').addEventListener('click', renderFeedbackButtons);

                   feedbackContainer.querySelector('.report-submit-btn').addEventListener('click', async () => {
                     const feedbackText = input.value.trim();
                     if (!feedbackText) return;

                     feedbackContainer.innerHTML = `
                       <span class="feedback-success feedback-success--incorrect">
                         Report submitted. Thank you!
                       </span>
                     `;
                     try {
                       const reportRes = await fetch('/api/report', {
                         method: 'POST',
                         headers: { 'Content-Type': 'application/json' },
                         body: JSON.stringify({
                           question,
                           intent: currentIntent,
                           is_correct: false,
                           feedback: feedbackText
                         })
                       });
                       const repData = await reportRes.json();
                       if (repData && repData.correction_triggered) {
                         const notice = document.createElement("span");
                         notice.className = "feedback-correction-notice";
                         notice.textContent = "✨ Automatic correction applied to database query template based on user feedback.";
                         feedbackContainer.appendChild(notice);
                       }
                     } catch (e) {
                       console.error("Feedback error:", e);
                     }
                   });
                 });
               };

               renderFeedbackButtons();
               msgEl.querySelector('.msg-body').appendChild(feedbackContainer);
             }
           } catch (err) {
             answerThinkingEl.remove();
             msgEl.querySelector('.msg-body').insertAdjacentHTML('beforeend', `<div class="msg-bubble error-bubble">Failed to load summary.</div>`);
           }
           scrollToBottom();
        }
      }
    } catch (err) {
      thinkingEl.remove();
      appendMessage("error", "Connection error — please check that the server is running.");
    } finally {
      isProcessing = false;
      setStatus("online");
      askBtn.disabled = false;
      questionInput.focus();
      scrollToBottom();
    }
  }

  // ── Append a chat message ─────────────────────────────────────────
  function appendMessage(role, text, sql = null, options = null, tableData = null, insight = null, meta = null, queryType = null, explanation = null, trust = null, question = "") {
    const msg = document.createElement("div");
    msg.className = `msg msg--${role}`;

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = role === "user" ? "Y" : role === "error" ? "!" : "C";
    avatar.setAttribute("aria-hidden", "true");

    const body = document.createElement("div");
    body.className = "msg-body";

    if (text) {
      const bubble = document.createElement("div");
      bubble.className = "msg-bubble";
      bubble.textContent = text;
      body.appendChild(bubble);
    }

    // SQL collapsible toggle
    if (sql) {
      const toggle = document.createElement("div");
      toggle.className = "sql-toggle";

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "sql-toggle-btn";
      toggleBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 18 22 12 16 6"/><path d="M8 6 2 12 8 18"/></svg>
        View SQL Query
      `;

      const panel = document.createElement("div");
      panel.className = "sql-panel";

      const code = document.createElement("pre");
      code.className = "sql-code";
      code.innerHTML = highlightSQL(sql);
      panel.appendChild(code);

      toggleBtn.addEventListener("click", () => {
        const isOpen = panel.classList.toggle("open");
        toggleBtn.classList.toggle("open", isOpen);
        toggleBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 18 22 12 16 6"/><path d="M8 6 2 12 8 18"/></svg>
          ${isOpen ? "Hide SQL Query" : "View SQL Query"}
        `;
      });

      toggle.appendChild(toggleBtn);
      toggle.appendChild(panel);
      body.appendChild(toggle);
    }
    
    // SQL Data Table
    if (tableData && tableData.columns && tableData.columns.length > 0) {
      const tableWrapper = document.createElement("div");
      tableWrapper.className = "data-table-wrapper";
      const table = document.createElement("table");
      table.className = "data-table";
      
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      tableData.columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);
      
      const tbody = document.createElement("tbody");
      tableData.rows.forEach(row => {
        const tr = document.createElement("tr");
        row.forEach(cell => {
          const td = document.createElement("td");
          td.textContent = cell;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      tableWrapper.appendChild(table);
      body.appendChild(tableWrapper);

      appendInsightLayer(body, tableData, insight, meta, queryType, sql, explanation, trust, question, tableWrapper);
    }

    // Clarification options
    if (options && options.length > 0) {
      const optionsContainer = document.createElement("div");
      optionsContainer.className = "clarify-options";
      options.forEach((opt) => {
        const btn = document.createElement("button");
        btn.className = "clarify-btn";
        btn.textContent = opt;
        btn.addEventListener("click", () => {
          sendQuestion(opt);
          // Remove options after clicking
          optionsContainer.remove();
        });
        optionsContainer.appendChild(btn);
      });
      body.appendChild(optionsContainer);
    }

    msg.appendChild(avatar);
    msg.appendChild(body);
    messagesEl.appendChild(msg);
    scrollToBottom();
    
    return msg;
  }

  // ── Executive insight layer ──────────────────────────────────────
  function appendInsightLayer(body, tableData, insight, meta, queryType, sql, explanationInfo, trust, question, tableWrapper) {
    const layer = document.createElement("section");
    layer.className = "insight-layer";

    if (insight?.headline) {
      const card = document.createElement("div");
      card.className = "insight-card";
      card.innerHTML = `<span class="insight-eyebrow">EXECUTIVE INSIGHT</span><strong></strong><small></small>`;
      card.querySelector("strong").textContent = insight.headline;
      card.querySelector("small").textContent = `${insight.record_count || tableData.rows.length} records analysed · Data supported through 2026`;
      layer.appendChild(card);
    }

    const chartType = insight?.chart_type || (queryType === "trend" ? "line" : ["ranking", "comparison", "breakdown"].includes(queryType) ? "bar" : null);
    let chart = null;
    if (chartType) { chart = createMiniChart(tableData, chartType); layer.appendChild(chart); }

    const actions = document.createElement("div");
    actions.className = "result-actions";
    const exportBtn = document.createElement("button");
    exportBtn.className = "result-action";
    exportBtn.textContent = "Export CSV";
    exportBtn.addEventListener("click", () => exportCsv(tableData));
    actions.appendChild(exportBtn);
    const explainBtn = document.createElement("button");
    explainBtn.className = "result-action";
    explainBtn.textContent = "How was this calculated?";
    explainBtn.addEventListener("click", () => {
      const note = document.createElement("p");
      note.className = "calculation-note";
      const filters = explanationInfo?.filters || [];
      note.textContent = `Calculated from ${explanationInfo?.source || "Cokebot AI transaction data"}; filters: ${filters.join(", ") || "requested criteria"}. Assumptions: ${(explanationInfo?.assumptions || []).join(" ")}`;
      explainBtn.replaceWith(note);
    });
    actions.appendChild(explainBtn);
    if (chart) {
      const toggle = document.createElement("button");
      toggle.className = "result-action";
      toggle.textContent = "Chart only";
      toggle.addEventListener("click", () => {
        const tableVisible = !tableWrapper.classList.toggle("table-hidden");
        toggle.textContent = tableVisible ? "Chart only" : "Show table";
      });
      actions.appendChild(toggle);
    }
    const whatIf = document.createElement("button");
    whatIf.className = "result-action";
    whatIf.textContent = "What-if";
    whatIf.addEventListener("click", () => showWhatIf(layer, tableData));
    actions.appendChild(whatIf);
    const brief = document.createElement("button");
    brief.className = "result-action";
    brief.textContent = "CFO brief";
    brief.addEventListener("click", () => downloadBrief(question, insight, explanationInfo, trust, tableData));
    actions.appendChild(brief);
    const investigate = document.createElement("button");
    investigate.className = "result-action";
    investigate.textContent = "Why changed?";
    investigate.addEventListener("click", async () => {
      investigate.disabled = true; investigate.textContent = "Investigating…";
      try {
        const response = await fetch("/api/investigate", {method: "POST"});
        const result = await response.json();
        appendMessage("ai", result.answer, null, null, result.data, result.insight, null, result.query_type, result.explanation, null, "Root-cause investigation");
      } finally { investigate.disabled = false; investigate.textContent = "Why changed?"; }
    });
    actions.appendChild(investigate);
    const monitor = document.createElement("button");
    monitor.className = "result-action";
    monitor.textContent = "Save monitor";
    monitor.addEventListener("click", async () => {
      const threshold = window.prompt("Alert when reporting amount is greater than:");
      if (threshold === null || !Number.isFinite(Number(threshold))) return;
      const response = await fetch("/api/monitors", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name: question || "Saved insight", metric: "reporting_amount", operator: ">", threshold: Number(threshold)})});
      monitor.textContent = response.ok ? "Monitor saved" : "Could not save";
    });
    actions.appendChild(monitor);
    if (meta?.source) {
      const source = document.createElement("span");
      source.className = "result-meta";
      source.textContent = `${meta.source} · ${meta.latency_ms ?? "–"} ms`;
      actions.appendChild(source);
    }
    layer.appendChild(actions);
    body.appendChild(layer);
  }

  function showWhatIf(layer, tableData) {
    const current = layer.querySelector(".what-if-panel");
    if (current) return current.remove();
    const amount = tableData.rows.flat().map(Number).find(Number.isFinite);
    if (amount === undefined) return;
    const panel = document.createElement("div");
    panel.className = "what-if-panel";
    panel.innerHTML = `<label>Change assumption <input type="range" min="-20" max="20" value="0" step="1" /></label><strong></strong><small>Scenario only — it does not alter source data.</small>`;
    const slider = panel.querySelector("input"); const output = panel.querySelector("strong");
    const update = () => { const pct = Number(slider.value); output.textContent = `${pct >= 0 ? "+" : ""}${pct}% → ${(amount * (1 + pct / 100)).toLocaleString(undefined, {maximumFractionDigits: 2})}`; };
    slider.addEventListener("input", update); update(); layer.appendChild(panel);
  }

  function downloadBrief(question, insight, explanation, trust, tableData) {
    const body = `<h1>Cokebot AI CFO Brief</h1><h2>${question}</h2><p><b>Headline:</b> ${insight?.headline || "Financial insight"}</p><p><b>Confidence:</b> ${trust?.score || "—"}% (${trust?.basis || "validated data"})</p><p><b>Evidence:</b> ${tableData.rows.length} records returned.</p><p><b>Method:</b> ${explanation?.logic || "Direct transaction analysis"}</p><p><b>Recommended next action:</b> Review the leading driver and compare it with the prior period.</p>`;
    const url = URL.createObjectURL(new Blob([`<!doctype html><title>Cokebot AI CFO Brief</title>${body}`], {type: "text/html"}));
    const link = document.createElement("a"); link.href = url; link.download = "cokebot-ai-cfo-brief.html"; link.click(); URL.revokeObjectURL(url);
  }

  function createMiniChart(tableData, type) {
    const numericIndex = tableData.columns.findIndex((_, i) => tableData.rows.some(row => Number.isFinite(Number(row[i]))));
    if (numericIndex < 0) return document.createDocumentFragment();
    const points = tableData.rows.slice(0, 12).map((row, i) => ({
      label: String(row.find((cell, index) => index !== numericIndex && cell != null) ?? `Item ${i + 1}`).slice(0, 14),
      value: Number(row[numericIndex])
    })).filter(point => Number.isFinite(point.value));
    if (points.length < 2) return document.createDocumentFragment();
    const max = Math.max(...points.map(point => Math.abs(point.value)), 1);
    const chart = document.createElement("div");
    chart.className = `mini-chart mini-chart--${type}`;
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = `${tableData.columns[numericIndex].replaceAll("_", " ")} visualized`;
    chart.appendChild(title);
    const plot = document.createElement("div");
    plot.className = "chart-plot";
    points.forEach(point => {
      const item = document.createElement("div");
      item.className = "chart-item";
      const bar = document.createElement("i");
      bar.style.height = `${Math.max(6, (Math.abs(point.value) / max) * 100)}%`;
      bar.title = `${point.label}: ${point.value.toLocaleString()}`;
      const label = document.createElement("span");
      label.textContent = point.label;
      item.append(bar, label); plot.appendChild(item);
    });
    chart.appendChild(plot);
    return chart;
  }

  function exportCsv(tableData) {
    const escape = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const content = [tableData.columns, ...tableData.rows].map(row => row.map(escape).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = "cokebot-ai-financial-insight.csv"; link.click();
    URL.revokeObjectURL(url);
  }

  // ── Thinking indicator ────────────────────────────────────────────
  function appendThinking() {
    const el = document.createElement("div");
    el.className = "msg msg--ai thinking";
    el.innerHTML = `
      <div class="msg-avatar" aria-hidden="true">C</div>
      <div class="msg-body">
        <div class="msg-bubble" style="display:flex;align-items:center;gap:12px;">
          <img class="cola-loader" src="assets/can.jpeg" alt="" aria-hidden="true" />
          <span class="thinking-label">Analyzing your question…</span>
        </div>
      </div>
    `;
    messagesEl.appendChild(el);
    return el;
  }

  // ── SQL syntax highlighting (lightweight) ─────────────────────────
  function highlightSQL(sql) {
    const keywords = [
      "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "LIKE",
      "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AS",
      "GROUP", "BY", "ORDER", "ASC", "DESC", "HAVING",
      "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
      "COUNT", "SUM", "AVG", "MIN", "MAX", "DISTINCT",
      "CASE", "WHEN", "THEN", "ELSE", "END", "CAST",
      "BETWEEN", "IS", "NULL", "TOP", "LIMIT", "OFFSET",
      "UNION", "ALL", "EXISTS", "WITH", "NOLOCK", "INTERVAL",
      "DATE", "YEAR", "MONTH", "DAY", "DATEADD", "DATEDIFF",
      "GETDATE", "CURDATE", "DATE_FORMAT", "MAKEDATE", "QUARTER",
      "DATEFROMPARTS", "DATEPART", "CONCAT",
    ];

    let escaped = sql
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Highlight strings
    escaped = escaped.replace(/'([^']*)'/g, `<span class="str">'$1'</span>`);

    // Highlight numbers
    escaped = escaped.replace(/\b(\d+(?:\.\d+)?)\b/g, `<span class="num">$1</span>`);

    // Highlight keywords (case-insensitive)
    const kwRegex = new RegExp(`\\b(${keywords.join("|")})\\b`, "gi");
    escaped = escaped.replace(kwRegex, `<span class="kw">$&</span>`);

    return escaped;
  }

  // ── Status indicator ──────────────────────────────────────────────
  function setStatus(state) {
    if (state === "thinking") {
      statusDot.style.background = "var(--accent)";
      statusDot.style.boxShadow  = "0 0 6px var(--accent)";
      statusLabel.textContent    = "Thinking…";
    } else {
      statusDot.style.background = "var(--success)";
      statusDot.style.boxShadow  = "0 0 6px var(--success)";
      statusLabel.textContent    = "Online";
    }
  }

  // ── Scroll helper ─────────────────────────────────────────────────
  function scrollToBottom() {
    requestAnimationFrame(() => {
      chatArea.scrollTop = chatArea.scrollHeight;
    });
  }

  // ── Focus input on load ───────────────────────────────────────────
  questionInput.focus();
})();
