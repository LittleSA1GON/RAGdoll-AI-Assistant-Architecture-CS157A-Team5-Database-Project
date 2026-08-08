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
%>
<%
    Object sessionUserId = session.getAttribute("userId");
    if (session.getAttribute("adminUserId") != null) {
        response.sendRedirect(request.getContextPath() + "/views/admin.jsp");
        return;
    }
    if (sessionUserId == null) {
        response.sendRedirect(request.getContextPath() + "/views/login.jsp");
        return;
    }
    int currentUserId;
    try {
        currentUserId = Integer.parseInt(String.valueOf(sessionUserId));
    } catch (NumberFormatException ignored) {
        response.sendRedirect(request.getContextPath() + "/views/login.jsp");
        return;
    }
    String currentDisplayName = String.valueOf(session.getAttribute("userDisplayName"));
    if (currentDisplayName == null || currentDisplayName.isBlank() || "null".equals(currentDisplayName)) {
        currentDisplayName = "User";
    }
    String currentTier = String.valueOf(session.getAttribute("userTier"));
    if (currentTier == null || currentTier.isBlank() || "null".equals(currentTier)) {
        currentTier = "Free";
    }
%>
<!DOCTYPE html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Upgrade Tier - RAGdoll AI Assistant</title>
    <link rel="icon" type="image/png" href="../images/ragdoll-icon.png">
    <link rel="stylesheet" href="../css/style.css?v=13">
</head>
<body class="dashboard-body">
    <div class="app-shell">
        <aside class="sidebar">
            <div class="sidebar-top">
                <a href="<%= request.getContextPath() %>/index.jsp" class="site-title brand-home-link brand-lockup" aria-label="RAGdoll home">
                    <img src="<%= request.getContextPath() %>/images/ragdoll-icon.png" alt="" class="brand-icon">
                    <span class="dash-logo">RAGdoll</span>
                </a>

                <button class="new-chat-btn" type="button" onclick="window.location.href='<%= request.getContextPath() %>/views/dashboard.jsp'">
                    <span class="left-icon" aria-hidden="true">←</span>
                    <span>Back to dashboard</span>
                </button>
            </div>
            <div class="sidebar-bottom">
                <div class="user-profile" data-user-id="<%= currentUserId %>" data-admin-view="false">
                    <div class="avatar"><%= escapeHtml(currentDisplayName) %></div>
                    <div class="user-info">
                        <div class="user-name"><%= escapeHtml(currentDisplayName) %></div>
                        <div class="user-tier"><%= escapeHtml(currentTier) %> · ID <%= currentUserId %></div>
                    </div>
                </div>
                <form action="<%= request.getContextPath() %>/auth" method="POST">
                    <input type="hidden" name="action" value="logout">
                    <button type="submit" class="sidebar-dashboard-link">Sign out</button>
                </form>
            </div>
        </aside>

        <main class="main-area">
            <div class="payment-content">
                <div class="payment-header">
                    <div>
                        <h1>Upgrade your tier</h1>
                        <p>Choose a plan and save a simulated payment record in MySQL. No real gateway is used.</p>
                    </div>
                    <div class="payment-message" id="payment-message">Loading your current tier...</div>
                </div>

                <div id="tier-list" class="payment-grid"></div>

                <section>
                    <h2>Payment history</h2>
                    <table class="payment-history" id="payment-history">
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Tier</th>
                                <th>Price</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="4">Loading history...</td></tr>
                        </tbody>
                    </table>
                </section>
            </div>
        </main>
    </div>

    <script>
        const API_BASE_URL = "<%= request.getContextPath() %>";
        const currentUserId = <%= currentUserId %>;
        const tierList = document.getElementById("tier-list");
        const paymentMessage = document.getElementById("payment-message");
        const historyBody = document.querySelector("#payment-history tbody");

        async function apiJson(url, options, errorMessage) {
            const response = await fetch(url, options);
            if (!response.ok) {
                const body = await response.text();
                throw new Error(errorMessage + " " + body);
            }
            return await response.json();
        }

        function formatCurrency(value) {
            return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
        }

        function showError(message) {
            paymentMessage.textContent = message;
            paymentMessage.style.color = "#b02a5b";
        }

        function buildTierPanel(tier, currentTierId) {
            const panel = document.createElement("div");
            panel.className = "tier-panel" + (tier.tier_id === currentTierId ? " current" : "");
            const title = document.createElement("h2");
            title.textContent = tier.tier_name;
            const price = document.createElement("div");
            price.className = "tier-price";
            price.textContent = formatCurrency(tier.price);
            const description = document.createElement("p");
            description.textContent = tier.tier_id === currentTierId
                ? "Your current subscription tier."
                : "Simulated upgrade to this tier using MySQL only.";
            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn-secondary";
            button.textContent = tier.tier_id === currentTierId ? "Current" : "Upgrade";
            button.disabled = tier.tier_id === currentTierId;
            button.addEventListener("click", function () {
                upgradeTier(tier.tier_id);
            });
            panel.append(title, price, description, button);
            return panel;
        }

        function renderHistory(entries) {
            historyBody.replaceChildren();
            if (!Array.isArray(entries) || entries.length === 0) {
                const row = document.createElement("tr");
                row.innerHTML = "<td colspan=\"4\">No payment history found.</td>";
                historyBody.appendChild(row);
                return;
            }
            for (const entry of entries) {
                const row = document.createElement("tr");
                const dateCell = document.createElement("td");
                dateCell.textContent = entry.payment_date || "Unknown";
                const tierCell = document.createElement("td");
                tierCell.textContent = entry.tier_name || "Unknown";
                const priceCell = document.createElement("td");
                priceCell.textContent = formatCurrency(Number(entry.price || 0));
                const statusCell = document.createElement("td");
                statusCell.textContent = entry.status || "Unknown";
                row.append(dateCell, tierCell, priceCell, statusCell);
                historyBody.appendChild(row);
            }
        }

        async function loadTiers() {
            try {
                const result = await apiJson(API_BASE_URL + "/api/payments/tiers", { cache: "no-store" }, "Unable to load tiers.");
                const currentTier = result.current_tier || {};
                paymentMessage.textContent = currentTier.tier_name
                    ? "Current tier: " + currentTier.tier_name + " (" + formatCurrency(Number(currentTier.price || 0)) + ")"
                    : "No current tier is assigned yet.";
                tierList.replaceChildren();
                const currentTierId = Number(currentTier.tier_id || -1);
                for (const tier of result.tiers || []) {
                    tierList.appendChild(buildTierPanel(tier, currentTierId));
                }
                renderHistory(result.payment_history || []);
            } catch (error) {
                showError(error.message);
            }
        }

        async function upgradeTier(tierId) {
            const confirmation = confirm("Simulate upgrade to tier " + tierId + "? This records the payment in MySQL only.");
            if (!confirmation) {
                return;
            }
            try {
                const result = await apiJson(
                    API_BASE_URL + "/api/payments/upgrade",
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ tier_id: tierId })
                    },
                    "Unable to complete upgrade."
                );
                paymentMessage.textContent = "Simulated upgrade recorded: " + result.tier_name + ".";
                paymentMessage.style.color = "var(--text-primary)";
                await loadTiers();
            } catch (error) {
                showError(error.message);
            }
        }

        loadTiers();
    </script>
</body>
</html>
