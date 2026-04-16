(function () {
  const API_BASE_URL = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "http://127.0.0.1:8000";

  const els = {
    messages: document.getElementById("messages"),
    textarea: document.getElementById("messageInput"),
    sendBtn: document.getElementById("sendBtn"),
    navProfile: document.getElementById("navProfile"),
    navEcommerce: document.getElementById("navEcommerce"),
    taskChips: document.getElementById("taskChips"),
    chipCopywriting: document.getElementById("chipCopywriting"),
    chipReview: document.getElementById("chipReview"),
  };

  let currentAgent = "profile";
  let currentTask = "copywriting";
  let messages = [];
  let sending = false;
  let msgId = 0;

  function scrollMessagesToBottom() {
    els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
  }

  function getQuickPrompts() {
    return currentAgent === "ecommerce"
      ? ["你能做什么？", "帮我写一段商品标题和核心卖点", "分析评论：发货有点慢，质量还不错。"]
      : ["你能做什么？", "帮我分析一下", "介绍一下自己"];
  }

  function emptyStateIconSvg() {
    return `<svg class="empty-state-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function updateSendButtonState() {
    const hasText = els.textarea.value.trim().length > 0;
    els.sendBtn.disabled = sending || !hasText;
    els.sendBtn.innerHTML = sending
      ? '<span class="spinner" aria-hidden="true"></span>'
      : '<svg class="icon-send" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  function renderMessages() {
    els.messages.innerHTML = "";
    if (messages.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const prompts = getQuickPrompts()
        .map((p) => `<button type="button" class="quick-prompt" data-prompt="${escapeAttr(p)}">${escapeHtml(p)}</button>`)
        .join("");
      empty.innerHTML = `
        <div class="empty-state-icon">${emptyStateIconSvg()}</div>
        <p class="empty-state-title">开始对话</p>
        <p class="empty-state-desc">选择左侧智能体，输入消息，或点击下方示例快速开始。</p>
        <div class="quick-prompts">${prompts}</div>
      `;
      els.messages.appendChild(empty);
      return;
    }

    for (const m of messages) {
      const wrap = document.createElement("div");
      wrap.className = `msg msg--${m.role}${m.error ? " msg-error" : ""}`;
      wrap.dataset.id = m.id;

      const bubble = document.createElement("div");
      bubble.className = "msg-bubble";

      if (m.role === "user") bubble.textContent = m.content;
      else if (m.thinking) {
        bubble.innerHTML = `
          <div class="thinking">
            <span>思考中</span>
            <span class="thinking-dots" aria-hidden="true"><span></span><span></span><span></span></span>
          </div>
          <div class="skeleton-block" style="margin-top:14px;width:92%"></div>
          <div class="skeleton-block" style="width:68%"></div>
        `;
      } else if (m.streaming) {
        const div = document.createElement("div");
        div.className = "md-content stream-plain";
        div.style.whiteSpace = "pre-wrap";
        div.textContent = m.content || "";
        bubble.appendChild(div);
      } else {
        const div = document.createElement("div");
        div.className = "md-content";
        div.innerHTML = DOMPurify.sanitize(marked.parse(m.content || "", { breaks: true, gfm: true }));
        bubble.appendChild(div);
        div.querySelectorAll("pre code").forEach((block) => hljs.highlightElement(block));
        enhanceCodeBlocks(div);
      }

      wrap.appendChild(bubble);
      els.messages.appendChild(wrap);
    }
    scrollMessagesToBottom();
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function enhanceCodeBlocks(root) {
    root.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".copy-btn")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "复制";
      btn.addEventListener("click", async () => {
        const code = pre.querySelector("code");
        const t = code ? code.innerText : "";
        try {
          await navigator.clipboard.writeText(t);
          btn.textContent = "已复制";
          setTimeout(() => (btn.textContent = "复制"), 1600);
        } catch {
          btn.textContent = "失败";
          setTimeout(() => (btn.textContent = "复制"), 1600);
        }
      });
      pre.style.position = "relative";
      pre.appendChild(btn);
    });
  }

  function updateAssistantStreamDom(assistantId, text) {
    const wrap = els.messages.querySelector(`[data-id="${assistantId}"]`);
    if (!wrap) return;
    const bubble = wrap.querySelector(".msg-bubble");
    if (!bubble) return;
    let div = bubble.querySelector(".stream-plain");
    if (!div) {
      bubble.innerHTML = "";
      div = document.createElement("div");
      div.className = "md-content stream-plain";
      div.style.whiteSpace = "pre-wrap";
      bubble.appendChild(div);
    }
    div.textContent = text;
    scrollMessagesToBottom();
  }

  async function consumeChatStream(response, assistantId) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let assembled = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      while (true) {
        const sep = buffer.indexOf("\n\n");
        if (sep === -1) break;
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        for (const line of block.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const raw = trimmed.slice(5).trim();
          if (raw === "[DONE]") return assembled;
          let obj;
          try {
            obj = JSON.parse(raw);
          } catch {
            continue;
          }
          if (obj.error) throw new Error(String(obj.error));
          if (typeof obj.d === "string" && obj.d.length) {
            assembled += obj.d;
            const m = messages.find((x) => x.id === assistantId);
            if (m) {
              m.thinking = false;
              m.streaming = true;
              m.content = assembled;
            }
            updateAssistantStreamDom(assistantId, assembled);
          }
        }
      }
    }
    return assembled;
  }

  function setNavActive() {
    const isEcommerce = currentAgent === "ecommerce";
    els.navProfile.classList.toggle("active", !isEcommerce);
    els.navEcommerce.classList.toggle("active", isEcommerce);
    els.navProfile.setAttribute("aria-pressed", (!isEcommerce).toString());
    els.navEcommerce.setAttribute("aria-pressed", isEcommerce.toString());
    els.taskChips.hidden = !isEcommerce;
    els.chipCopywriting.classList.toggle("active", currentTask === "copywriting");
    els.chipReview.classList.toggle("active", currentTask === "review_analysis");
    els.textarea.placeholder =
      isEcommerce
        ? "输入商品信息或评论内容… Enter 发送，Shift+Enter 换行"
        : "输入消息… Enter 发送，Shift+Enter 换行";
  }

  function switchAgent(agent) {
    if (agent === currentAgent) return;
    els.messages.classList.add("messages--fade");
    setTimeout(() => {
      currentAgent = agent;
      messages = [];
      msgId = 0;
      setNavActive();
      renderMessages();
      els.messages.classList.remove("messages--fade");
    }, 220);
  }

  async function sendMessage(presetText) {
    const raw = presetText !== undefined && presetText !== null ? presetText : els.textarea.value;
    const text = String(raw).trim();
    if (!text || sending) return;

    const agent = currentAgent;
    const task = agent === "ecommerce" ? currentTask : "general";

    sending = true;
    updateSendButtonState();
    els.textarea.value = "";
    onTextareaInput();

    const userId = ++msgId;
    const assistantId = ++msgId;
    messages.push({ id: userId, role: "user", content: text });
    messages.push({ id: assistantId, role: "assistant", thinking: true });
    renderMessages();

    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent, task, message: text }),
      });

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const errBody = await response.json();
          if (errBody.detail) detail = String(errBody.detail);
        } catch {
          try { detail = await response.text(); } catch {}
        }
        const m = messages.find((x) => x.id === assistantId);
        if (m) {
          m.thinking = false;
          m.streaming = false;
          m.content = `请求失败：${detail}`;
          m.error = true;
        }
        renderMessages();
        return;
      }

      const reply = await consumeChatStream(response, assistantId);
      const m = messages.find((x) => x.id === assistantId);
      if (m) {
        m.thinking = false;
        m.streaming = false;
        m.content = reply || "（空回复）";
      }
      renderMessages();
    } catch (err) {
      const m = messages.find((x) => x.id === assistantId);
      if (m) {
        m.thinking = false;
        m.streaming = false;
        m.content = `网络错误：${err.message || err}`;
        m.error = true;
      }
      renderMessages();
    } finally {
      sending = false;
      updateSendButtonState();
    }
  }

  function onTextareaInput() {
    els.textarea.style.height = "auto";
    els.textarea.style.height = Math.min(els.textarea.scrollHeight, 200) + "px";
    updateSendButtonState();
  }

  els.messages.addEventListener("click", (e) => {
    const btn = e.target.closest(".quick-prompt");
    if (!btn || sending) return;
    const prompt = btn.getAttribute("data-prompt");
    if (prompt) sendMessage(prompt);
  });

  els.navProfile.addEventListener("click", () => switchAgent("profile"));
  els.navEcommerce.addEventListener("click", () => switchAgent("ecommerce"));
  els.chipCopywriting.addEventListener("click", () => { currentTask = "copywriting"; setNavActive(); renderMessages(); });
  els.chipReview.addEventListener("click", () => { currentTask = "review_analysis"; setNavActive(); renderMessages(); });
  els.sendBtn.addEventListener("click", () => sendMessage());
  els.textarea.addEventListener("input", onTextareaInput);
  els.textarea.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });

  setNavActive();
  renderMessages();
  updateSendButtonState();
})();
