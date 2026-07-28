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
    boolean adminRequired = "true".equals(request.getParameter("admin_required"));
    String status = request.getParameter("status");
%>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login - RAGdoll AI</title>
    <link rel="icon" type="image/png" href="<%= request.getContextPath() %>/images/ragdoll-icon.png">
    <link rel="stylesheet" href="<%= request.getContextPath() %>/css/style.css?v=13">
</head>
<body class="auth-body">
    <div class="auth-wrapper">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Welcome back</h2>
                <p>Log in to your <a href="<%= request.getContextPath() %>/index.jsp" class="brand-inline-link brand-inline-lockup">
                    <img src="<%= request.getContextPath() %>/images/ragdoll-icon.png" alt="" class="brand-icon brand-icon-inline">
                    <span>RAGdoll</span>
                </a> account</p>
            </div>
            
            <% if ("signed_out".equals(status)) { %>
            <div class="auth-message info">You have been signed out.</div>
            <% } %>
            <% if (adminRequired) { %>
            <div class="auth-message error">Please log in with an administrator account to continue.</div>
            <% } %>
            <% if (errorMessage != null) { %>
            <div class="auth-message error"><%= escapeHtml(errorMessage) %></div>
            <% } %>

            <form action="<%= request.getContextPath() %>/auth?action=login" method="POST" class="auth-form">
                <div class="form-group">
                    <label for="email">Email address</label>
                    <input type="email" id="email" name="email" placeholder="name@example.com" required>
                </div>
                
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" placeholder="••••••••" required>
                </div>
                
                <button type="submit" class="auth-submit-btn">Continue</button>
            </form>

            <div class="auth-footer">
                <p>Don't have an account? <a href="signup.jsp">Sign up</a></p>
                <p><a href="<%= request.getContextPath() %>/index.jsp" class="back-link">← Back to Home</a></p>
            </div>
        </div>
    </div>
</body>
</html>
