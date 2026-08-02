package application;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Stream;

/** Reads environment settings and resolves project paths in one place. */
final class Config
{
    public static final String DB_URL = setting("DB_URL",
            "jdbc:mysql://localhost:3306/ragdoll_db?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC");
    public static final String DB_USER = setting("DB_USER", "root");
    public static final String DB_PASSWORD = setting("DB_PASSWORD", "");

    public static final int DEFAULT_USER_ID = integer("RAGDOLL_DEFAULT_USER_ID", 0);
    public static final int DEFAULT_ADMIN_ID = integer("RAGDOLL_DEFAULT_ADMIN_USER_ID", 20);
    public static final int MAX_UPLOAD_MB = integer("RAGDOLL_MAX_UPLOAD_MB", 25);
    public static final int RAG_TOP_K = integer("RAGDOLL_RAG_TOP_K", 4);
    public static final int RAG_MAX_CHUNKS = integer("RAGDOLL_RAG_MAX_CHUNKS", 5000);
    public static final double RAG_MIN_SIMILARITY = decimal("RAGDOLL_RAG_MIN_SIMILARITY", 0.55);
    public static final double RAG_CONTEXT_MIN_SIMILARITY = decimal("RAGDOLL_RAG_CONTEXT_MIN_SIMILARITY", 0.35);
    public static final double RAG_SCORE_MARGIN = decimal("RAGDOLL_RAG_SCORE_MARGIN", 0.08);
    public static final int MAX_HISTORY_TURNS = integer("RAGDOLL_MAX_HISTORY_TURNS", 20);
    public static final boolean RAG_ENABLED = Boolean.parseBoolean(setting("RAGDOLL_RAG_ENABLED", "true"));

    private static Path projectRoot;

    private Config()
    {
    }

    public static void setProjectRoot(Path root)
    {
        projectRoot = root.toAbsolutePath().normalize();
    }

    public static Path projectRoot()
    {
        if (projectRoot != null)
        {
            return projectRoot;
        }
        Path configured = pathSetting("RAGDOLL_PROJECT_ROOT");
        Path start = configured == null ? Paths.get(System.getProperty("user.dir", ".")).toAbsolutePath() : configured;
        for (Path current = start; current != null; current = current.getParent())
        {
            if (Files.isRegularFile(current.resolve("src/rag_pipeline/model_worker.py")))
            {
                projectRoot = current.normalize();
                return projectRoot;
            }
        }
        throw new IllegalStateException("Project root was not found. Set RAGDOLL_PROJECT_ROOT.");
    }

    public static Path modelDirectory()
    {
        Path configured = pathSetting("RAGDOLL_MODEL_DIR");
        return configured == null ? projectRoot().resolve("models/models") : configured;
    }

    public static Path uploadDirectory()
    {
        Path configured = pathSetting("RAGDOLL_UPLOAD_DIR");
        return configured == null ? projectRoot().resolve("data/uploads") : configured;
    }

    public static List<String> pythonCommand()
    {
        String configured = System.getenv("RAGDOLL_PYTHON");
        if (configured != null && !configured.isBlank())
        {
            return List.of(configured.trim());
        }
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");
        Path virtualPython = projectRoot().resolve(windows ? ".venv/Scripts/python.exe" : ".venv/bin/python");
        if (Files.isRegularFile(virtualPython))
        {
            return List.of(virtualPython.toString());
        }
        return List.of(windows ? "python" : "python3");
    }

    private static String setting(String name, String fallback)
    {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private static int integer(String name, int fallback)
    {
        return Integer.parseInt(setting(name, String.valueOf(fallback)));
    }

    private static double decimal(String name, double fallback)
    {
        return Double.parseDouble(setting(name, String.valueOf(fallback)));
    }

    private static Path pathSetting(String name)
    {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? null : Paths.get(value).toAbsolutePath().normalize();
    }
}

/**
 * Shared JDBC helpers. Every SQL statement lives in a Java repository class.
 */
final class Database
{
    static
    {
        try
        {
            // Every repository closes connections with try-with-resources. Disabling
            // Connector/J's global cleanup thread prevents a class-loader leak when
            // Tomcat reloads this web application.
            System.setProperty("com.mysql.cj.disableAbandonedConnectionCleanup", "true");
            Class.forName("com.mysql.cj.jdbc.Driver");
        }
        catch (ClassNotFoundException error)
        {
            throw new ExceptionInInitializerError(error);
        }
    }

