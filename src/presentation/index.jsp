<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>RAGdoll AI Assistant - Home</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <div class="app-shell">
        <header>
            <h1>RAGdoll AI Assistant</h1>
            <p>A minimal runnable 3-tier architecture homepage.</p>
        </header>

        <main>
            <section>
                <h2>Start here</h2>
                <p>This page is served through a servlet controller and forwarded to the presentation tier.</p>
                <div class="actions">
                    <a class="button" href="views/login.jsp">Login</a>
                    <a class="button" href="views/dashboard.jsp">Dashboard</a>
                </div>
            </section>
        </main>
    </div>
</body>
</html>
