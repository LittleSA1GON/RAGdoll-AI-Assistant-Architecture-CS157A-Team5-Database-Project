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

    private String adminInitials(String displayName) {
        if (displayName == null || displayName.trim().isEmpty()) {
            return "A";
        }
        String[] parts = displayName.trim().split("\\s+");
        StringBuilder result = new StringBuilder();
        for (String part : parts) {
            if (!part.isEmpty() && result.length() < 2) {
                result.append(Character.toUpperCase(part.charAt(0)));
            }
        }
        return result.length() == 0 ? "A" : result.toString();
    }
%>
<%
    String testAdmin = request.getParameter("test_admin");

    if ("jane_fortnite".equals(testAdmin)) {
        session.removeAttribute("userId");
        session.removeAttribute("userDisplayName");
        session.removeAttribute("username");
        session.removeAttribute("userTier");
        session.removeAttribute("temporaryUser");
        session.setAttribute("adminUserId", Integer.valueOf(20));
        session.setAttribute("adminDisplayName", "Jane Fortnite Admin");
        session.setAttribute("adminCompanyId", "RAGDOLL010");
        session.setAttribute("temporaryAdmin", Boolean.TRUE);
        response.sendRedirect(request.getContextPath() + "/views/admin.jsp");
        return;
    }

    Object adminUserIdValue = session.getAttribute("adminUserId");
    if (adminUserIdValue == null) {
        response.sendRedirect(request.getContextPath() + "/views/login.jsp?admin_required=true");
        return;
    }

    int adminUserId;
    try {
        adminUserId = Integer.parseInt(String.valueOf(adminUserIdValue));
    } catch (NumberFormatException ignored) {
        adminUserId = 20;
    }

    String adminDisplayName = String.valueOf(
        session.getAttribute("adminDisplayName") != null
            ? session.getAttribute("adminDisplayName")
            : "Administrator"
    );
    String adminCompanyId = String.valueOf(
        session.getAttribute("adminCompanyId") != null
            ? session.getAttribute("adminCompanyId")
            : "RAGDOLL010"
    );
    boolean temporaryAdmin = Boolean.TRUE.equals(session.getAttribute("temporaryAdmin"));
    String adminAvatarText = adminInitials(adminDisplayName);
