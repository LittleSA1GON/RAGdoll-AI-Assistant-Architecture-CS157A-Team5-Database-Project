package application;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import javax.servlet.http.Part;

/** Administrator tiers, audit logs, and RAG document management. */
public final class AdminService
{
    private final AdminRepository admins = new AdminRepository();
    private final AdminAuditRepository audit = new AdminAuditRepository(admins);
    private final AdminTierRepository tiers = new AdminTierRepository(admins, audit);
    private final DocumentRepository documents = new DocumentRepository(admins);
    private final DocumentService files;

    public AdminService(PythonModelClient python)
    {
        files = new DocumentService(documents, audit, python);
    }

    public Map<String, Object> listTiers(int adminId) throws SQLException
    {
        return tiers.list(adminId);
    }

    public Map<String, Object> updateTier(int adminId, int tierId, double price, List<Integer> modelIds) throws SQLException
    {
        return tiers.update(adminId, tierId, price, modelIds);
    }

    public List<Map<String, Object>> listAudit(int adminId, int limit) throws SQLException
    {
        return audit.list(adminId, limit);
    }

    public List<Map<String, Object>> listDocuments(int adminId) throws SQLException
    {
        return documents.list(adminId);
    }

    public Map<String, Object> findDocument(int adminId, int documentId) throws SQLException
    {
        return documents.find(adminId, documentId);
    }

    public Map<String, Object> uploadDocument(int adminId, Part part) throws Exception
    {
        return files.uploadForAdmin(adminId, part);
    }

    public Map<String, Object> deleteDocument(int adminId, int documentId) throws Exception
    {
        return files.deleteForAdmin(adminId, documentId);
    }

    public Path downloadPath(int adminId, int documentId) throws SQLException, IOException
    {
        return files.downloadPath(adminId, documentId);
    }
}

/**
 * Verifies administrator identities for admin-only repositories and services.
 */
final class AdminRepository
{
    public void verify(Connection connection, int adminId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT user_id FROM Admins WHERE user_id = ?"))
        {
            statement.setInt(1, adminId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    throw new SecurityException("Administrator access is required.");
                }
            }
        }
    }
}

/**
 * Java-only SQL for administrator audit-log access and admin action records.
 */
final class AdminAuditRepository
{
    private final AdminRepository admins;

    public AdminAuditRepository(AdminRepository admins)
    {
        this.admins = admins;
    }

    public List<Map<String, Object>> list(int adminId, int limit) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            admins.verify(connection, adminId);
            try (PreparedStatement statement = connection
                    .prepareStatement("SELECT a.log_id, a.user_id, u.username, a.action_log, a.action_type, a.action_date FROM"
                            + " Audit_Log a LEFT JOIN Users u ON u.user_id = a.user_id ORDER BY" + " a.action_date DESC, a.log_id DESC"))
            {
                List<Map<String, Object>> rows = Database.rows(statement);
                for (Map<String, Object> row : rows)
                {
                    if (row.get("username") == null)
                    {
                        row.put("username", "Deleted user");
                    }
                }
                int maximum = Math.max(1, Math.min(500, limit));
                return new ArrayList<>(rows.subList(0, Math.min(rows.size(), maximum)));
            }
        }
    }

    public void record(int adminId, String action, String type) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                admins.verify(connection, adminId);
                insert(connection, adminId, action, type);
                connection.commit();
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    void insert(Connection connection, int adminId, String action, String type) throws SQLException
    {
        int logId = Database.nextId(connection, "Audit_Log", "log_id");
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Audit_Log VALUES (?, ?, ?, ?, ?)"))
        {
            statement.setInt(1, logId);
            statement.setInt(2, adminId);
            statement.setString(3, truncate(action, 255));
            statement.setString(4, truncate(type, 50));
            statement.setTimestamp(5, new Timestamp(System.currentTimeMillis()));
            statement.executeUpdate();
        }
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Triggers VALUES (?, ?)"))
        {
            statement.setInt(1, adminId);
            statement.setInt(2, logId);
            statement.executeUpdate();
        }
    }

    private String truncate(String value, int maximum)
    {
        String text = value == null ? "" : value;
        return text.substring(0, Math.min(text.length(), maximum));
    }
}

