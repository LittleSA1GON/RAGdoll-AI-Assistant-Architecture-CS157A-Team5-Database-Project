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
    String errorMessage = (String) request.getAttribute("errorMessage");
%>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sign up - RAGdoll AI</title>
    <link rel="icon" type="image/png" href="<%= request.getContextPath() %>/images/ragdoll-icon.png">
    <link rel="stylesheet" href="<%= request.getContextPath() %>/css/style.css?v=13">
</head>
<body class="auth-body">
    <div class="auth-wrapper">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Create your account</h2>
                <p>Sign up for <a href="<%= request.getContextPath() %>/index.jsp" class="brand-inline-link brand-inline-lockup">
                    <img src="<%= request.getContextPath() %>/images/ragdoll-icon.png" alt="" class="brand-icon brand-icon-inline">
                    <span>RAGdoll</span>
                </a></p>
            </div>

            <% if (errorMessage != null) { %>
            <div class="auth-message error"><%= escapeHtml(errorMessage) %></div>
            <% } %>
            <div class="auth-message error" id="client-signup-error" hidden></div>

            <form action="<%= request.getContextPath() %>/auth?action=signup" method="POST" class="auth-form" id="signup-form">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input
                        type="text"
                        id="username"
                        name="username"
                        placeholder="Choose a username"
                        minlength="3"
                        maxlength="50"
                        pattern="[A-Za-z0-9_]+"
                        title="Letters, numbers, and underscores only"
                        autocomplete="username"
                        required>
                </div>

                <div class="form-group">
                    <label for="email">Email address</label>
                    <input
                        type="email"
                        id="email"
                        name="email"
                        placeholder="name@example.com"
                        autocomplete="email"
                        required>
                </div>

                <div class="form-group">
                    <label for="password">Password</label>
                    <input
                        type="password"
                        id="password"
                        name="password"
                        placeholder="••••••••"
                        minlength="8"
                        autocomplete="new-password"
                        required>
                </div>

                <div class="form-group">
                    <label for="confirm-password">Confirm password</label>
                    <input
                        type="password"
                        id="confirm-password"
                        name="confirm_password"
                        placeholder="••••••••"
                        minlength="8"
                        autocomplete="new-password"
                        required>
                </div>

                <button type="submit" class="auth-submit-btn">Create account</button>
            </form>

            <div class="auth-footer">
                <p>Already have an account? <a href="<%= request.getContextPath() %>/auth?action=login">Log in</a></p>
                <p><a href="<%= request.getContextPath() %>/index.jsp" class="back-link">← Back to Home</a></p>
            </div>
        </div>
    </div>
    <script>
        (function () {
            const form = document.getElementById("signup-form");
            const passwordInput = document.getElementById("password");
            const confirmInput = document.getElementById("confirm-password");
            const status = document.getElementById("client-signup-error");

            function showStatus(message) {
                status.textContent = message;
                status.hidden = false;
            }

            function clearStatus() {
                status.textContent = "";
                status.hidden = true;
            }

            form.addEventListener("submit", function (event) {
                const password = passwordInput.value || "";
                const confirm = confirmInput.value || "";

                if (password !== confirm) {
                    event.preventDefault();
                    showStatus("Passwords do not match.");
                    window.alert("Passwords do not match.");
                    confirmInput.focus();
                    return;
                }

                clearStatus();
            });

            confirmInput.addEventListener("input", function () {
                if (status.hidden) {
                    return;
                }
                if (passwordInput.value === confirmInput.value) {
                    clearStatus();
                }
            });
        })();
    </script>
</body>
</html>
