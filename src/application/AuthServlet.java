package application;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.regex.Pattern;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.HttpSession;

// le auth serverlet
public class AuthServlet extends HttpServlet {

    private static final String DB_URL =
        "jdbc:mysql://localhost:3306/ragdoll_db?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC";
    private static final String DB_USER = "root";
    // gets it from sys ENV
    private static final String DB_PASSWORD = System.getenv("DB_PASSWORD");

    // got from google
    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[A-Za-z0-9_]{3,50}$");
    private static final Pattern EMAIL_PATTERN = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");

    // i'm using a more advanced sha256 hashing algorithm so it needs these params
    private static final int PBKDF2_ITERATIONS = 120_000;
    private static final int KEY_LENGTH_BITS = 256;
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        handle(request, response);
    }

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String action = request.getParameter("action");
        if ("logout".equals(action)) {
            handleLogout(request, response);
            return;
        }

        if ("signup".equals(action)) {
            response.sendRedirect(request.getContextPath() + "/views/signup.jsp");
            return;
        }

        if ("login".equals(action) && "true".equals(request.getParameter("admin_required"))) {
            response.sendRedirect(request.getContextPath() + "/views/login.jsp?admin_required=true");
            return;
        }

        response.sendRedirect(request.getContextPath() + "/views/login.jsp");
    }

    private void handle(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String action = request.getParameter("action");
        if ("signup".equals(action)) {
            handleSignup(request, response);
        } else if ("login".equals(action)) {
            handleLogin(request, response);
        } else if ("logout".equals(action)) {
            handleLogout(request, response);
        } else {
            response.sendRedirect(request.getContextPath() + "/views/login.jsp");
        }
    }

    // signup endpoint handleing

    private void handleSignup(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String username = trim(request.getParameter("username"));
        String email = trim(request.getParameter("email"));
        String password = request.getParameter("password");
        String confirmPassword = request.getParameter("confirm_password");

        String validationError = validateSignup(username, email, password, confirmPassword);
        if (validationError != null) {
            forwardWithError(request, response, "/views/signup.jsp", validationError);
            return;
        }

        try (Connection connection = getConnection()) {
            connection.setAutoCommit(false);
            try {
                AccountConflict conflict = getAccountConflict(connection, username, email);
                if (conflict == AccountConflict.EMAIL) {
                    connection.rollback();
                    forwardWithError(
                        request, response, "/views/signup.jsp",
                        "This email is already registered."
                    );
                    return;
                }
                if (conflict == AccountConflict.USERNAME) {
                    connection.rollback();
                    forwardWithError(
                        request, response, "/views/signup.jsp",
                        "That username is already taken."
                    );
                    return;
                }

                int userId = nextId(connection, "Users", "user_id");
                String salt = generateSalt();
                String passwordHash = hashPassword(password, salt);

                try (PreparedStatement statement = connection.prepareStatement(
                        "INSERT INTO Users (user_id, username, email, created_at) "
                        + "VALUES (?, ?, ?, NOW())")) {
                    statement.setInt(1, userId);
                    statement.setString(2, username);
                    statement.setString(3, email);
                    statement.executeUpdate();
                }

                try (PreparedStatement statement = connection.prepareStatement(
                        "INSERT INTO User_Hashes (user_id, password_hash, salt) "
                        + "VALUES (?, ?, ?)")) {
                    statement.setInt(1, userId);
                    statement.setString(2, passwordHash);
                    statement.setString(3, salt);
                    statement.executeUpdate();
                }

                Integer freeTierId = findTierId(connection, "Free");
                if (freeTierId != null) {
                    try (PreparedStatement statement = connection.prepareStatement(
                            "INSERT INTO Has (user_id, tier_id, assigned_at) VALUES (?, ?, NOW())")) {
                        statement.setInt(1, userId);
                        statement.setInt(2, freeTierId);
                        statement.executeUpdate();
                    }
                }

                insertAuditLog(connection, userId, "New account created: " + username, "SIGNUP");
                connection.commit();

                HttpSession oldSession = request.getSession(false);
                if (oldSession != null) {
                    oldSession.invalidate();
                }
                HttpSession session = request.getSession(true);
                session.setAttribute("userId", Integer.valueOf(userId));
                session.setAttribute("username", username);
                session.setAttribute("userDisplayName", username);
                session.setAttribute("userTier", "Free");
                response.sendRedirect(request.getContextPath() + "/views/dashboard.jsp");
            } catch (Exception error) {
                connection.rollback();
                throw error;
            }
        } catch (Exception error) {
            forwardWithError(
                request, response, "/views/signup.jsp",
                "Unable to create the account right now. Please try again."
            );
        }
    }

    private String validateSignup(
            String username, String email, String password, String confirmPassword) {
        if (username == null || !USERNAME_PATTERN.matcher(username).matches()) {
            return "Username must be 3-50 characters and use only letters, numbers, and underscores.";
        }
        if (email == null || email.length() > 100 || !EMAIL_PATTERN.matcher(email).matches()) {
            return "Enter a valid email address.";
        }
        if (password == null || password.length() < 8) {
            return "Password must be at least 8 characters.";
        }
        if (!password.equals(confirmPassword)) {
            return "Passwords do not match.";
        }
        return null;
    }

    // ---- Login ----

    private void handleLogin(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String email = trim(request.getParameter("email"));
        String password = request.getParameter("password");

        if (email == null || email.isEmpty() || password == null || password.isEmpty()) {
            forwardWithError(request, response, "/views/login.jsp", "Enter your email and password.");
            return;
        }

        try (Connection connection = getConnection()) {
            Integer userId = null;
            String username = null;
            String storedHash = null;
            String salt = null;

            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT u.user_id, u.username, h.password_hash, h.salt "
                    + "FROM Users u JOIN User_Hashes h ON h.user_id = u.user_id "
                    + "WHERE u.email = ?")) {
                statement.setString(1, email);
                try (ResultSet resultSet = statement.executeQuery()) {
                    if (resultSet.next()) {
                        userId = Integer.valueOf(resultSet.getInt("user_id"));
                        username = resultSet.getString("username");
                        storedHash = resultSet.getString("password_hash");
                        salt = resultSet.getString("salt");
                    }
                }
            }

            if (userId == null) {
                forwardWithError(request, response, "/views/login.jsp", "No account was found for that email.");
                return;
            }

            if (salt == null || !verifyPassword(password, salt, storedHash)) {
                forwardWithError(request, response, "/views/login.jsp", "Incorrect password.");
                return;
            }

            String adminCompanyId = null;
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT company_id FROM Admins WHERE user_id = ?")) {
                statement.setInt(1, userId.intValue());
                try (ResultSet resultSet = statement.executeQuery()) {
                    if (resultSet.next()) {
                        adminCompanyId = resultSet.getString("company_id");
                    }
                }
            }

            HttpSession oldSession = request.getSession(false);
            if (oldSession != null) {
                oldSession.invalidate();
            }
            HttpSession session = request.getSession(true);

            if (adminCompanyId != null) {
                session.setAttribute("adminUserId", userId);
                session.setAttribute("adminDisplayName", username);
                session.setAttribute("adminCompanyId", adminCompanyId);
                insertAuditLogAutoCommit(
                    connection, userId.intValue(), username + " logged in as administrator", "LOGIN"
                );
                response.sendRedirect(request.getContextPath() + "/views/admin.jsp");
                return;
            }

            String tierName = findCurrentTierName(connection, userId.intValue());
            session.setAttribute("userId", userId);
            session.setAttribute("username", username);
            session.setAttribute("userDisplayName", username);
            session.setAttribute("userTier", tierName == null ? "Free" : tierName);
            insertAuditLogAutoCommit(connection, userId.intValue(), username + " logged in", "LOGIN");
            response.sendRedirect(request.getContextPath() + "/views/dashboard.jsp");
        } catch (Exception error) {
            forwardWithError(
                request, response, "/views/login.jsp",
                "Unable to log in right now. Please try again."
            );
        }
    }

    // logout

    private void handleLogout(HttpServletRequest request, HttpServletResponse response)
            throws IOException {
        HttpSession session = request.getSession(false);
        if (session != null) {
            session.invalidate();
        }
        response.sendRedirect(request.getContextPath() + "/views/login.jsp?status=signed_out");
    }

    // helper functions

    private void forwardWithError(
            HttpServletRequest request, HttpServletResponse response,
            String page, String errorMessage) throws ServletException, IOException {
        request.setAttribute("errorMessage", errorMessage);
        request.getRequestDispatcher(page).forward(request, response);
    }

    private Connection getConnection() throws SQLException {
        try {
            Class.forName("com.mysql.cj.jdbc.Driver");
        } catch (ClassNotFoundException error) {
            throw new SQLException("MySQL driver not found.", error);
        }
        return DriverManager.getConnection(DB_URL, DB_USER, DB_PASSWORD);
    }

    private enum AccountConflict {
        NONE,
        USERNAME,
        EMAIL
    }

    private AccountConflict getAccountConflict(Connection connection, String username, String email)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT username, email FROM Users WHERE username = ? OR email = ?")) {
            statement.setString(1, username);
            statement.setString(2, email);
            try (ResultSet resultSet = statement.executeQuery()) {
                boolean usernameTaken = false;
                boolean emailTaken = false;
                while (resultSet.next()) {
                    String existingUsername = resultSet.getString("username");
                    String existingEmail = resultSet.getString("email");
                    if (existingUsername != null && existingUsername.equalsIgnoreCase(username)) {
                        usernameTaken = true;
                    }
                    if (existingEmail != null && existingEmail.equalsIgnoreCase(email)) {
                        emailTaken = true;
                    }
                }

                if (emailTaken) {
                    return AccountConflict.EMAIL;
                }
                if (usernameTaken) {
                    return AccountConflict.USERNAME;
                }
                return AccountConflict.NONE;
            }
        }
    }

    private Integer findTierId(Connection connection, String tierName) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT tier_id FROM Tiers WHERE LOWER(tier_name) = LOWER(?) ORDER BY tier_id LIMIT 1")) {
            statement.setString(1, tierName);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? Integer.valueOf(resultSet.getInt("tier_id")) : null;
            }
        }
    }

    private String findCurrentTierName(Connection connection, int userId) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT t.tier_name FROM Payments p JOIN Tiers t ON t.tier_id = p.tier_id "
                + "WHERE p.user_id = ? ORDER BY p.payment_date DESC, p.payment_id DESC LIMIT 1")) {
            statement.setInt(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? resultSet.getString("tier_name") : null;
            }
        }
    }

    private int nextId(Connection connection, String table, String column) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT COALESCE(MAX(" + column + "), 0) + 1 AS next_id FROM " + table)) {
            try (ResultSet resultSet = statement.executeQuery()) {
                resultSet.next();
                return resultSet.getInt("next_id");
            }
        }
    }

    private void insertAuditLog(Connection connection, int userId, String actionLog, String actionType)
            throws SQLException {
        int logId = nextId(connection, "Audit_Log", "log_id");
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO Audit_Log (log_id, user_id, action_log, action_type, action_date) "
                + "VALUES (?, ?, ?, ?, NOW())")) {
            statement.setInt(1, logId);
            statement.setInt(2, userId);
            statement.setString(3, truncate(actionLog, 255));
            statement.setString(4, truncate(actionType, 50));
            statement.executeUpdate();
        }
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO Triggers (user_id, log_id) VALUES (?, ?)")) {
            statement.setInt(1, userId);
            statement.setInt(2, logId);
            statement.executeUpdate();
        }
    }

    private void insertAuditLogAutoCommit(
            Connection connection, int userId, String actionLog, String actionType) {
        try {
            insertAuditLog(connection, userId, actionLog, actionType);
        } catch (SQLException ignored) {
            // Login still succeeds even when the audit trail cannot be written.
        }
    }

    private String truncate(String value, int maxLength) {
        if (value == null) {
            return "";
        }
        return value.length() > maxLength ? value.substring(0, maxLength) : value;
    }

    private String trim(String value) {
        return value == null ? null : value.trim();
    }

    private String generateSalt() {
        byte[] saltBytes = new byte[16];
        SECURE_RANDOM.nextBytes(saltBytes);
        return toHex(saltBytes);
    }

    private boolean verifyPassword(String password, String saltHex, String expectedHashHex)
            throws GeneralSecurityException {
        String candidate = hashPassword(password, saltHex);
        return MessageDigest.isEqual(
            candidate.getBytes(StandardCharsets.US_ASCII),
            expectedHashHex.getBytes(StandardCharsets.US_ASCII)
        );
    }

    private String hashPassword(String password, String saltHex) throws GeneralSecurityException {
        byte[] salt = fromHex(saltHex);
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, PBKDF2_ITERATIONS, KEY_LENGTH_BITS);
        SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
        byte[] hash = factory.generateSecret(spec).getEncoded();
        return toHex(hash);
    }

    private static String toHex(byte[] bytes) {
        StringBuilder builder = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            builder.append(String.format("%02x", Byte.valueOf(value)));
        }
        return builder.toString();
    }

    private static byte[] fromHex(String hex) {
        int length = hex.length();
        byte[] data = new byte[length / 2];
        for (int i = 0; i < length; i += 2) {
            data[i / 2] = (byte) (
                (Character.digit(hex.charAt(i), 16) << 4)
                + Character.digit(hex.charAt(i + 1), 16)
            );
        }
        return data;
    }
}
