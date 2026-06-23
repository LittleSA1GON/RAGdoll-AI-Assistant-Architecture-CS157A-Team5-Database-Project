<%@ page import="java.sql.*" %>
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
        <header>
            <h1>Dashboard</h1>
            <p>Simple SQL table loaded from the RAGdoll database.</p>
        </header>

        <main>
            <section>
                <h2>Available AI Models</h2>

                <%
                    String db = "ragdoll";
                    String user = "root";
                    String password = "1234";

                    try {
                        Class.forName("com.mysql.cj.jdbc.Driver");

                        Connection con = DriverManager.getConnection(
                            "jdbc:mysql://localhost:3306/ragdoll?autoReconnect=true&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC",
                            user,
                            password
                        );

                        out.println("<p class=\"status success\">" + db + " database successfully opened.</p>");
                        out.println("<p>Initial entries in table <strong>models</strong>:</p>");

                        out.println("<table class=\"data-table\">");
                        out.println("<tr><th>Model ID</th><th>Model Name</th><th>Access Level</th></tr>");

                        Statement stmt = con.createStatement();
                        ResultSet rs = stmt.executeQuery("SELECT model_id, model_name, access_level FROM models");

                        while (rs.next()) {
                            out.println("<tr>"
                                + "<td>" + rs.getInt("model_id") + "</td>"
                                + "<td>" + rs.getString("model_name") + "</td>"
                                + "<td>" + rs.getString("access_level") + "</td>"
                                + "</tr>");
                        }

                        out.println("</table>");

                        rs.close();
                        stmt.close();
                        con.close();
                    } catch (SQLException e) {
                        out.println("<p class=\"status error\">SQLException caught: " + e.getMessage() + "</p>");
                    } catch (ClassNotFoundException e) {
                        out.println("<p class=\"status error\">MySQL JDBC Driver not found: " + e.getMessage() + "</p>");
                    }
                %>
            </section>

            <p><a class="button" href="../index.jsp">Back to Home</a></p>
        </main>
    </div>
</body>
</html>