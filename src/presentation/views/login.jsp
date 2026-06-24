<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login - RAGdoll AI</title>
    <link rel="stylesheet" href="../css/style.css">
</head>
<body class="auth-body">
    <div class="auth-wrapper">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Welcome back</h2>
                <p>Log in to your RAGdoll account</p>
            </div>
            
            <form action="#" method="POST" class="auth-form">
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
                <p>Don't have an account? <a href="#">Sign up</a></p>
                <p><a href="../index.jsp" class="back-link">← Back to Home</a></p>
            </div>
        </div>
    </div>
</body>
</html>