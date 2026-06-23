package application;

import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;

import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class HomeServlet extends HttpServlet {

    private static final String DB_URL =
        "jdbc:mysql://localhost:3306/ragdoll?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC";

    private static final String DB_USER = "root";

    // Change this to your real MySQL password
    private static final String DB_PASSWORD = "YOUR_MYSQL_PASSWORD";

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {

        ArrayList<String[]> models = new ArrayList<String[]>();

        try {
            Class.forName("com.mysql.cj.jdbc.Driver");

            Connection connection = DriverManager.getConnection(DB_URL, DB_USER, DB_PASSWORD);
            Statement statement = connection.createStatement();
            ResultSet resultSet = statement.executeQuery("SELECT model_name, access_level FROM models");

            while (resultSet.next()) {
                String[] model = new String[2];
                model[0] = resultSet.getString("model_name");
                model[1] = resultSet.getString("access_level");
                models.add(model);
            }

            resultSet.close();
            statement.close();
            connection.close();

            request.setAttribute("status", "Database connected successfully.");
            request.setAttribute("models", models);

        } catch (Exception e) {
            request.setAttribute("status", "Database connection failed: " + e.getMessage());
        }

        request.getRequestDispatcher("/index.jsp").forward(request, response);
    }
}