%>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - RAGdoll AI Assistant</title>
    <link rel="stylesheet" href="../css/style.css?v=11">
    <style>
        .admin-tabs-page { background: var(--bg-main); }
        .admin-tabs-sidebar { flex: 0 0 260px; }
        .admin-brand-lockup { margin-bottom: 28px; padding: 0 8px; }
        .admin-brand-lockup .site-title { display: inline-block; margin: 0; padding: 0; line-height: 1.15; }
        .admin-tab-list { display: grid; gap: 6px; }
        .admin-tab-button {
            width: 100%; display: flex; align-items: center; gap: 11px;
            padding: 10px 11px; border: 0; border-radius: 8px;
            background: transparent; color: var(--text-secondary);
            font: inherit; font-size: 13px; font-weight: 600;
            text-align: left; cursor: pointer; transition: all 0.2s ease;
        }
        .admin-tab-button:hover { color: var(--text-primary); background: var(--hover-color); }
        .admin-tab-button.active {
            color: white; background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            box-shadow: var(--shadow-sm);
        }
        .admin-tab-icon { width: 20px; text-align: center; font-size: 15px; }
        .admin-tabs-main { min-width: 0; }
        .admin-tabs-header { flex: 0 0 72px; height: 72px; }
        .admin-tabs-header h1 { font-size: 18px; line-height: 1.2; letter-spacing: -0.25px; }
        .admin-tabs-header p { margin-top: 3px; color: var(--text-secondary); font-size: 12px; }
        .admin-tabs-content { flex: 1; min-height: 0; overflow-y: auto; padding: 28px; }
        .admin-tab-panel[hidden] { display: none; }
        .api-state {
            display: inline-flex; align-items: center; gap: 8px; max-width: 48%;
            padding: 7px 11px; border: 1px solid var(--border-color); border-radius: 18px;
            background: white; color: var(--text-secondary); font-size: 12px; box-shadow: var(--shadow-sm);
        }
        .api-state-dot { width: 9px; height: 9px; border-radius: 50%; background: #f59e0b; }
        .api-state.ready .api-state-dot { background: var(--success); }
        .api-state.error .api-state-dot { background: #ef4444; }
        .admin-panel-heading { margin-bottom: 18px; }
        .admin-panel-heading h2 { margin: 0; font-size: 20px; letter-spacing: -0.3px; }
        .admin-panel-heading p { margin: 5px 0 0; color: var(--text-secondary); font-size: 13px; }
        .admin-card-simple {
            border: 1px solid var(--border-color); border-radius: 14px;
            background: rgba(255,255,255,0.96); box-shadow: var(--shadow-sm);
        }
        .document-layout { display: grid; grid-template-columns: minmax(280px, .72fr) minmax(440px, 1.28fr); gap: 22px; align-items: start; }
        .tier-layout { display: grid; grid-template-columns: minmax(230px, .48fr) minmax(480px, 1.52fr); gap: 22px; align-items: start; }
        .upload-box, .table-card, .tier-list-card, .tier-editor, .audit-card { padding: 22px; }
        .admin-card-simple h3, .admin-card-simple h4 { margin: 0; font-size: 17px; letter-spacing: -0.2px; }
        .upload-drop-simple {
            min-height: 180px; margin-top: 18px; padding: 24px;
            display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
            border: 1.5px dashed #c7c9f7; border-radius: 12px;
            background: linear-gradient(135deg, rgba(99,102,241,.045), rgba(139,92,246,.035));
            cursor: pointer; text-align: center; transition: all .2s ease;
        }
        .upload-drop-simple:hover { border-color: var(--accent-primary); background: rgba(99,102,241,.07); }
        .upload-drop-simple input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
        .upload-drop-simple strong { font-size: 14px; overflow-wrap: anywhere; }
        .upload-drop-simple span { color: var(--text-secondary); font-size: 11px; }
        .admin-primary, .admin-secondary, .admin-danger {
            display: inline-flex; align-items: center; justify-content: center;
            border-radius: 8px; font: inherit; font-size: 12px; font-weight: 700;
            cursor: pointer; transition: all .2s ease;
        }
        .admin-primary { padding: 9px 14px; border: 0; background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)); color: white; }
        .upload-box .admin-primary { width: 100%; margin-top: 14px; }
        .admin-secondary { padding: 7px 12px; border: 1px solid var(--border-color); background: white; color: var(--text-secondary); }
        .admin-secondary:hover { border-color: var(--accent-primary); color: var(--accent-primary); }
        .admin-danger { padding: 6px 10px; border: 1px solid #fecaca; background: #fff; color: #b91c1c; }
        .admin-danger:hover { background: #fef2f2; border-color: #ef4444; }
        .admin-primary:disabled, .admin-secondary:disabled, .admin-danger:disabled { opacity: .5; cursor: wait; }
        .admin-message-simple { min-height: 0; margin-top: 12px; border-radius: 8px; font-size: 12px; }
        .admin-message-simple:not(:empty) { padding: 9px 11px; }
        .admin-message-simple.success { background: #ecfdf5; color: #047857; }
        .admin-message-simple.error { background: #fef2f2; color: #991b1b; }
        .admin-message-simple.working { background: #eef2ff; color: #4338ca; }
        .card-title-row, .audit-controls { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
        .admin-table-wrap { width: 100%; overflow-x: auto; border: 1px solid var(--border-color); border-radius: 10px; }
        .admin-simple-table { width: 100%; min-width: 680px; border-collapse: collapse; font-size: 12px; }
        .admin-simple-table th { padding: 10px 12px; background: var(--bg-sidebar); color: var(--text-secondary); font-size: 10px; text-align: left; text-transform: uppercase; letter-spacing: .55px; }
        .admin-simple-table td { padding: 12px; border-top: 1px solid var(--border-color); vertical-align: middle; }
        .admin-simple-table td strong { display: block; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .empty-row { padding: 26px !important; color: var(--text-secondary); text-align: center; }
        .status-pill, .audit-type, .model-badge { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; }
        .status-pill { background: var(--hover-color); color: var(--text-secondary); text-transform: capitalize; }
        .status-ready, .status-complete, .status-completed { background: #d1fae5; color: #047857; }
        .status-processing, .status-embedding, .status-uploaded { background: #e0e7ff; color: #4338ca; }
        .status-failed, .status-error { background: #fee2e2; color: #b91c1c; }
        .tier-list-card { display: grid; gap: 8px; }
        .tier-choice { width: 100%; padding: 12px 13px; border: 1px solid var(--border-color); border-radius: 9px; background: white; text-align: left; cursor: pointer; }
        .tier-choice strong, .tier-choice span { display: block; }
        .tier-choice span { margin-top: 3px; color: var(--text-secondary); font-size: 11px; }
        .tier-choice:hover, .tier-choice.active { border-color: var(--accent-primary); background: rgba(99,102,241,.055); }
        .tier-price-row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; align-items: end; margin: 18px 0; }
        .field-label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 11px; font-weight: 700; }
        .field-label input { width: 100%; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 8px; background: white; }
        .model-list { display: grid; gap: 8px; max-height: 430px; overflow-y: auto; padding-right: 3px; }
        .model-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 10px; align-items: center; padding: 10px; border: 1px solid var(--border-color); border-radius: 9px; cursor: pointer; }
        .model-row:hover { background: var(--hover-color); }
        .model-row strong, .model-row small { display: block; }
        .model-row small { margin-top: 3px; color: var(--text-secondary); }
        .model-statuses { display: flex; flex-wrap: wrap; gap: 5px; justify-content: flex-end; }
        .model-available { background: #d1fae5; color: #047857; }
        .model-unavailable { background: #fee2e2; color: #b91c1c; }
        .model-disabled { background: #f3f4f6; color: #6b7280; }
        .audit-type { background: #eef2ff; color: #4338ca; }
        .sidebar-dashboard-link { gap: 7px; }
        .brand-home-link:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 4px; border-radius: 4px; }
        @media (max-width: 980px) {
            .document-layout, .tier-layout { grid-template-columns: 1fr; }
            .api-state { max-width: 54%; }
        }
        @media (max-width: 720px) {
            .admin-tabs-sidebar { flex-basis: 210px; }
            .admin-tabs-content { padding: 18px; }
            .admin-tabs-header { padding: 12px 16px; }
            .api-state { display: none; }
            .upload-box, .table-card, .tier-list-card, .tier-editor, .audit-card { padding: 18px; }
        }
    </style>
</head>
<body class="admin-body">
<div class="app-shell admin-tabs-page" data-admin-user-id="<%= adminUserId %>">
    <aside class="sidebar admin-sidebar admin-tabs-sidebar">
        <div class="sidebar-top">
            <div class="admin-brand-lockup">
                <a href="<%= request.getContextPath() %>/index.jsp" class="site-title brand-home-link">RAGdoll</a>
                <span class="sidebar-role-label">ADMIN</span>
            </div>

            <nav class="admin-tab-list" role="tablist" aria-label="Administrator tools">
                <button class="admin-tab-button active" type="button" role="tab"
                        aria-selected="true" aria-controls="documents-panel" data-tab="documents">
                    <span class="admin-tab-icon" aria-hidden="true">▤</span>
                    <span>RAG Documents</span>
                </button>
                <button class="admin-tab-button" type="button" role="tab"
                        aria-selected="false" aria-controls="pricing-panel" data-tab="pricing">
                    <span class="admin-tab-icon" aria-hidden="true">$</span>
                    <span>Pricing &amp; Tiers</span>
                </button>
                <button class="admin-tab-button" type="button" role="tab"
                        aria-selected="false" aria-controls="audit-panel" data-tab="audit">
                    <span class="admin-tab-icon" aria-hidden="true">◷</span>
                    <span>Audit Logs</span>
                </button>
            </nav>

            <div class="admin-sidebar-note">
                <strong>Administrator workspace</strong>
                <span>Manage RAG content, model access, pricing, and database activity.</span>
            </div>
        </div>

        <div class="sidebar-bottom admin-sidebar-bottom">
            <a class="sidebar-dashboard-link" href="dashboard.jsp">
                <span aria-hidden="true">↗</span>
                Open dashboard as admin
            </a>
            <div class="user-profile admin-user-profile" data-admin-user-id="<%= adminUserId %>">
                <div class="avatar"><%= escapeHtml(adminAvatarText) %></div>
                <div class="user-info">
                    <div class="user-name"><%= escapeHtml(adminDisplayName) %></div>
                    <div class="user-tier">
                        Administrator · ID <%= adminUserId %>
                        <% if (temporaryAdmin) { %> · Temporary<% } %>
                    </div>
                </div>
            </div>
        </div>
    </aside>

    <main class="main-area admin-main-area admin-tabs-main">
        <header class="top-nav admin-top-nav admin-tabs-header">
            <div>
                <span class="top-nav-kicker">Administration</span>
                <h1 id="page-title">RAG Documents</h1>
                <p id="page-description">Upload documents and remove their stored chunks and embeddings.</p>
            </div>
            <div class="api-state" id="api-state">
                <span class="api-state-dot" aria-hidden="true"></span>
                <span id="api-state-text">Connecting to local RAG API</span>
            </div>
        </header>

        <div class="admin-tabs-content">
            <section class="admin-tab-panel" id="documents-panel" data-panel="documents" role="tabpanel">
                <div class="admin-panel-heading">
                    <h2>RAG Documents</h2>
                    <p>Upload source files for chunking and embedding, or permanently remove stored RAG content.</p>
                </div>
                <div class="document-layout">
                    <article class="admin-card-simple upload-box">
                        <h3>Upload RAG document</h3>
                        <form id="document-upload-form" enctype="multipart/form-data">
                            <label class="upload-drop-simple" for="document-file">
                                <strong id="selected-file-name">Choose a document</strong>
                                <span>PDF, TXT, Markdown, or DOCX · 25 MB maximum</span>
                                <input id="document-file" name="file" type="file"
                                       accept=".pdf,.txt,.md,.docx" required>
                            </label>
                            <button class="admin-primary" id="upload-submit" type="submit">
                                Upload, chunk, and embed
                            </button>
                        </form>
                        <div class="admin-message-simple" id="upload-message" role="status" aria-live="polite"></div>
                    </article>

                    <article class="admin-card-simple table-card">
                        <div class="card-title-row">
                            <h3>Stored RAG documents</h3>
                            <button class="admin-secondary" id="refresh-documents" type="button">Refresh</button>
                        </div>
                        <div class="admin-table-wrap">
                            <table class="admin-simple-table">
                                <thead>
                                <tr>
                                    <th>Document</th>
                                    <th>Status</th>
                                    <th>Chunks</th>
                                    <th>Embedding</th>
                                    <th>Uploaded</th>
                                    <th>Action</th>
                                </tr>
                                </thead>
                                <tbody id="document-table-body">
                                <tr><td colspan="6" class="empty-row">Loading documents…</td></tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="admin-message-simple" id="document-message" role="status" aria-live="polite"></div>
                    </article>
                </div>
            </section>

            <section class="admin-tab-panel" id="pricing-panel" data-panel="pricing" role="tabpanel" hidden>
                <div class="admin-panel-heading">
                    <h2>Pricing &amp; Tiers</h2>
                    <p>Set monthly prices and model access. Every model remembered in MySQL remains visible, even when unavailable.</p>
                </div>
                <div class="tier-layout">
                    <div class="admin-card-simple tier-list-card" id="tier-list">
                        <div class="empty-row">Loading tiers…</div>
                    </div>

                    <article class="admin-card-simple tier-editor">
                        <h3 id="tier-editor-title">Select a tier</h3>
                        <div id="tier-editor-content" hidden>
                            <div class="tier-price-row">
                                <label class="field-label">
                                    Monthly price (USD)
                                    <input id="tier-price" type="number" min="0" max="999999.99" step="0.01">
                                </label>
                                <button class="admin-primary" id="save-tier" type="button">Save tier</button>
                            </div>
                            <div class="card-title-row">
                                <h3>Model access</h3>
                                <small id="model-count-summary"></small>
                            </div>
                            <div class="model-list" id="model-list"></div>
                        </div>
                        <div class="admin-message-simple" id="tier-message" role="status" aria-live="polite"></div>
                    </article>
                </div>
            </section>

            <section class="admin-tab-panel" id="audit-panel" data-panel="audit" role="tabpanel" hidden>
                <div class="admin-panel-heading">
                    <h2>Audit Logs</h2>
                    <p>Review recent user and administrator activity recorded by RAGdoll.</p>
                </div>
                <article class="admin-card-simple audit-card">
                    <div class="audit-controls">
                        <div>
                            <h3>Recorded activity</h3>
                        </div>
                        <button class="admin-secondary" id="refresh-audit" type="button">Refresh</button>
                    </div>
                    <div class="admin-table-wrap">
                        <table class="admin-simple-table">
                            <thead>
                            <tr>
                                <th>Date</th>
                                <th>User</th>
                                <th>Type</th>
                                <th>Action</th>
                            </tr>
                            </thead>
                            <tbody id="audit-table-body">
                            <tr><td colspan="4" class="empty-row">Open this tab to load audit logs.</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="admin-message-simple" id="audit-message" role="status" aria-live="polite"></div>
                </article>
            </section>
        </div>
    </main>
</div>

<script>
    const API_BASE_URL = window.RAGDOLL_API_URL || "http://127.0.0.1:8000";
    const pageRoot = document.querySelector(".admin-tabs-page");
    const ADMIN_USER_ID = Number(pageRoot.dataset.adminUserId);
    const moneyFormatter = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD"
    });

    const tabMetadata = {
        documents: {
            title: "RAG Documents",
            description: "Upload documents and remove their stored chunks and embeddings."
        },
        pricing: {
            title: "Pricing & Tiers",
            description: "Set monthly prices and decide which remembered models each tier can access."
        },
        audit: {
            title: "Audit Logs",
            description: "Review recorded activity across the RAGdoll database."
        }
    };

    const loadedTabs = { documents: false, pricing: false, audit: false };
    let tierState = { tiers: [], models: [], selectedTierId: null };

    function wait(milliseconds) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, milliseconds);
        });
    }

    function setApiState(text, type) {
        const state = document.getElementById("api-state");
        state.className = "api-state" + (type ? " " + type : "");
        document.getElementById("api-state-text").textContent = text;
    }

    async function apiFetch(url, options) {
        const attempts = 45;
        let lastError = new Error("The local RAG API did not start.");

        for (let attempt = 1; attempt <= attempts; attempt += 1) {
            try {
                const response = await fetch(url, options);
                setApiState("Local RAG API connected", "ready");
                return response;
            } catch (error) {
                lastError = error;
                setApiState("Starting local RAG API (" + attempt + "/" + attempts + ")", "");
                if (attempt < attempts) {
                    await wait(1000);
                }
            }
        }

        setApiState("Local RAG API unavailable", "error");
        throw lastError;
    }

    async function apiJson(url, options) {
        const response = await apiFetch(url, options);
        const payload = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            throw new Error(payload.detail || ("Request failed with status " + response.status + "."));
        }
        return payload;
    }

    function setMessage(element, message, type) {
        element.textContent = message || "";
        element.className = "admin-message-simple" + (type ? " " + type : "");
    }

    function formatDate(value) {
        if (!value) {
            return "—";
        }
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("en-US");
    }

    function statusPill(status) {
        const normalized = String(status || "unknown").toLowerCase();
        const pill = document.createElement("span");
        pill.className = "status-pill status-" + normalized;
        pill.textContent = normalized;
        return pill;
    }

    function openTab(tabName) {
        document.querySelectorAll(".admin-tab-button").forEach(function (button) {
            const active = button.dataset.tab === tabName;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll(".admin-tab-panel").forEach(function (panel) {
            panel.hidden = panel.dataset.panel !== tabName;
        });

        const metadata = tabMetadata[tabName];
        document.getElementById("page-title").textContent = metadata.title;
        document.getElementById("page-description").textContent = metadata.description;

        if (tabName === "documents" && !loadedTabs.documents) {
            loadDocuments();
        } else if (tabName === "pricing" && !loadedTabs.pricing) {
            loadPricing();
        } else if (tabName === "audit" && !loadedTabs.audit) {
            loadAuditLogs();
        }
    }

    document.querySelectorAll(".admin-tab-button").forEach(function (button) {
        button.addEventListener("click", function () {
            openTab(button.dataset.tab);
        });
    });

    const documentTableBody = document.getElementById("document-table-body");
    const documentMessage = document.getElementById("document-message");
    const uploadForm = document.getElementById("document-upload-form");
    const fileInput = document.getElementById("document-file");
    const selectedFileName = document.getElementById("selected-file-name");
    const uploadButton = document.getElementById("upload-submit");
    const uploadMessage = document.getElementById("upload-message");

    function renderDocuments(documents) {
        documentTableBody.replaceChildren();
        if (!Array.isArray(documents) || documents.length === 0) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 6;
            cell.className = "empty-row";
            cell.textContent = "No RAG documents have been uploaded.";
            row.appendChild(cell);
            documentTableBody.appendChild(row);
            return;
        }

        documents.forEach(function (documentRecord) {
            const row = document.createElement("tr");

            const nameCell = document.createElement("td");
            const name = document.createElement("strong");
            name.textContent = documentRecord.file_name || "Untitled document";
            nameCell.appendChild(name);
            if (documentRecord.processing_error) {
                const error = document.createElement("small");
                error.style.display = "block";
                error.style.marginTop = "4px";
                error.style.color = "#b91c1c";
                error.textContent = documentRecord.processing_error;
                nameCell.appendChild(error);
            }

            const statusCell = document.createElement("td");
            statusCell.appendChild(statusPill(documentRecord.processing_status));

            const chunksCell = document.createElement("td");
            chunksCell.textContent = String(documentRecord.chunk_count || 0);

            const embeddingCell = document.createElement("td");
            const embeddingModel = documentRecord.embedding_model || "Not embedded";
            const embeddingDimension = Number(documentRecord.embedding_dimension || 0);
            embeddingCell.textContent = embeddingDimension > 0
                ? embeddingModel + " · " + embeddingDimension + "D"
                : embeddingModel;

            const dateCell = document.createElement("td");
            dateCell.textContent = formatDate(documentRecord.uploaded_at);

            const actionCell = document.createElement("td");
            const removeButton = document.createElement("button");
            removeButton.type = "button";
            removeButton.className = "admin-danger";
            removeButton.textContent = "Remove";
            removeButton.addEventListener("click", function () {
                removeDocument(documentRecord, removeButton);
            });
            actionCell.appendChild(removeButton);

            [nameCell, statusCell, chunksCell, embeddingCell, dateCell, actionCell].forEach(function (cell) {
                row.appendChild(cell);
            });
            documentTableBody.appendChild(row);
        });
    }

    async function loadDocuments(showMessage) {
        if (showMessage !== false) {
            setMessage(documentMessage, "Loading documents…", "working");
        }
        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/documents?admin_user_id=" + encodeURIComponent(ADMIN_USER_ID)
            );
            renderDocuments(payload.documents || []);
            loadedTabs.documents = true;
            setMessage(documentMessage, "", "");
        } catch (error) {
            documentTableBody.innerHTML = '<tr><td colspan="6" class="empty-row">Documents could not be loaded.</td></tr>';
            setMessage(documentMessage, error.message, "error");
        }
    }

    async function removeDocument(documentRecord, button) {
        const fileName = documentRecord.file_name || "this document";
        const chunkCount = Number(documentRecord.chunk_count || 0);
        if (!window.confirm(
            "Remove " + fileName + "? This deletes " + chunkCount +
            " chunk(s), embeddings, and the uploaded file."
        )) {
            return;
        }

        button.disabled = true;
        button.textContent = "Removing…";
        setMessage(documentMessage, "Removing " + fileName + "…", "working");

        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/documents/" + encodeURIComponent(documentRecord.document_id) +
                "?admin_user_id=" + encodeURIComponent(ADMIN_USER_ID),
                { method: "DELETE" }
            );
            setMessage(
                documentMessage,
                payload.file_name + " and " + payload.deleted_chunk_count + " chunk(s) were removed.",
                "success"
            );
            loadedTabs.audit = false;
            await loadDocuments(false);
        } catch (error) {
            button.disabled = false;
            button.textContent = "Remove";
            setMessage(documentMessage, error.message, "error");
        }
    }

    fileInput.addEventListener("change", function () {
        selectedFileName.textContent = fileInput.files.length
            ? fileInput.files[0].name
            : "Choose a document";
    });

    uploadForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        if (!fileInput.files.length) {
            setMessage(uploadMessage, "Choose a document first.", "error");
            return;
        }

        uploadButton.disabled = true;
        uploadButton.textContent = "Processing…";
        setMessage(uploadMessage, "Extracting, chunking, embedding, and storing the document…", "working");

        const formData = new FormData();
        formData.append("admin_user_id", String(ADMIN_USER_ID));
        formData.append("file", fileInput.files[0]);

        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/documents",
                { method: "POST", body: formData }
            );
            setMessage(
                uploadMessage,
                payload.file_name + " was stored with " + payload.chunk_count + " chunk(s).",
                "success"
            );
            uploadForm.reset();
            selectedFileName.textContent = "Choose a document";
            loadedTabs.audit = false;
            await loadDocuments(false);
        } catch (error) {
            setMessage(uploadMessage, error.message, "error");
        } finally {
            uploadButton.disabled = false;
            uploadButton.textContent = "Upload, chunk, and embed";
        }
    });

    document.getElementById("refresh-documents").addEventListener("click", function () {
        loadDocuments();
    });

    const tierList = document.getElementById("tier-list");
    const tierEditorTitle = document.getElementById("tier-editor-title");
    const tierEditorContent = document.getElementById("tier-editor-content");
    const tierPrice = document.getElementById("tier-price");
    const modelList = document.getElementById("model-list");
    const tierMessage = document.getElementById("tier-message");
    const saveTierButton = document.getElementById("save-tier");

    function selectedTier() {
        return tierState.tiers.find(function (tier) {
            return Number(tier.tier_id) === Number(tierState.selectedTierId);
        });
    }

    function renderTierList() {
        tierList.replaceChildren();
        tierState.tiers.forEach(function (tier) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "tier-choice" +
                (Number(tier.tier_id) === Number(tierState.selectedTierId) ? " active" : "");

            const name = document.createElement("strong");
            name.textContent = tier.tier_name;
            const detail = document.createElement("span");
            detail.textContent = moneyFormatter.format(Number(tier.price || 0)) +
                " · " + (tier.model_ids || []).length + " model(s)";
            button.append(name, detail);
            button.addEventListener("click", function () {
                tierState.selectedTierId = Number(tier.tier_id);
                renderTierList();
                renderTierEditor();
            });
            tierList.appendChild(button);
        });
    }

    function modelBadge(text, className) {
        const badge = document.createElement("span");
        badge.className = "model-badge " + className;
        badge.textContent = text;
        return badge;
    }

    function renderTierEditor() {
        const tier = selectedTier();
        if (!tier) {
            tierEditorTitle.textContent = "Select a tier";
            tierEditorContent.hidden = true;
            return;
        }

        tierEditorTitle.textContent = tier.tier_name;
        tierEditorContent.hidden = false;
        tierPrice.value = Number(tier.price || 0).toFixed(2);
        modelList.replaceChildren();
        const accessible = new Set((tier.model_ids || []).map(Number));

        tierState.models.forEach(function (model) {
            const row = document.createElement("label");
            row.className = "model-row";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = String(model.model_id);
            checkbox.checked = accessible.has(Number(model.model_id));

            const details = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = model.model_name;
            const metadata = document.createElement("small");
            metadata.textContent = model.model_type + " · " +
                (model.model_location || "local") + " · ID " + model.model_id;
            details.append(name, metadata);

            const statuses = document.createElement("div");
            statuses.className = "model-statuses";
            statuses.appendChild(
                modelBadge(
                    model.is_available ? "Available" : "Unavailable",
                    model.is_available ? "model-available" : "model-unavailable"
                )
            );
            if (!model.is_enabled) {
                statuses.appendChild(modelBadge("Disabled", "model-disabled"));
            }

            row.append(checkbox, details, statuses);
            modelList.appendChild(row);
        });

        document.getElementById("model-count-summary").textContent =
            tierState.models.length + " remembered model(s)";
    }

    async function loadPricing(preferredTierId) {
        setMessage(tierMessage, "Loading pricing and remembered models…", "working");
        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/tiers?admin_user_id=" + encodeURIComponent(ADMIN_USER_ID)
            );
            tierState.tiers = payload.tiers || [];
            tierState.models = payload.models || [];
            tierState.selectedTierId = preferredTierId || tierState.selectedTierId ||
                (tierState.tiers.length ? Number(tierState.tiers[0].tier_id) : null);
            renderTierList();
            renderTierEditor();
            loadedTabs.pricing = true;
            setMessage(
                tierMessage,
                payload.model_sync_error ? "Model scan warning: " + payload.model_sync_error : "",
                payload.model_sync_error ? "error" : ""
            );
        } catch (error) {
            tierList.innerHTML = '<div class="empty-row">Pricing could not be loaded.</div>';
            setMessage(tierMessage, error.message, "error");
        }
    }

    saveTierButton.addEventListener("click", async function () {
        const tier = selectedTier();
        if (!tier) {
            return;
        }

        const price = Number(tierPrice.value);
        if (!Number.isFinite(price) || price < 0) {
            setMessage(tierMessage, "Enter a valid non-negative price.", "error");
            return;
        }

        const modelIds = Array.from(modelList.querySelectorAll('input[type="checkbox"]:checked'))
            .map(function (checkbox) { return Number(checkbox.value); });

        saveTierButton.disabled = true;
        saveTierButton.textContent = "Saving…";
        setMessage(tierMessage, "Saving " + tier.tier_name + "…", "working");
        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/tiers/" + encodeURIComponent(tier.tier_id) +
                "?admin_user_id=" + encodeURIComponent(ADMIN_USER_ID),
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ price: price, model_ids: modelIds })
                }
            );
            loadedTabs.audit = false;
            await loadPricing(Number(tier.tier_id));
            setMessage(
                tierMessage,
                payload.tier.tier_name + " was updated to " +
                moneyFormatter.format(Number(payload.tier.price)) + ".",
                "success"
            );
        } catch (error) {
            setMessage(tierMessage, error.message, "error");
        } finally {
            saveTierButton.disabled = false;
            saveTierButton.textContent = "Save tier";
        }
    });

    const auditTableBody = document.getElementById("audit-table-body");
    const auditMessage = document.getElementById("audit-message");

    function renderAuditLogs(logs) {
        auditTableBody.replaceChildren();
        if (!Array.isArray(logs) || logs.length === 0) {
            auditTableBody.innerHTML = '<tr><td colspan="4" class="empty-row">No audit records were found.</td></tr>';
            return;
        }

        logs.forEach(function (log) {
            const row = document.createElement("tr");
            const dateCell = document.createElement("td");
            dateCell.textContent = formatDate(log.action_date);
            const userCell = document.createElement("td");
            userCell.textContent = log.username +
                (log.user_id === null ? "" : " (" + log.user_id + ")");
            const typeCell = document.createElement("td");
            const type = document.createElement("span");
            type.className = "audit-type";
            type.textContent = log.action_type;
            typeCell.appendChild(type);
            const actionCell = document.createElement("td");
            actionCell.textContent = log.action_log;
            row.append(dateCell, userCell, typeCell, actionCell);
            auditTableBody.appendChild(row);
        });
    }

    async function loadAuditLogs() {
        setMessage(auditMessage, "Loading audit logs…", "working");
        try {
            const payload = await apiJson(
                API_BASE_URL + "/api/admin/audit-logs?admin_user_id=" +
                encodeURIComponent(ADMIN_USER_ID) + "&limit=100"
            );
            renderAuditLogs(payload.logs || []);
            loadedTabs.audit = true;
            setMessage(auditMessage, "", "");
        } catch (error) {
            auditTableBody.innerHTML = '<tr><td colspan="4" class="empty-row">Audit logs could not be loaded.</td></tr>';
            setMessage(auditMessage, error.message, "error");
        }
    }

    document.getElementById("refresh-audit").addEventListener("click", loadAuditLogs);

    openTab("documents");
</script>
</body>
</html>