/**
 * Java-only SQL for administrator tier pricing and model-access configuration.
 */
final class AdminTierRepository
{
    private final AdminRepository admins;
    private final AdminAuditRepository audit;

    public AdminTierRepository(AdminRepository admins, AdminAuditRepository audit)
    {
        this.admins = admins;
        this.audit = audit;
    }

    public Map<String, Object> list(int adminId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            admins.verify(connection, adminId);
            List<Map<String, Object>> tiers = query(connection, "SELECT tier_id, tier_name, price FROM Tiers ORDER BY tier_id");
            List<Map<String, Object>> models = query(connection, "SELECT model_id, model_name, model_type, model_path, model_location,"
                    + " server_model_id, is_enabled, is_available FROM Models ORDER BY" + " model_id");
            List<Map<String, Object>> access = query(connection, "SELECT tier_id, model_id FROM Access ORDER BY tier_id, model_id");

            for (Map<String, Object> tier : tiers)
            {
                int tierId = ((Number) tier.get("tier_id")).intValue();
                List<Integer> modelIds = new ArrayList<>();
                for (Map<String, Object> row : access)
                {
                    if (((Number) row.get("tier_id")).intValue() == tierId)
                    {
                        modelIds.add(((Number) row.get("model_id")).intValue());
                    }
                }
                tier.put("model_ids", modelIds);
            }
            return Map.of("tiers", tiers, "models", models);
        }
    }

    public synchronized Map<String, Object> update(int adminId, int tierId, double price, List<Integer> modelIds) throws SQLException
    {
        if (price < 0 || price > 999999.99)
        {
            throw new IllegalArgumentException("Tier price must be between 0 and 999999.99.");
        }
        List<Integer> uniqueModelIds = modelIds.stream().distinct().sorted().toList();
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                admins.verify(connection, adminId);
                String tierName = tierName(connection, tierId);
                for (int modelId : uniqueModelIds)
                {
                    verifyModel(connection, modelId);
                }

                try (PreparedStatement statement = connection.prepareStatement("UPDATE Tiers SET price = ? WHERE tier_id = ?"))
                {
                    statement.setDouble(1, roundPrice(price));
                    statement.setInt(2, tierId);
                    statement.executeUpdate();
                }
                try (PreparedStatement statement = connection.prepareStatement("DELETE FROM Access WHERE tier_id = ?"))
                {
                    statement.setInt(1, tierId);
                    statement.executeUpdate();
                }
                try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Access (tier_id, model_id) VALUES (?, ?)"))
                {
                    for (int modelId : uniqueModelIds)
                    {
                        statement.setInt(1, tierId);
                        statement.setInt(2, modelId);
                        statement.addBatch();
                    }
                    statement.executeBatch();
                }

                audit.insert(connection, adminId, "Admin updated " + tierName + " tier", "UPDATE_TIER");
                connection.commit();

                Map<String, Object> tier = new LinkedHashMap<>();
                tier.put("tier_id", tierId);
                tier.put("tier_name", tierName);
                tier.put("price", roundPrice(price));
                tier.put("model_ids", uniqueModelIds);
                return tier;
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    private List<Map<String, Object>> query(Connection connection, String sql) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement(sql))
        {
            return Database.rows(statement);
        }
    }

    private String tierName(Connection connection, int tierId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT tier_name FROM Tiers WHERE tier_id = ?"))
        {
            statement.setInt(1, tierId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    throw new IllegalArgumentException("Tier " + tierId + " was not found.");
                }
                return rows.getString(1);
            }
        }
    }

    private void verifyModel(Connection connection, int modelId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT model_id FROM Models WHERE model_id = ?"))
        {
            statement.setInt(1, modelId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                {
                    throw new IllegalArgumentException("Model " + modelId + " was not found.");
                }
            }
        }
    }

    private double roundPrice(double price)
    {
        return Math.round(price * 100.0) / 100.0;
    }
}

/** Java-only SQL for uploaded documents, chunks, and embedding vectors. */
final class DocumentRepository
{
    private final AdminRepository admins;

