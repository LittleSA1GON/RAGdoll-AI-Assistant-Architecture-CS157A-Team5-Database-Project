<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Dashboard - RAGdoll AI Assistant</title>
    <link rel="stylesheet" href="../css/style.css">
</head>
<body>
    <div class="app-shell">
        <aside class="sidebar">
            <div class="sidebar-top">
                <h2 class="site-title">RAGdoll</h2>
                
                <button class="new-chat-btn">
                    <span class="left-icon">○</span> New chat
                    <span class="right-icon">+</span>
                </button>
                
                <div class="past-chats">
                    <h3>Past Chats</h3>
                    <div class="chat-item active">
                        <span class="gray-circle"></span> Default Chat
                    </div>
                </div>
            </div>
            
            <div class="sidebar-bottom">
                <div class="user-profile">
                    <div class="avatar">JR</div>
                    <div class="user-info">
                        <div class="user-name">John Roblox</div>
                        <div class="user-tier">Free</div>
                    </div>
                </div>
            </div>
        </aside>
        
        <main class="main-area">
            <header class="top-nav">
                <div class="model-selector">
                    <select id="ai-model" name="ai-model" disabled>
                        <option value="">Loading local models...</option>
                    </select>
                </div>
                <button class="upgrade-btn">Upgrade</button>
            </header>

            <div class="chat-container empty-state" id="chat-container" aria-live="polite">
                <div id="welcome-state" style="max-width: 500px;">
                    <div style="font-size: 56px; margin-bottom: 16px;">✨</div>
                    <h2 style="font-size: 28px; font-weight: 700; margin-bottom: 12px; color: #1f2937;">Welcome to RAGdoll AI</h2>
                    <p style="font-size: 16px; color: #6b7280; margin-bottom: 32px; line-height: 1.6;">
                        Explore powerful AI conversations. Start by typing your question below or select a model from the dropdown.
                    </p>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 20px; background: rgba(99, 102, 241, 0.05); border-radius: 12px; border: 1px solid rgba(99, 102, 241, 0.1);">
                        <div style="text-align: center;">
                            <div style="font-size: 32px; margin-bottom: 8px;">🚀</div>
                            <div style="font-size: 13px; font-weight: 600; color: #1f2937;">Quick Start</div>
                            <div style="font-size: 12px; color: #6b7280; margin-top: 4px;">Begin a new conversation</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 32px; margin-bottom: 8px;">⚙️</div>
                            <div style="font-size: 13px; font-weight: 600; color: #1f2937;">Select Model</div>
                            <div style="font-size: 12px; color: #6b7280; margin-top: 4px;">Choose your AI</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="input-container">
                <form class="input-box" id="query-form">
                    <span class="plus-btn">+</span>
                    <input id="query-input" name="query_text" type="text" placeholder="Type here" autocomplete="off" required disabled />
                    <button class="send-btn" id="send-btn" type="submit" aria-label="Send query" disabled>↑</button>
                </form>
            </div>
        </main>
    </div>

    <script>
        const API_BASE_URL = window.RAGDOLL_API_URL || "http://127.0.0.1:8000";
        const queryForm = document.getElementById("query-form");
        const queryInput = document.getElementById("query-input");
        const sendButton = document.getElementById("send-btn");
        const modelSelect = document.getElementById("ai-model");
        const chatContainer = document.getElementById("chat-container");
        const newChatButton = document.querySelector(".new-chat-btn");
        const welcomeState = document.getElementById("welcome-state");

        function selectedModelLabel() {
            const selected = modelSelect.options[modelSelect.selectedIndex];
            return selected && selected.dataset.modelName
                ? selected.dataset.modelName
                : "Local model";
        }

        function prepareChat() {
            chatContainer.classList.remove("empty-state");
            if (welcomeState && welcomeState.parentNode) {
                welcomeState.remove();
            }
        }

        function addMessage(role, text, extraClass) {
            prepareChat();

            const row = document.createElement("div");
            row.className = "message-row " + role + (extraClass ? " " + extraClass : "");

            const label = document.createElement("div");
            label.className = "message-label";
            label.textContent = role === "user" ? "You" : selectedModelLabel();

            const bubble = document.createElement("div");
            bubble.className = "message-bubble";
            bubble.textContent = text;

            row.appendChild(label);
            row.appendChild(bubble);
            chatContainer.appendChild(row);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            return row;
        }

        async function loadAvailableModels() {
            modelSelect.disabled = true;
            queryInput.disabled = true;
            sendButton.disabled = true;

            try {
                const response = await fetch(API_BASE_URL + "/api/models");
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || "Unable to load local models.");
                }

                modelSelect.replaceChildren();
                const models = Array.isArray(result.models) ? result.models : [];

                if (models.length === 0) {
                    const option = document.createElement("option");
                    option.value = "";
                    option.textContent = "No GGUF models found";
                    modelSelect.appendChild(option);
                    queryInput.placeholder = "Add a .gguf file to models/models";
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

                modelSelect.disabled = false;
                queryInput.disabled = false;
                sendButton.disabled = false;
                queryInput.placeholder = "Type here";
                queryInput.focus();
            } catch (error) {
                modelSelect.replaceChildren();
                const option = document.createElement("option");
                option.value = "";
                option.textContent = "Local model service unavailable";
                modelSelect.appendChild(option);
                queryInput.placeholder = "Start local_query.py first";
                addMessage(
                    "assistant",
                    "Unable to load models: " + error.message +
                    ". Start src/rag_pipeline/local_query.py and try again.",
                    "error-message"
                );
            }
        }

        queryForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            const prompt = queryInput.value.trim();
            const selectedOption = modelSelect.options[modelSelect.selectedIndex];
            if (!prompt || !selectedOption || !selectedOption.value || sendButton.disabled) {
                return;
            }

            addMessage("user", prompt);
            queryInput.value = "";
            queryInput.disabled = true;
            sendButton.disabled = true;
            modelSelect.disabled = true;
            const loadingRow = addMessage("assistant", "Generating response...", "loading-message");

            try {
                const requestBody = {
                    query_text: prompt,
                    model_file: selectedOption.value,
                    max_tokens: 256
                };
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

                loadingRow.remove();
                addMessage("assistant", result.response_text || "No response was returned.");
            } catch (error) {
                loadingRow.remove();
                addMessage(
                    "assistant",
                    "Unable to query the selected model: " + error.message,
                    "error-message"
                );
            } finally {
                queryInput.disabled = false;
                sendButton.disabled = false;
                modelSelect.disabled = false;
                queryInput.focus();
            }
        });

        newChatButton.addEventListener("click", function () {
            window.location.reload();
        });

        loadAvailableModels();
    </script>
</body>
</html>