    private Database()
    {
    }

    public static Connection open() throws SQLException
    {
        return DriverManager.getConnection(Config.DB_URL, Config.DB_USER, Config.DB_PASSWORD);
    }

    public static int nextId(Connection connection, String table, String column) throws SQLException
    {
        String sql = "SELECT MAX(" + column + ") FROM " + table;
        try (PreparedStatement statement = connection.prepareStatement(sql); ResultSet rows = statement.executeQuery())
        {
            rows.next();
            Object maximum = rows.getObject(1);
            return maximum == null ? 1 : ((Number) maximum).intValue() + 1;
        }
    }

    public static List<Map<String, Object>> rows(PreparedStatement statement) throws SQLException
    {
        try (ResultSet result = statement.executeQuery())
        {
            List<Map<String, Object>> rows = new ArrayList<>();
            ResultSetMetaData metadata = result.getMetaData();
            while (result.next())
            {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int index = 1; index <= metadata.getColumnCount(); index++)
                {
                    Object value = result.getObject(index);
                    if (value instanceof Timestamp timestamp)
                    {
                        value = timestamp.toInstant().toString();
                    }
                    row.put(metadata.getColumnLabel(index), value);
                }
                rows.add(row);
            }
            return rows;
        }
    }
}

/** Finds local GGUF files without performing database work. */
final class ModelFileScanner
{
    public List<ModelFile> scan()
    {
        Path directory = Config.modelDirectory();
        if (!Files.isDirectory(directory))
        {
            return List.of();
        }
        try (Stream<Path> paths = Files.walk(directory))
        {
            return paths.filter(Files::isRegularFile).filter(this::isGguf).map(this::describe)
                    .sorted(Comparator.comparing(model -> model.fileName().toLowerCase(Locale.ROOT))).toList();
        }
        catch (IOException error)
        {
            throw new IllegalStateException("Unable to scan GGUF models: " + error.getMessage(), error);
        }
    }

    private boolean isGguf(Path path)
    {
        return path.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".gguf");
    }

    private ModelFile describe(Path path)
    {
        Path absolute = path.toAbsolutePath().normalize();
        String fileName = absolute.getFileName().toString();
        String modelName = fileName.substring(0, fileName.length() - 5);
        return new ModelFile(absolute, fileName, modelName, storedPath(absolute));
    }

    private String storedPath(Path absolute)
    {
        try
        {
            return Config.projectRoot().relativize(absolute).toString().replace('\\', '/');
        }
        catch (IllegalArgumentException ignored)
        {
            return absolute.toString();
        }
    }

    public record ModelFile(Path absolutePath, String fileName, String modelName, String storedPath)
    {
    }
}

/** Reads administrator and subscription-based model permissions from MySQL. */
final class ModelAccessRepository
{
    public boolean isAdministrator(int userId) throws SQLException
    {
        try (Connection connection = Database.open(); PreparedStatement statement = connection.prepareStatement("SELECT user_id FROM Admins WHERE user_id = ?"))
        {
            statement.setInt(1, userId);
            try (ResultSet rows = statement.executeQuery())
            {
                return rows.next();
            }
        }
    }

    public Set<Integer> allowedModelIds(int userId) throws SQLException
    {
        try (Connection connection = Database.open();
                PreparedStatement statement = connection
                        .prepareStatement("SELECT DISTINCT a.model_id FROM Access a JOIN Has h ON h.tier_id =" + " a.tier_id WHERE h.user_id = ?"))
        {
            statement.setInt(1, userId);
            Set<Integer> modelIds = new HashSet<>();
            try (ResultSet rows = statement.executeQuery())
            {
                while (rows.next())
                {
                    modelIds.add(rows.getInt(1));
                }
            }
            return modelIds;
        }
    }
}

/**
 * Synchronizes detected GGUF files with MySQL and applies model-access rules.
 */
public final class ModelService
{
    private final ModelFileScanner files;
    private final ModelAccessRepository access;