    public DocumentRepository(AdminRepository admins)
    {
        this.admins = admins;
    }

    public synchronized int begin(int ownerId, Integer managingAdminId, String fileName, String fileType) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                verifyUser(connection, ownerId);
                if (managingAdminId != null)
                    admins.verify(connection, managingAdminId);
                int id = Database.nextId(connection, "Documents", "document_id");
                Timestamp uploadedAt = new Timestamp(System.currentTimeMillis());
                try (PreparedStatement statement = connection.prepareStatement(
                        "INSERT INTO Documents (document_id, user_id, file_name, file_type," + " file_path, processing_status, processing_error,"
                                + " rag_access_scope, uploaded_at) VALUES (?, ?, ?, ?, NULL," + " 'processing', NULL, 'all_users', ?)"))
                {
                    statement.setInt(1, id);
                    statement.setInt(2, ownerId);
                    statement.setString(3, fileName);
                    statement.setString(4, fileType);
                    statement.setTimestamp(5, uploadedAt);
                    statement.executeUpdate();
                }
                if (managingAdminId != null)
                {
                    try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Manages VALUES (?, ?, ?)"))
                    {
                        statement.setInt(1, managingAdminId);
                        statement.setInt(2, id);
                        statement.setTimestamp(3, uploadedAt);
                        statement.executeUpdate();
                    }
                }
                connection.commit();
                return id;
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    public void setPath(int documentId, String path) throws SQLException
    {
        update("UPDATE Documents SET file_path = ? WHERE document_id = ?", path, documentId);
    }

    public synchronized void complete(int documentId, List<?> chunks, List<?> embeddings, String model, int dimension) throws SQLException
    {
        if (chunks.size() != embeddings.size())
            throw new IllegalArgumentException("Chunk and vector counts differ.");
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                int nextId = Database.nextId(connection, "Chunks", "chunk_id");
                Timestamp embeddedAt = new Timestamp(System.currentTimeMillis());
                for (int index = 0; index < chunks.size(); index++)
                {
                    int chunkId = nextId + index;
                    try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Chunks VALUES (?, ?, ?, ?, ?, ?, ?)"))
                    {
                        statement.setInt(1, chunkId);
                        statement.setInt(2, documentId);
                        statement.setString(3, String.valueOf(chunks.get(index)));
                        statement.setString(4, Json.stringify(embeddings.get(index)));
                        statement.setString(5, model);
                        statement.setInt(6, dimension);
                        statement.setTimestamp(7, embeddedAt);
                        statement.executeUpdate();
                    }
                    try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Splits_Into VALUES (?, ?)"))
                    {
                        statement.setInt(1, documentId);
                        statement.setInt(2, chunkId);
                        statement.executeUpdate();
                    }
                }
                try (PreparedStatement statement = connection
                        .prepareStatement("UPDATE Documents SET processing_status = 'ready', processing_error" + " = NULL WHERE document_id = ?"))
                {
                    statement.setInt(1, documentId);
                    statement.executeUpdate();
                }
                connection.commit();
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    public void fail(int documentId, String error) throws SQLException
    {
        update("UPDATE Documents SET processing_status = 'failed', processing_error = ? WHERE" + " document_id = ?",
                error.substring(0, Math.min(error.length(), 4000)), documentId);
    }

    /**
     * Administrators can review every uploaded document, regardless of its owner.
     */
    public List<Map<String, Object>> list(int adminId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            admins.verify(connection, adminId);
            try (PreparedStatement statement = connection.prepareStatement("SELECT d.document_id, d.user_id, u.username, d.file_name, d.file_type,"
                    + " d.file_path, d.processing_status, d.processing_error," + " d.uploaded_at, COUNT(c.chunk_id) chunk_count,"
                    + " MAX(c.embedding_model) embedding_model," + " MAX(c.embedding_dimension) embedding_dimension FROM Documents d"
                    + " JOIN Users u ON u.user_id = d.user_id LEFT JOIN Chunks c ON" + " c.document_id = d.document_id GROUP BY d.document_id,"
                    + " d.user_id, u.username, d.file_name, d.file_type, d.file_path," + " d.processing_status, d.processing_error, d.uploaded_at ORDER BY"
                    + " d.uploaded_at DESC"))
            {
                return Database.rows(statement);
            }
        }
    }

