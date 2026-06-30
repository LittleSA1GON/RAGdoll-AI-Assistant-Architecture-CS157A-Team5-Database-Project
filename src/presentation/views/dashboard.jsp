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
                    <select id="ai-model" name="ai-model">
                        <%
                            String db = "ragdoll";
                            String user = "root";
                            String password = System.getenv("DB_PASSWORD");

                            try {
                                Class.forName("com.mysql.cj.jdbc.Driver");
                                Connection con = DriverManager.getConnection(
                                    "jdbc:mysql://localhost:3306/ragdoll?autoReconnect=true&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC",
                                    user,
                                    password
                                );

                                Statement stmt = con.createStatement();
                                ResultSet rs = stmt.executeQuery("SELECT model_id, model_name, access_level FROM models");

                                while (rs.next()) {
                                    String modelName = rs.getString("model_name");
                                    String access_level = rs.getString("access_level");
                                    out.println("<option value=\"" + rs.getInt("model_id") + "\">" + modelName + " - " + access_level + "</option>");
                                }

                                rs.close();
                                stmt.close();
                                con.close();
                            } catch (SQLException e) {
                                out.println("<option value=\"error\">SQL Error</option>");
                            } catch (ClassNotFoundException e) {
                                out.println("<option value=\"error\">Driver Error</option>");
                            }
                        %>
                    </select>
                </div>
                <button class="upgrade-btn">Upgrade</button>
            </header>

            <div class="chat-container empty-state">
                <div style="max-width: 500px;">
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
                <div class="input-box">
                    <span class="plus-btn">+</span>
                    <input type="text" placeholder="Type here" />
                </div>
            </div>
        </main>
    </div>
</body>
</html>