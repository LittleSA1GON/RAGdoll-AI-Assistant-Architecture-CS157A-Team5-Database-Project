package application;

import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;

import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class HomeServlet extends HttpServlet {

    private static final String DB_URL =
        "jdbc:mysql://localhost:3306/ragdoll_db?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC";

    private static final String DB_USER = "root";
    private static final String DB_PASSWORD = System.getenv("DB_PASSWORD");

    private void ensureAvailabilityColumn(Connection connection) throws SQLException {
        try (
            PreparedStatement check = connection.prepareStatement(
                "SHOW COLUMNS FROM Models LIKE 'is_available'"
            );
            ResultSet columns = check.executeQuery()
        ) {
            if (columns.next()) {
                return;
            }
        }

        try (PreparedStatement alter = connection.prepareStatement(
            "ALTER TABLE Models " +
            "ADD COLUMN is_available TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled"
        )) {
            alter.executeUpdate();
        }
    }

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {

        ArrayList<String[]> models = new ArrayList<String[]>();

        try {
            Class.forName("com.mysql.cj.jdbc.Driver");

            try (Connection connection = DriverManager.getConnection(DB_URL, DB_USER, DB_PASSWORD)) {
                ensureAvailabilityColumn(connection);

                try (
                    PreparedStatement statement = connection.prepareStatement(
                        "SELECT model_id, model_name, model_path " +
                        "FROM Models WHERE model_location = 'local' " +
                        "AND is_enabled = 1 AND is_available = 1"
                    );
                    ResultSet resultSet = statement.executeQuery()
                ) {
                    while (resultSet.next()) {
                        String[] model = new String[3];
                        model[0] = String.valueOf(resultSet.getInt("model_id"));
                        model[1] = resultSet.getString("model_name");
                        model[2] = resultSet.getString("model_path");
                        models.add(model);
                    }
                }
            }

            request.setAttribute("status", "Database connected successfully.");
            request.setAttribute("models", models);

        } catch (Exception e) {
            request.setAttribute("status", "Database connection failed: " + e.getMessage());
            request.setAttribute("models", models);
        }

        request.getRequestDispatcher("/index.jsp").forward(request, response);
    }
}