    public Map<String, Object> find(int adminId, int documentId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            admins.verify(connection, adminId);
            try (PreparedStatement statement = connection
                    .prepareStatement("SELECT d.document_id, d.file_name, d.file_path FROM Documents d " + "WHERE d.document_id = ?"))
            {
                statement.setInt(1, documentId);
                List<Map<String, Object>> rows = Database.rows(statement);
                if (rows.isEmpty())
                    throw new IllegalArgumentException("Document " + documentId + " was not found.");
                return rows.get(0);
            }
        }
    }

    public synchronized Map<String, Object> delete(int adminId, int documentId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                admins.verify(connection, adminId);
                Map<String, Object> document = delete(connection, documentId);
                connection.commit();
                return document;
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    private Map<String, Object> delete(Connection connection, int documentId) throws SQLException
    {
        Map<String, Object> document;
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT d.document_id, d.file_name, d.file_path, COUNT(c.chunk_id)" + " chunk_count FROM Documents d LEFT JOIN Chunks c ON c.document_id ="
                        + " d.document_id WHERE d.document_id = ? GROUP BY d.document_id," + " d.file_name, d.file_path"))
        {
            statement.setInt(1, documentId);
            List<Map<String, Object>> rows = Database.rows(statement);
            if (rows.isEmpty())
                throw new IllegalArgumentException("Document " + documentId + " was not found.");
            document = new LinkedHashMap<>(rows.get(0));
        }
        try (PreparedStatement statement = connection.prepareStatement("DELETE FROM Documents WHERE document_id = ?"))
        {
            statement.setInt(1, documentId);
            statement.executeUpdate();
        }
        return document;
    }

    private void verifyUser(Connection connection, int userId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT 1 FROM Users WHERE user_id = ?"))
        {
            statement.setInt(1, userId);
            try (ResultSet row = statement.executeQuery())
            {
                if (!row.next())
                    throw new SecurityException("Login is required.");
            }
        }
    }

    private void update(String sql, String value, int id) throws SQLException
    {
        try (Connection connection = Database.open(); PreparedStatement statement = connection.prepareStatement(sql))
        {
            statement.setString(1, value);
            statement.setInt(2, id);
            statement.executeUpdate();
        }
    }
}

/**
 * Owns uploaded files and asks Python only to extract, chunk, and embed them.
 */
final class DocumentService
{
    private static final Set<String> EXTENSIONS = Set.of(".pdf", ".txt", ".md", ".docx");

    private final DocumentRepository documents;
    private final AdminAuditRepository adminAudit;
    private final PythonModelClient python;

    public DocumentService(DocumentRepository documents, AdminAuditRepository adminAudit, PythonModelClient python)
    {
        this.documents = documents;
        this.adminAudit = adminAudit;
        this.python = python;
    }

    public Map<String, Object> uploadForAdmin(int adminId, Part part) throws Exception
    {
        return upload(adminId, part);
    }

