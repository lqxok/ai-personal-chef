const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

const messages = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const imageInput = document.querySelector("#imageInput");
const imagePreview = document.querySelector("#imagePreview");
const imageName = document.querySelector("#imageName");
const sendButton = document.querySelector("#sendButton");
const newChatButton = document.querySelector("#newChatButton");
const statusLine = document.querySelector("#status");

let threadId = localStorage.getItem("chef_thread_id") || crypto.randomUUID();
let previewUrl = null;
localStorage.setItem("chef_thread_id", threadId);


function removeWelcome() {
  document.querySelector("#welcome")?.remove();
}


function scrollToLatest() {
  messages.scrollTop = messages.scrollHeight;
}


function setStatus(message, state = "working") {
  statusLine.textContent = message;
  statusLine.dataset.state = state;
}


function appendInlineMarkdown(parent, text) {
  const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const token = match[0];
    const index = match.index ?? 0;

    if (index > cursor) {
      parent.append(document.createTextNode(text.slice(cursor, index)));
    }

    if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.append(strong);
    } else if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.append(code);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (linkMatch) {
        const link = document.createElement("a");
        link.textContent = linkMatch[1];
        link.href = linkMatch[2];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
      } else {
        parent.append(document.createTextNode(token));
      }
    }

    cursor = index + token.length;
  }

  if (cursor < text.length) {
    parent.append(document.createTextNode(text.slice(cursor)));
  }
}


function renderMarkdown(container, markdown) {
  container.replaceChildren();
  container.classList.add("markdown-body");

  let activeList = null;
  let activeParagraph = null;

  for (const rawLine of markdown.replace(/\r/g, "").split("\n")) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      activeList = null;
      activeParagraph = null;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = Math.min(headingMatch[1].length + 2, 6);
      const heading = document.createElement(`h${level}`);
      appendInlineMarkdown(heading, headingMatch[2]);
      container.append(heading);
      activeList = null;
      activeParagraph = null;
      continue;
    }

    if (/^(-{3,}|_{3,}|\*{3,})$/.test(trimmed)) {
      container.append(document.createElement("hr"));
      activeList = null;
      activeParagraph = null;
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (unorderedMatch || orderedMatch) {
      const listType = orderedMatch ? "ol" : "ul";
      if (!activeList || activeList.tagName.toLowerCase() !== listType) {
        activeList = document.createElement(listType);
        container.append(activeList);
      }
      const item = document.createElement("li");
      appendInlineMarkdown(item, (orderedMatch || unorderedMatch)[1]);
      activeList.append(item);
      activeParagraph = null;
      continue;
    }

    if (!activeParagraph) {
      activeParagraph = document.createElement("p");
      container.append(activeParagraph);
    } else {
      activeParagraph.append(document.createElement("br"));
    }
    appendInlineMarkdown(activeParagraph, trimmed);
    activeList = null;
  }
}


function addMessage(role, content) {
  removeWelcome();
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.dataset.role = role;

  if (role === "assistant") {
    renderMarkdown(article, content);
  } else {
    article.textContent = content;
  }

  messages.append(article);
  scrollToLatest();
  return article;
}


function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("图片读取失败，请重新选择"));
    reader.readAsDataURL(file);
  });
}


function validateImage(file) {
  if (!file) return;
  if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
    throw new Error("只支持 JPG、PNG 或 WebP 图片");
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new Error("图片不能超过 5 MB，请压缩后重试");
  }
}


function clearImageSelection() {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  imageInput.value = "";
  imagePreview.removeAttribute("src");
  imagePreview.hidden = true;
  imageName.textContent = "未选择图片";
}


imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  try {
    validateImage(file);
    if (!file) {
      clearImageSelection();
      return;
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    imagePreview.src = previewUrl;
    imagePreview.hidden = false;
    imageName.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    setStatus("图片已准备好，可以发送", "ready");
  } catch (error) {
    clearImageSelection();
    setStatus(error.message, "error");
  }
});


async function readSse(response, target) {
  if (!response.body) throw new Error("浏览器无法读取流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let renderQueued = false;

  const scheduleRender = () => {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => {
      renderMarkdown(target, answer);
      target.removeAttribute("data-empty");
      scrollToLatest();
      renderQueued = false;
    });
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";

    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const raw = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (!raw) continue;

      const data = JSON.parse(raw);
      if (event === "status") {
        setStatus(data.message, "working");
      } else if (event === "token") {
        answer += data.text;
        scheduleRender();
      } else if (event === "error") {
        throw new Error(data.message);
      } else if (event === "done") {
        renderMarkdown(target, answer);
        target.removeAttribute("data-empty");
      }
    }

    if (done) break;
  }

  return answer;
}


async function loadHistory() {
  try {
    const response = await fetch(`/api/v1/chat/messages?thread_id=${encodeURIComponent(threadId)}`);
    if (!response.ok) return;

    const history = await response.json();
    for (const message of history.messages) {
      addMessage(message.role, message.content);
    }
    if (history.messages.length) setStatus("已恢复上次会话", "ready");
  } catch {
    setStatus("历史记录暂时无法读取，不影响开始新对话", "error");
  }
}


form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (sendButton.disabled) return;

  const file = imageInput.files[0];
  const typedMessage = input.value.trim();
  const message = typedMessage || (file ? "请识别图片中可以确认的食材，并推荐三道适合的家常菜。" : "");
  let assistantTarget = null;

  if (!message) {
    setStatus("请先输入食材或选择一张图片", "error");
    input.focus();
    return;
  }

  try {
    validateImage(file);
    sendButton.disabled = true;
    input.disabled = true;
    imageInput.disabled = true;
    setStatus(file ? "正在读取图片……" : "正在发送需求……", "working");

    const imageData = file ? await fileToDataUrl(file) : null;
    const userDisplay = file ? `📷 ${file.name}\n${message}` : message;
    addMessage("user", userDisplay);
    assistantTarget = addMessage("assistant", "");
    assistantTarget.dataset.empty = "true";

    const response = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        thread_id: threadId,
        image_data: imageData,
      }),
    });

    if (!response.ok) {
      let detail = `请求失败（HTTP ${response.status}）`;
      try {
        const payload = await response.json();
        if (Array.isArray(payload.detail)) detail = payload.detail[0]?.msg || detail;
        else if (typeof payload.detail === "string") detail = payload.detail;
      } catch {
        // 响应不是 JSON 时使用通用错误信息。
      }
      throw new Error(detail);
    }

    await readSse(response, assistantTarget);
    input.value = "";
    clearImageSelection();
    setStatus("菜谱准备完成，祝你用餐愉快！", "done");
  } catch (error) {
    if (assistantTarget?.dataset.empty === "true") {
      renderMarkdown(assistantTarget, `**暂时无法生成菜谱：** ${error.message}`);
      assistantTarget.removeAttribute("data-empty");
    } else if (assistantTarget) {
      const note = document.createElement("p");
      note.className = "stream-error";
      note.textContent = `生成中断：${error.message}`;
      assistantTarget.append(note);
    }
    setStatus(error.message, "error");
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    imageInput.disabled = false;
    input.focus();
  }
});


newChatButton.addEventListener("click", async () => {
  newChatButton.disabled = true;
  try {
    await fetch(`/api/v1/chat/messages?thread_id=${encodeURIComponent(threadId)}`, {
      method: "DELETE",
    });
  } finally {
    localStorage.removeItem("chef_thread_id");
    location.reload();
  }
});


for (const button of document.querySelectorAll("[data-prompt]")) {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    input.focus();
  });
}


loadHistory();
