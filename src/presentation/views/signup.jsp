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
    <link rel="icon" type="image/png" href="../images/ragdoll-icon.png">
    <link rel="stylesheet" href="../css/style.css?v=13">
</head>
<body class="auth-body">
    <div class="auth-wrapper">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Create your account</h2>
                <p>Sign up for <a href="../index.jsp" class="brand-inline-link brand-inline-lockup">
                    <img src="../images/ragdoll-icon.png" alt="" class="brand-icon brand-icon-inline">
                    <span>RAGdoll</span>
                </a></p>
            </div>

            <% if (errorMessage != null) { %>
            <div class="auth-message error"><%= escapeHtml(errorMessage) %></div>
            <% } %>

            <form action="<%= request.getContextPath() %>/auth?action=signup" method="POST" class="auth-form">
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
                <p>Already have an account? <a href="login.jsp">Log in</a></p>
                <p><a href="../index.jsp" class="back-link">← Back to Home</a></p>
            </div>
        </div>
    </div>
</body>
</html>
