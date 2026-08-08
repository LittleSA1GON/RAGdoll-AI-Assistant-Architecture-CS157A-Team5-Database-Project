package application;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Provides simulated payment and tier upgrade behavior using MySQL only. */
public final class PaymentService
{
    public Map<String, Object> userTiers(int userId) throws SQLException
    {
        return new PaymentRepository().userTiers(userId);
    }

    public Map<String, Object> upgradeTier(int userId, int tierId) throws SQLException
    {
        return new PaymentRepository().upgradeTier(userId, tierId);
    }
}

final class PaymentRepository
{
    public Map<String, Object> userTiers(int userId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            verifyUser(connection, userId);
            Map<String, Object> currentTier = currentTier(connection, userId);
            List<Map<String, Object>> tiers;
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT tier_id, tier_name, price FROM Tiers ORDER BY tier_id"))
            {
                tiers = Database.rows(statement);
            }
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT p.payment_id, p.tier_id, t.tier_name, t.price, p.status, p.payment_date "
                            + "FROM Payments p JOIN Tiers t ON t.tier_id = p.tier_id "
                            + "WHERE p.user_id = ? ORDER BY p.payment_date DESC, p.payment_id DESC"))
            {
                statement.setInt(1, userId);
                List<Map<String, Object>> history = Database.rows(statement);
                Map<String, Object> response = new LinkedHashMap<>();
                response.put("user_id", userId);
                response.put("current_tier", currentTier == null ? Map.of() : currentTier);
                response.put("tiers", tiers);
                response.put("payment_history", history);
                return response;
            }
        }
    }

    public Map<String, Object> upgradeTier(int userId, int tierId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                verifyUser(connection, userId);
                Map<String, Object> tier = tierById(connection, tierId);
                String tierName = String.valueOf(tier.get("tier_name"));
                double price = ((Number) tier.get("price")).doubleValue();
                String status = price > 0.0 ? "Completed" : "Free Tier";

                int paymentId = Database.nextId(connection, "Payments", "payment_id");
                try (PreparedStatement insert = connection.prepareStatement(
                        "INSERT INTO Payments (payment_id, user_id, tier_id, status, payment_date) VALUES (?, ?, ?, ?, NOW())"))
                {
                    insert.setInt(1, paymentId);
                    insert.setInt(2, userId);
                    insert.setInt(3, tierId);
                    insert.setString(4, status);
                    insert.executeUpdate();
                }
                try (PreparedStatement insert = connection.prepareStatement(
                        "INSERT INTO Pays (user_id, payment_id) VALUES (?, ?)") )
                {
                    insert.setInt(1, userId);
                    insert.setInt(2, paymentId);
                    insert.executeUpdate();
                }
                try (PreparedStatement insert = connection.prepareStatement(
                        "INSERT INTO Sets (tier_id, payment_id) VALUES (?, ?)") )
                {
                    insert.setInt(1, tierId);
                    insert.setInt(2, paymentId);
                    insert.executeUpdate();
                }

                if (hasTierAssignment(connection, userId, tierId))
                {
                    try (PreparedStatement update = connection.prepareStatement(
                            "UPDATE Has SET assigned_at = NOW() WHERE user_id = ? AND tier_id = ?"))
                    {
                        update.setInt(1, userId);
                        update.setInt(2, tierId);
                        update.executeUpdate();
                    }
                }
                else
                {
                    try (PreparedStatement insert = connection.prepareStatement(
                            "INSERT INTO Has (user_id, tier_id, assigned_at) VALUES (?, ?, NOW())"))
                    {
                        insert.setInt(1, userId);
                        insert.setInt(2, tierId);
                        insert.executeUpdate();
                    }
                }

                insertAuditLog(connection, userId, "Simulated payment recorded for " + tierName, "PAYMENT");
                connection.commit();

                return Map.of(
                        "payment_id", paymentId,
                        "tier_id", tierId,
                        "tier_name", tierName,
                        "price", price,
                        "status", status);
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    private void verifyUser(Connection connection, int userId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT user_id FROM Users WHERE user_id = ?"))
        {
            statement.setInt(1, userId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    throw new IllegalArgumentException("User not found.");
                }
            }
        }
    }

    private Map<String, Object> tierById(Connection connection, int tierId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT tier_id, tier_name, price FROM Tiers WHERE tier_id = ?"))
        {
            statement.setInt(1, tierId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    throw new IllegalArgumentException("Tier " + tierId + " was not found.");
                }
                Map<String, Object> tier = new LinkedHashMap<>();
                tier.put("tier_id", rows.getInt("tier_id"));
                tier.put("tier_name", rows.getString("tier_name"));
                tier.put("price", rows.getDouble("price"));
                return tier;
            }
        }
    }

    private boolean hasTierAssignment(Connection connection, int userId, int tierId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT 1 FROM Has WHERE user_id = ? AND tier_id = ?"))
        {
            statement.setInt(1, userId);
            statement.setInt(2, tierId);
            try (ResultSet rows = statement.executeQuery())
            {
                return rows.next();
            }
        }
    }

    private Map<String, Object> currentTier(Connection connection, int userId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT t.tier_id, t.tier_name, t.price FROM Has h JOIN Tiers t ON t.tier_id = h.tier_id "
                        + "WHERE h.user_id = ? ORDER BY h.assigned_at DESC LIMIT 1"))
        {
            statement.setInt(1, userId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    return null;
                }
                Map<String, Object> tier = new LinkedHashMap<>();
                tier.put("tier_id", rows.getInt("tier_id"));
                tier.put("tier_name", rows.getString("tier_name"));
                tier.put("price", rows.getDouble("price"));
                return tier;
            }
        }
    }

    private void insertAuditLog(Connection connection, int userId, String actionLog, String actionType) throws SQLException
    {
        int logId = Database.nextId(connection, "Audit_Log", "log_id");
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO Audit_Log (log_id, user_id, action_log, action_type, action_date) VALUES (?, ?, ?, ?, NOW())"))
        {
            statement.setInt(1, logId);
            statement.setInt(2, userId);
            statement.setString(3, truncate(actionLog, 255));
            statement.setString(4, truncate(actionType, 50));
            statement.executeUpdate();
        }
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Triggers (user_id, log_id) VALUES (?, ?)") )
        {
            statement.setInt(1, userId);
            statement.setInt(2, logId);
            statement.executeUpdate();
        }
    }

    private String truncate(String value, int maximum)
    {
        String text = value == null ? "" : value;
        return text.length() <= maximum ? text : text.substring(0, maximum);
    }
}