    private Map<String, Object> upload(int adminId, Part part) throws Exception
    {
        String name = safeName(part.getSubmittedFileName());
        String extension = extension(name);
        if (!EXTENSIONS.contains(extension))
        {
            throw new IllegalArgumentException("Unsupported document type. Allowed: .pdf, .txt, .md, .docx.");
        }
        long limit = Config.MAX_UPLOAD_MB * 1024L * 1024L;
        if (part.getSize() == 0)
            throw new IllegalArgumentException("The uploaded file is empty.");
        if (part.getSize() > limit)
            throw new IllegalArgumentException("The uploaded file exceeds " + Config.MAX_UPLOAD_MB + " MB.");

        int documentId = documents.begin(adminId, adminId, name, extension.substring(1).toUpperCase(Locale.ROOT));
        Path directory = Config.uploadDirectory().resolve(String.valueOf(documentId));
        Path file = directory.resolve(name).normalize();
        try
        {
            Files.createDirectories(directory);
            try (InputStream input = part.getInputStream())
            {
                Files.copy(input, file, StandardCopyOption.REPLACE_EXISTING);
            }
            documents.setPath(documentId, relative(file));
            Map<String, Object> prepared = python.prepareDocument(file);
            List<?> chunks = (List<?>) prepared.get("chunks");
            List<?> embeddings = (List<?>) prepared.get("embeddings");
            int dimension = ((Number) prepared.get("embedding_dimension")).intValue();
            String model = String.valueOf(prepared.get("embedding_model"));
            documents.complete(documentId, chunks, embeddings, model, dimension);
            try
            {
                String action = "Admin uploaded " + name + " with " + chunks.size() + " chunks";
                adminAudit.record(adminId, action, "UPLOAD_DOCUMENT");
            }
            catch (SQLException ignored)
            {
                // Document processing has already completed; audit failure is non-fatal.
            }

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("document_id", documentId);
            result.put("file_name", name);
            result.put("processing_status", "ready");
            result.put("chunk_count", chunks.size());
            result.put("embedding_dimension", dimension);
            result.put("embedding_model_name", model);
            return result;
        }
        catch (Exception error)
        {
            try
            {
                documents.fail(documentId, error.getMessage() == null ? error.toString() : error.getMessage());
            }
            catch (SQLException ignored)
            {
            }
            throw error;
        }
    }

    public Map<String, Object> deleteForAdmin(int adminId, int documentId) throws Exception
    {
        Map<String, Object> deleted = documents.delete(adminId, documentId);
        boolean fileDeleted = deleteStoredFile(documentId, deleted.get("file_path"));
        try
        {
            adminAudit.record(adminId, "Admin removed " + deleted.get("file_name"), "REMOVE_DOCUMENT");
        }
        catch (SQLException ignored)
        {
            // The deletion has already completed and should still be reported accurately.
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("deleted", true);
        result.put("document_id", documentId);
        result.put("file_name", deleted.get("file_name"));
        result.put("deleted_chunk_count", deleted.get("chunk_count"));
        result.put("file_deleted", fileDeleted);
        return result;
    }

    public Path downloadPath(int adminId, int documentId) throws SQLException, IOException
    {
        Map<String, Object> document = documents.find(adminId, documentId);
        Path path = storedPath(documentId, document.get("file_path"));
        if (!Files.isRegularFile(path))
            throw new IOException("The uploaded file is not available.");
        return path;
    }

    private boolean deleteStoredFile(int documentId, Object stored) throws IOException
    {
        if (stored == null)
            return false;
        Path path = storedPath(documentId, stored);
        boolean deleted = Files.deleteIfExists(path);
        Path directory = path.getParent();
        if (directory != null && directory.equals(Config.uploadDirectory().resolve(String.valueOf(documentId))))
        {
            try
            {
                Files.deleteIfExists(directory);
            }
            catch (java.nio.file.DirectoryNotEmptyException ignored)
            {
            }
        }
        return deleted;
    }

    private Path storedPath(int documentId, Object stored) throws IOException
    {
        if (stored == null)
            throw new IOException("Document has no stored path.");
        Path path = Path.of(String.valueOf(stored));
        if (!path.isAbsolute())
            path = Config.projectRoot().resolve(path);
        path = path.toAbsolutePath().normalize();
        Path allowed = Config.uploadDirectory().resolve(String.valueOf(documentId)).toAbsolutePath().normalize();
        if (!path.startsWith(allowed))
            throw new IOException("Stored document path is outside the upload directory.");
        return path;
    }

    private String relative(Path path)
    {
        return Config.projectRoot().relativize(path.toAbsolutePath().normalize()).toString().replace('\\', '/');
    }

    private String safeName(String supplied)
    {
        String name = supplied == null ? "document" : supplied.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1);
        name = name.replaceAll("[^A-Za-z0-9._ -]", "_").replaceAll("^[. ]+|[. ]+$", "");
        if (name.isBlank())
            name = "document";
        return name.substring(0, Math.min(180, name.length()));
    }

    private String extension(String name)
    {
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
    }
}