    public ModelService()
    {
        this(new ModelFileScanner(), new ModelAccessRepository());
    }

    ModelService(ModelFileScanner files, ModelAccessRepository access)
    {
        this.files = files;
        this.access = access;
    }

    public synchronized Map<String, Object> discover()
    {
        List<ModelFileScanner.ModelFile> detected = files.scan();
        Map<String, Map<String, Object>> databaseModels = new HashMap<>();
        String databaseError = null;
        try
        {
            databaseModels = synchronize(detected);
        }
        catch (Exception error)
        {
            databaseError = error.getMessage();
        }

        List<Map<String, Object>> models = new ArrayList<>();
        for (ModelFileScanner.ModelFile file : detected)
        {
            Map<String, Object> row = databaseModels.get(file.fileName().toLowerCase());
            if (row != null && (!truth(row.get("is_enabled")) || !truth(row.get("is_available"))))
            {
                continue;
            }
            Map<String, Object> model = new LinkedHashMap<>();
            model.put("model_id", row == null ? null : row.get("model_id"));
            model.put("model_name", row == null ? file.modelName() : row.get("model_name"));
            model.put("file_name", file.fileName());
            model.put("model_path", file.storedPath());
            model.put("absolute_path", file.absolutePath().toString());
            model.put("model_type", "gguf");
            model.put("is_enabled", row == null || truth(row.get("is_enabled")));
            model.put("is_available", row == null || truth(row.get("is_available")));
            model.put("database_registered", row != null);
            models.add(model);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("models", models);
        result.put("model_directory", Config.modelDirectory().toString());
        result.put("database_connected", databaseError == null);
        result.put("database_error", databaseError);
        return result;
    }

    public Map<String, Object> discoverForUser(int userId)
    {
        Map<String, Object> discovery = new LinkedHashMap<>(discover());
        if (!Boolean.TRUE.equals(discovery.get("database_connected")))
        {
            discovery.put("models", List.of());
            return discovery;
        }

        try
        {
            if (access.isAdministrator(userId))
            {
                return discovery;
            }
            Set<Integer> allowed = access.allowedModelIds(userId);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> models = (List<Map<String, Object>>) discovery.get("models");
            discovery.put("models", models.stream().filter(model -> model.get("model_id") instanceof Number id && allowed.contains(id.intValue())).toList());
            return discovery;
        }
        catch (SQLException error)
        {
            discovery.put("models", List.of());
            discovery.put("database_connected", false);
            discovery.put("database_error", error.getMessage());
            return discovery;
        }
    }

    public Map<String, Object> select(Map<String, Object> request, int userId)
    {
        Map<String, Object> discovery = discoverForUser(userId);
        if (!Boolean.TRUE.equals(discovery.get("database_connected")))
        {
            throw new IllegalStateException("Database access is required to verify model-tier permissions.");
        }

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> models = (List<Map<String, Object>>) discovery.get("models");
        for (Map<String, Object> model : models)
        {
            if (matches(model, request))
            {
                return model;
            }
        }
        if (request.get("model_id") == null && request.get("model_file") == null && request.get("model_name") == null && !models.isEmpty())
        {
            return models.get(0);
        }
        throw new IllegalArgumentException("The selected GGUF model is unavailable.");
    }

    private Map<String, Map<String, Object>> synchronize(List<ModelFileScanner.ModelFile> detected) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                List<Map<String, Object>> rows = localModels(connection);
                markLocalModelsUnavailable(connection);

                int nextId = Database.nextId(connection, "Models", "model_id");
                Integer freeTier = null;
                for (ModelFileScanner.ModelFile file : detected)
                {
                    Map<String, Object> existing = find(rows, file);
                    if (existing == null)
                    {
                        if (freeTier == null)
                        {
                            freeTier = freeTier(connection);
                        }
                        insertModel(connection, nextId, file);
                        grantFreeTier(connection, freeTier, nextId);

                        existing = new LinkedHashMap<>();
                        existing.put("model_id", nextId++);
                        existing.put("model_name", file.modelName());
                        existing.put("model_path", file.storedPath());
                        existing.put("is_enabled", 1);
                        rows.add(existing);
                    }
                    else
                    {
                        updateModel(connection, ((Number) existing.get("model_id")).intValue(), file);
                    }
                    existing.put("is_available", 1);
                    existing.put("model_path", file.storedPath());
                }
                connection.commit();
                return byFilename(rows);
            }
            catch (SQLException | RuntimeException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    private List<Map<String, Object>> localModels(Connection connection) throws SQLException
    {
        try (PreparedStatement statement = connection
                .prepareStatement("SELECT model_id, model_name, model_path, is_enabled, is_available " + "FROM Models WHERE model_location = 'local'"))
        {
            return Database.rows(statement);
        }
    }

    private void markLocalModelsUnavailable(Connection connection) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("UPDATE Models SET is_available = 0 WHERE model_location = 'local'"))
        {
            statement.executeUpdate();
        }
    }

    private void insertModel(Connection connection, int modelId, ModelFileScanner.ModelFile file) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Models (model_id, model_name, model_type, model_path, "
                + "model_location, server_model_id, is_enabled, is_available) " + "VALUES (?, ?, 'gguf', ?, 'local', '', 1, 1)"))
        {
            statement.setInt(1, modelId);
            statement.setString(2, file.modelName());
            statement.setString(3, file.storedPath());
            statement.executeUpdate();
        }
    }

    private void updateModel(Connection connection, int modelId, ModelFileScanner.ModelFile file) throws SQLException
    {
        try (PreparedStatement statement = connection
                .prepareStatement("UPDATE Models SET model_path = ?, model_type = 'gguf', model_location =" + " 'local', is_available = 1 WHERE model_id = ?"))
        {
            statement.setString(1, file.storedPath());
            statement.setInt(2, modelId);
            statement.executeUpdate();
        }
    }

    private void grantFreeTier(Connection connection, int tierId, int modelId) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Access (tier_id, model_id) VALUES (?, ?)"))
        {
            statement.setInt(1, tierId);
            statement.setInt(2, modelId);
            statement.executeUpdate();
        }
    }

    private int freeTier(Connection connection) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement("SELECT tier_id, tier_name FROM Tiers ORDER BY tier_id");
                ResultSet rows = statement.executeQuery())
        {
            while (rows.next())
            {
                if ("Free".equalsIgnoreCase(rows.getString("tier_name")))
                {
                    return rows.getInt("tier_id");
                }
            }
            throw new SQLException("The Free tier was not found.");
        }
    }

    private Map<String, Object> find(List<Map<String, Object>> rows, ModelFileScanner.ModelFile file)
    {
        for (Map<String, Object> row : rows)
        {
            String storedFile = java.nio.file.Path.of(String.valueOf(row.get("model_path"))).getFileName().toString();
            if (storedFile.equalsIgnoreCase(file.fileName()) || String.valueOf(row.get("model_name")).equalsIgnoreCase(file.modelName()))
            {
                return row;
            }
        }
        return null;
    }

    private Map<String, Map<String, Object>> byFilename(List<Map<String, Object>> rows)
    {
        Map<String, Map<String, Object>> models = new HashMap<>();
        for (Map<String, Object> row : rows)
        {
            String filename = java.nio.file.Path.of(String.valueOf(row.get("model_path"))).getFileName().toString().toLowerCase();
            models.put(filename, row);
        }
        return models;
    }

    private boolean matches(Map<String, Object> model, Map<String, Object> request)
    {
        Object requestedId = request.get("model_id");
        if (requestedId instanceof Number requested && model.get("model_id") instanceof Number actual && actual.longValue() == requested.longValue())
        {
            return true;
        }
        String requestedFile = text(request.get("model_file"));
        if (requestedFile != null && requestedFile.equalsIgnoreCase(String.valueOf(model.get("file_name"))))
        {
            return true;
        }
        String requestedName = text(request.get("model_name"));
        return requestedName != null && requestedName.equalsIgnoreCase(String.valueOf(model.get("model_name")));
    }

    private boolean truth(Object value)
    {
        return value instanceof Boolean flag ? flag : value instanceof Number number && number.intValue() != 0;
    }

    private String text(Object value)
    {
        return value == null || String.valueOf(value).isBlank() ? null : String.valueOf(value);
    }
}

