<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%!
    private String escapeHtml(Object value) {
        if (value == null) {
            return "";
        }
        return String.valueOf(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")
            .replace("'", "&#39;");
    }

    private String userInitials(String displayName) {
        if (displayName == null || displayName.trim().isEmpty()) {
            return "U";
        }
        String[] parts = displayName.trim().split("\\s+");
        StringBuilder initials = new StringBuilder();
        for (String part : parts) {
            if (!part.isEmpty() && initials.length() < 2) {
                initials.append(Character.toUpperCase(part.charAt(0)));
            }
        }
        return initials.length() == 0 ? "U" : initials.toString();
    }
%>
<%
    if ("john_roblox".equals(request.getParameter("test_user"))) {
        session.setAttribute("userId", Integer.valueOf(0));
        session.setAttribute("userDisplayName", "John Roblox");
        session.setAttribute("username", "john_roblox");
        session.setAttribute("userTier", "Free");
        session.setAttribute("temporaryUser", Boolean.TRUE);
        response.sendRedirect(request.getContextPath() + "/views/dashboard.jsp");
        return;
    }

    Object sessionUserId = session.getAttribute("userId");
    if (sessionUserId == null) {
        session.setAttribute("userId", Integer.valueOf(0));
        session.setAttribute("userDisplayName", "John Roblox");
        session.setAttribute("username", "john_roblox");
        session.setAttribute("userTier", "Free");
        session.setAttribute("temporaryUser", Boolean.TRUE);
        sessionUserId = Integer.valueOf(0);
    }

    int currentUserId;
    try {
        currentUserId = Integer.parseInt(String.valueOf(sessionUserId));
    } catch (NumberFormatException ignored) {
        currentUserId = 0;
    }

    String currentDisplayName = String.valueOf(
        session.getAttribute("userDisplayName") != null
            ? session.getAttribute("userDisplayName")
            : "John Roblox"
    );
    String currentTier = String.valueOf(
        session.getAttribute("userTier") != null
            ? session.getAttribute("userTier")
            : "Free"
    );
    boolean currentUserTemporary = Boolean.TRUE.equals(
        session.getAttribute("temporaryUser")
    );
    String currentInitials = userInitials(currentDisplayName);
%>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - RAGdoll AI Assistant</title>
    <link rel="stylesheet" href="../css/style.css?v=4">
</head>
<body class="dashboard-body">
    <div class="app-shell">
        <aside class="sidebar">
            <div class="sidebar-top">
                <h2 class="site-title">RAGdoll</h2>

                <button class="new-chat-btn" type="button">
                    <span class="left-icon" aria-hidden="true">○</span>
                    <span>New chat</span>
                    <span class="right-icon" aria-hidden="true">+</span>
                </button>

                <div class="past-chats">
                    <h3>Past Chats</h3>
                    <div id="past-chat-list">
                        <div class="chat-item">
                            <span class="gray-circle"></span>
                            <span>Loading conversations...</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="sidebar-bottom">
                <div class="user-profile" data-user-id="<%= currentUserId %>">
                    <div class="avatar"><%= escapeHtml(currentInitials) %></div>
                    <div class="user-info">
                        <div class="user-name"><%= escapeHtml(currentDisplayName) %></div>
                        <div class="user-tier">
                            <%= escapeHtml(currentTier) %>
                            <% if (currentUserTemporary) { %>
                                · Temporary (ID <%= currentUserId %>)
                            <% } else { %>
                                · ID <%= currentUserId %>
                            <% } %>
                        </div>
                    </div>
                </div>
            </div>
        </aside>

        <main class="main-area">
            <header class="top-nav">
                <div class="model-selector">
                    <select id="ai-model" name="ai-model" aria-label="Select AI model" disabled>
                        <option value="">Loading local models...</option>
                    </select>
                </div>
                <button class="upgrade-btn" type="button">Upgrade</button>
            </header>

            <section class="chat-container empty-state" id="chat-container" aria-label="Conversation">
                <div class="conversation" id="conversation" aria-live="polite">
                    <div class="welcome-state" id="welcome-state">
                        <div class="welcome-logo" aria-hidden="true">R</div>
                        <h1>How can I help you today?</h1>
                        <p>Choose a local model and start a conversation.</p>
                    </div>
                </div>
            </section>

            <footer class="input-container">
                <form class="input-box" id="query-form">
                    <button class="plus-btn" type="button" aria-label="Attach a document" title="Document upload is not connected yet">+</button>
                    <textarea
                        id="query-input"
                        name="query_text"
                        rows="1"
                        maxlength="8000"
                        placeholder="Message RAGdoll"
                        autocomplete="off"
                        required
                        disabled></textarea>
                    <button class="send-btn" id="send-btn" type="submit" aria-label="Send message" disabled>
                        <span aria-hidden="true">↑</span>
                    </button>
                </form>
                <p class="input-hint" id="input-hint">RAGdoll runs the selected GGUF model on your computer.</p>
            </footer>
        </main>
    </div>

    <script>
        const API_BASE_URL = window.RAGDOLL_API_URL || "http://127.0.0.1:8000";
        const userProfile = document.querySelector(".user-profile");
        const CURRENT_USER_ID = userProfile
            ? Number(userProfile.dataset.userId)
            : 0;
        let currentConversationId = null;
        const queryForm = document.getElementById("query-form");
        const queryInput = document.getElementById("query-input");
        const sendButton = document.getElementById("send-btn");
        const modelSelect = document.getElementById("ai-model");
        const chatContainer = document.getElementById("chat-container");
        const conversation = document.getElementById("conversation");
        const newChatButton = document.querySelector(".new-chat-btn");
        const pastChatList = document.getElementById("past-chat-list");
        const inputHint = document.getElementById("input-hint");

        function selectedModelLabel() {
            const selected = modelSelect.options[modelSelect.selectedIndex];
            return selected && selected.dataset.modelName
                ? selected.dataset.modelName
                : "RAGdoll";
        }

        function createWelcomeState() {
            const welcome = document.createElement("div");
            welcome.className = "welcome-state";
            welcome.id = "welcome-state";

            const logo = document.createElement("div");
            logo.className = "welcome-logo";
            logo.setAttribute("aria-hidden", "true");
            logo.textContent = "R";

            const heading = document.createElement("h1");
            heading.textContent = "How can I help you today?";

            const description = document.createElement("p");
            description.textContent = "Choose a local model and start a conversation.";

            welcome.append(logo, heading, description);
            return welcome;
        }

        function prepareChat() {
            chatContainer.classList.remove("empty-state");
            const welcomeState = document.getElementById("welcome-state");
            if (welcomeState) {
                welcomeState.remove();
            }
        }

        function appendInlineMarkdown(parent, text) {
            const tokenPattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
            let lastIndex = 0;
            let match;

            while ((match = tokenPattern.exec(text)) !== null) {
                if (match.index > lastIndex) {
                    parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
                }

                const token = match[0];
                if (token.startsWith("**")) {
                    const strong = document.createElement("strong");
                    strong.textContent = token.slice(2, -2);
                    parent.appendChild(strong);
                } else if (token.startsWith("`")) {
                    const code = document.createElement("code");
                    code.textContent = token.slice(1, -1);
                    parent.appendChild(code);
                } else {
                    const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
                    if (linkMatch) {
                        const link = document.createElement("a");
                        link.textContent = linkMatch[1];
                        link.href = linkMatch[2];
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        parent.appendChild(link);
                    } else {
                        parent.appendChild(document.createTextNode(token));
                    }
                }
                lastIndex = tokenPattern.lastIndex;
            }

            if (lastIndex < text.length) {
                parent.appendChild(document.createTextNode(text.slice(lastIndex)));
            }
        }

        function renderMarkdown(container, text) {
            const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
            let paragraphLines = [];
            let activeList = null;
            let activeListType = "";
            let codeLines = [];
            let inCodeBlock = false;
            let codeLanguage = "";

            function flushParagraph() {
                if (paragraphLines.length === 0) {
                    return;
                }
                const paragraph = document.createElement("p");
                paragraphLines.forEach(function (line, index) {
                    if (index > 0) {
                        paragraph.appendChild(document.createElement("br"));
                    }
                    appendInlineMarkdown(paragraph, line);
                });
                container.appendChild(paragraph);
                paragraphLines = [];
            }

            function flushList() {
                activeList = null;
                activeListType = "";
            }

            function flushCode() {
                const pre = document.createElement("pre");
                const code = document.createElement("code");
                if (codeLanguage) {
                    code.dataset.language = codeLanguage;
                }
                code.textContent = codeLines.join("\n");
                pre.appendChild(code);
                container.appendChild(pre);
                codeLines = [];
                codeLanguage = "";
            }

            lines.forEach(function (line) {
                const fenceMatch = line.match(/^```\s*([^\s`]*)\s*$/);
                if (fenceMatch) {
                    flushParagraph();
                    flushList();
                    if (inCodeBlock) {
                        flushCode();
                        inCodeBlock = false;
                    } else {
                        inCodeBlock = true;
                        codeLanguage = fenceMatch[1] || "";
                    }
                    return;
                }

                if (inCodeBlock) {
                    codeLines.push(line);
                    return;
                }

                if (!line.trim()) {
                    flushParagraph();
                    flushList();
                    return;
                }

                const headingMatch = line.match(/^([#]{1,3})\s+(.+)$/);
                if (headingMatch) {
                    flushParagraph();
                    flushList();
                    const heading = document.createElement("h" + String(headingMatch[1].length + 2));
                    appendInlineMarkdown(heading, headingMatch[2]);
                    container.appendChild(heading);
                    return;
                }

                const unorderedMatch = line.match(/^\s*[-*]\s+(.+)$/);
                const orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
                if (unorderedMatch || orderedMatch) {
                    flushParagraph();
                    const listType = orderedMatch ? "ol" : "ul";
                    if (!activeList || activeListType !== listType) {
                        flushList();
                        activeList = document.createElement(listType);
                        activeListType = listType;
                        container.appendChild(activeList);
                    }
                    const item = document.createElement("li");
                    appendInlineMarkdown(item, (orderedMatch || unorderedMatch)[1]);
                    activeList.appendChild(item);
                    return;
                }

                const quoteMatch = line.match(/^>\s?(.+)$/);
                if (quoteMatch) {
                    flushParagraph();
                    flushList();
                    const quote = document.createElement("blockquote");
                    appendInlineMarkdown(quote, quoteMatch[1]);
                    container.appendChild(quote);
                    return;
                }

                flushList();
                paragraphLines.push(line);
            });

            flushParagraph();
            if (inCodeBlock || codeLines.length > 0) {
                flushCode();
            }
        }

        function addMessage(role, text, extraClass, assistantLabel) {
            prepareChat();

            const message = document.createElement("article");
            message.className = "message message-" + role + (extraClass ? " " + extraClass : "");

            const inner = document.createElement("div");
            inner.className = "message-inner";

            if (role === "assistant") {
                const avatar = document.createElement("div");
                avatar.className = "message-avatar";
                avatar.setAttribute("aria-hidden", "true");
                avatar.textContent = "R";
                inner.appendChild(avatar);
            }

            const body = document.createElement("div");
            body.className = "message-body";

            const label = document.createElement("div");
            label.className = "message-label";
            label.textContent = role === "user"
                ? "You"
                : (assistantLabel || selectedModelLabel());

            const bubble = document.createElement("div");
            bubble.className = "message-bubble";
            renderMarkdown(bubble, text);

            body.append(label, bubble);
            inner.appendChild(body);
            message.appendChild(inner);
            conversation.appendChild(message);
            chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: "smooth" });
            return message;
        }

        function addLoadingMessage() {
            prepareChat();

            const message = document.createElement("article");
            message.className = "message message-assistant loading-message";

            const inner = document.createElement("div");
            inner.className = "message-inner";

            const avatar = document.createElement("div");
            avatar.className = "message-avatar";
            avatar.setAttribute("aria-hidden", "true");
            avatar.textContent = "R";

            const body = document.createElement("div");
            body.className = "message-body";

            const label = document.createElement("div");
            label.className = "message-label";
            label.textContent = selectedModelLabel();

            const dots = document.createElement("div");
            dots.className = "typing-indicator";
            dots.setAttribute("aria-label", "Generating response");
            dots.innerHTML = "<span></span><span></span><span></span>";

            body.append(label, dots);
            inner.append(avatar, body);
            message.appendChild(inner);
            conversation.appendChild(message);
            chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: "smooth" });
            return message;
        }

        function setComposerEnabled(enabled) {
            queryInput.disabled = !enabled;
            sendButton.disabled = !enabled;
            modelSelect.disabled = !enabled;
        }

        function resizeComposer() {
            queryInput.style.height = "auto";
            queryInput.style.height = Math.min(queryInput.scrollHeight, 180) + "px";
        }

        function wait(milliseconds) {
            return new Promise(function (resolve) {
                window.setTimeout(resolve, milliseconds);
            });
        }

        function setActiveConversation(conversationId) {
            document.querySelectorAll(".chat-item[data-conversation-id]").forEach(function (item) {
                item.classList.toggle(
                    "active",
                    Number(item.dataset.conversationId) === Number(conversationId)
                );
            });
        }

        async function loadPastChats(activeConversationId) {
            try {
                const response = await fetch(
                    API_BASE_URL + "/api/conversations?user_id=" + encodeURIComponent(CURRENT_USER_ID),
                    { cache: "no-store" }
                );
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || "Unable to load conversations.");
                }

                pastChatList.replaceChildren();
                const conversations = Array.isArray(result.conversations)
                    ? result.conversations
                    : [];

                if (conversations.length === 0) {
                    const emptyItem = document.createElement("div");
                    emptyItem.className = "chat-item";
                    emptyItem.textContent = "No saved chats yet";
                    pastChatList.appendChild(emptyItem);
                    return;
                }

                conversations.forEach(function (savedConversation) {
                    const item = document.createElement("div");
                    item.className = "chat-item";
                    item.dataset.conversationId = String(savedConversation.conversation_id);

                    const dot = document.createElement("span");
                    dot.className = "gray-circle";

                    const title = document.createElement("span");
                    title.textContent = savedConversation.title || "Saved conversation";

                    item.append(dot, title);
                    item.addEventListener("click", function () {
                        openConversation(Number(savedConversation.conversation_id));
                    });
                    pastChatList.appendChild(item);
                });

                setActiveConversation(activeConversationId || currentConversationId);
            } catch (error) {
                pastChatList.replaceChildren();
                const errorItem = document.createElement("div");
                errorItem.className = "chat-item";
                errorItem.textContent = "Conversation history unavailable";
                errorItem.title = error.message;
                pastChatList.appendChild(errorItem);
            }
        }

        async function openConversation(conversationId) {
            setComposerEnabled(false);
            inputHint.textContent = "Loading saved conversation...";

            try {
                const response = await fetch(
                    API_BASE_URL + "/api/conversations/" + encodeURIComponent(conversationId) +
                    "?user_id=" + encodeURIComponent(CURRENT_USER_ID),
                    { cache: "no-store" }
                );
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || "Unable to load the conversation.");
                }

                currentConversationId = Number(result.conversation_id);
                conversation.replaceChildren();
                chatContainer.classList.remove("empty-state");

                const messages = Array.isArray(result.messages) ? result.messages : [];
                if (messages.length === 0) {
                    conversation.appendChild(createWelcomeState());
                    chatContainer.classList.add("empty-state");
                } else {
                    messages.forEach(function (message) {
                        addMessage(
                            message.role,
                            message.text || "",
                            "",
                            message.model_name || "RAGdoll"
                        );
                    });
                }

                setActiveConversation(currentConversationId);
                inputHint.textContent = "Saved conversation loaded. New messages will use its history.";
            } catch (error) {
                addMessage(
                    "assistant",
                    "**Unable to load the saved conversation.**\n\n" + error.message,
                    "error-message"
                );
                inputHint.textContent = "The saved conversation could not be loaded.";
            } finally {
                setComposerEnabled(modelSelect.options.length > 0 && Boolean(modelSelect.value));
                queryInput.focus();
            }
        }

        async function fetchModelsWithStartupRetry() {
            const maximumAttempts = 15;
            let lastError = new Error("The local model service did not start.");

            for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
                try {
                    const response = await fetch(API_BASE_URL + "/api/models", {
                        cache: "no-store"
                    });
                    const result = await response.json();
                    if (!response.ok) {
                        throw new Error(result.detail || "Unable to load local models.");
                    }
                    return result;
                } catch (error) {
                    lastError = error;
                    if (attempt < maximumAttempts) {
                        inputHint.textContent = "Starting the local model service...";
                        await wait(1000);
                    }
                }
            }

            throw lastError;
        }

        async function loadAvailableModels() {
            setComposerEnabled(false);
            inputHint.textContent = "Starting the local model service...";

            try {
                const result = await fetchModelsWithStartupRetry();

                modelSelect.replaceChildren();
                const models = Array.isArray(result.models) ? result.models : [];

                if (models.length === 0) {
                    const option = document.createElement("option");
                    option.value = "";
                    option.textContent = "No GGUF models found";
                    modelSelect.appendChild(option);
                    queryInput.placeholder = "Add a .gguf file to models/models";
                    inputHint.textContent = "No model was found in models/models.";
                    return;
                }

                models.forEach(function (model) {
                    const option = document.createElement("option");
                    option.value = model.file_name;
                    option.textContent = model.model_name + " - Local";
                    option.dataset.modelName = model.model_name;
                    if (model.model_id !== null && model.model_id !== undefined) {
                        option.dataset.modelId = String(model.model_id);
                    }
                    modelSelect.appendChild(option);
                });

                setComposerEnabled(true);
                queryInput.placeholder = "Message RAGdoll";
                inputHint.textContent = "RAGdoll runs the selected GGUF model on your computer.";
                queryInput.focus();
            } catch (error) {
                modelSelect.replaceChildren();
                const option = document.createElement("option");
                option.value = "";
                option.textContent = "Local model service unavailable";
                modelSelect.appendChild(option);
                queryInput.placeholder = "Local model service unavailable";
                inputHint.textContent = "Tomcat could not connect to the local API at " + API_BASE_URL + ".";
                addMessage(
                    "assistant",
                    "**Unable to connect to the local model service.**\n\n" +
                    error.message + "\n\nCheck `logs/local_query.log`. You can still use `run_local_query.bat` as a manual fallback.",
                    "error-message"
                );
            }
        }

        queryInput.addEventListener("input", resizeComposer);
        queryInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (!sendButton.disabled) {
                    queryForm.requestSubmit();
                }
            }
        });

        queryForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            const prompt = queryInput.value.trim();
            const selectedOption = modelSelect.options[modelSelect.selectedIndex];
            if (!prompt || !selectedOption || !selectedOption.value || sendButton.disabled) {
                return;
            }

            addMessage("user", prompt);
            queryInput.value = "";
            resizeComposer();
            setComposerEnabled(false);
            inputHint.textContent = "Generating a response locally...";
            const loadingMessage = addLoadingMessage();

            try {
                const requestBody = {
                    query_text: prompt,
                    user_id: CURRENT_USER_ID,
                    model_file: selectedOption.value,
                    max_tokens: 512
                };
                if (currentConversationId !== null) {
                    requestBody.conversation_id = currentConversationId;
                }
                if (selectedOption.dataset.modelId) {
                    requestBody.model_id = Number(selectedOption.dataset.modelId);
                }

                const response = await fetch(API_BASE_URL + "/api/query", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(requestBody)
                });

                let result = {};
                try {
                    result = await response.json();
                } catch (ignored) {
                    result = {};
                }

                if (!response.ok) {
                    throw new Error(result.detail || "The local model service returned an error.");
                }

                loadingMessage.remove();
                addMessage(
                    "assistant",
                    result.response_text || "No response was returned.",
                    "",
                    result.model_name || selectedModelLabel()
                );

                if (result.conversation_id !== null && result.conversation_id !== undefined) {
                    currentConversationId = Number(result.conversation_id);
                    await loadPastChats(currentConversationId);
                }

                if (result.conversation_saved === false) {
                    inputHint.textContent = "Response generated, but MySQL could not save this turn: " +
                        (result.conversation_error || "unknown database error");
                } else {
                    const rememberedTurns = Number(result.remembered_turn_count || 0);
                    const memoryMessage = rememberedTurns > 0
                        ? " Used " + rememberedTurns +
                          (rememberedTurns === 1 ? " previous turn." : " previous turns.")
                        : " This is the first saved turn in this conversation.";

                    inputHint.textContent = result.elapsed_seconds !== undefined
                        ? "Saved and generated locally in " + result.elapsed_seconds +
                          " seconds." + memoryMessage
                        : "Conversation saved in MySQL." + memoryMessage;
                }
            } catch (error) {
                loadingMessage.remove();
                addMessage(
                    "assistant",
                    "**Unable to query the selected model.**\n\n" + error.message,
                    "error-message"
                );
                inputHint.textContent = "The last request failed. Check the local API terminal for details.";
            } finally {
                setComposerEnabled(true);
                queryInput.focus();
            }
        });

        newChatButton.addEventListener("click", function () {
            currentConversationId = null;
            setActiveConversation(null);
            conversation.replaceChildren(createWelcomeState());
            chatContainer.classList.add("empty-state");
            queryInput.value = "";
            resizeComposer();
            inputHint.textContent = "RAGdoll runs the selected GGUF model on your computer.";
            if (!queryInput.disabled) {
                queryInput.focus();
            }
        });

        loadAvailableModels().then(function () {
            loadPastChats(null);
        });
    </script>
</body>
</html>