/** Sends model and embedding work to the private Python JSON-lines process. */
final class PythonModelClient implements AutoCloseable
{
    private final AtomicLong requestIds = new AtomicLong();
    private Process process;
    private BufferedWriter input;
    private BufferedReader output;

    public synchronized Map<String, Object> call(String action, Map<String, Object> values) throws IOException
    {
        ensureStarted();
        long id = requestIds.incrementAndGet();
        Map<String, Object> request = new LinkedHashMap<>(values);
        request.put("id", id);
        request.put("action", action);

        try
        {
            input.write(Json.stringify(request));
            input.newLine();
            input.flush();

            String line = output.readLine();
            if (line == null)
            {
                throw new IOException("The Python model worker stopped. Check logs/model_worker.log.");
            }
            Map<String, Object> response = Json.object(line);
            if (!(response.get("id") instanceof Number responseId) || responseId.longValue() != id)
            {
                throw new IOException("The Python model worker returned a mismatched response.");
            }
            if (!Boolean.TRUE.equals(response.get("ok")))
            {
                throw new IOException(String.valueOf(response.get("error")));
            }
            if (!(response.get("result") instanceof Map<?, ?> result))
            {
                throw new IOException("The Python model worker returned an invalid result.");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> typed = (Map<String, Object>) result;
            return typed;
        }
        catch (IOException | RuntimeException error)
        {
            stop();
            if (error instanceof IOException ioError)
            {
                throw ioError;
            }
            throw new IOException("The Python model worker returned invalid JSON.", error);
        }
    }

    public Map<String, Object> status() throws IOException
    {
        return call("status", Map.of());
    }

    public Map<String, Object> embedQuery(String text) throws IOException
    {
        Map<String, Object> result = call("embed", Map.of("texts", List.of(text), "query", true));
        Object vectorsValue = result.get("vectors");
        if (!(vectorsValue instanceof List<?> vectors) || vectors.isEmpty())
        {
            throw new IOException("The embedding worker returned no vector.");
        }

        String model = String.valueOf(result.getOrDefault("embedding_model", "")).trim();
        if (model.isEmpty())
        {
            throw new IOException("The embedding worker returned no model identifier.");
        }

        Map<String, Object> embedding = new LinkedHashMap<>();
        embedding.put("vector", numberList(vectors.get(0)));
        embedding.put("model", model);
        embedding.put("dimension", result.get("embedding_dimension"));
        return embedding;
    }

    public Map<String, Object> prepareDocument(Path path) throws IOException
    {
        return call("prepare_document", Map.of("path", path.toString()));
    }

    public String generate(Path modelPath, List<Map<String, String>> messages, int maxTokens, double temperature) throws IOException
    {
        Map<String, Object> result = call("generate",
                Map.of("model_path", modelPath.toString(), "messages", messages, "max_tokens", maxTokens, "temperature", temperature));
        return String.valueOf(result.getOrDefault("text", ""));
    }

    public static List<Double> numberList(Object value)
    {
        List<Double> numbers = new ArrayList<>();
        if (value instanceof List<?> items)
        {
            for (Object item : items)
            {
                numbers.add(((Number) item).doubleValue());
            }
        }
        return numbers;
    }

    private void ensureStarted() throws IOException
    {
        if (process != null && process.isAlive())
        {
            return;
        }

        Path root = Config.projectRoot();
        Path script = root.resolve("src/rag_pipeline/model_worker.py");
        if (!Files.isRegularFile(script))
        {
            throw new IOException("Python worker was not found: " + script);
        }
        Path log = root.resolve("logs/model_worker.log");
        Files.createDirectories(log.getParent());

        List<String> command = new ArrayList<>(Config.pythonCommand());
        command.add("-B");
        command.add(script.toString());
        ProcessBuilder builder = new ProcessBuilder(command).directory(root.toFile());
        builder.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        builder.redirectError(ProcessBuilder.Redirect.appendTo(log.toFile()));
        process = builder.start();
        input = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
        output = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
    }

    private void stop()
    {
        if (process != null && process.isAlive())
        {
            process.destroy();
        }
        process = null;
        input = null;
        output = null;
    }

    @Override
    public synchronized void close()
    {
        stop();
    }
}
