package application;

import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Array;
import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.time.temporal.TemporalAccessor;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.Part;

/** Same-origin JSON API for model execution and administrator capabilities. */
public final class ApiServlet extends HttpServlet
{
    private static final long serialVersionUID = 1L;

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response) throws IOException
    {
        handle(request, response, "GET");
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response) throws IOException
    {
        handle(request, response, "POST");
    }

    @Override
    protected void doDelete(HttpServletRequest request, HttpServletResponse response) throws IOException
    {
        handle(request, response, "DELETE");
    }

    private void handle(HttpServletRequest request, HttpServletResponse response, String method) throws IOException
    {
        request.setCharacterEncoding(StandardCharsets.UTF_8.name());
        try
        {
            String path = request.getPathInfo();
            if (path == null || path.isBlank())
            {
                path = "/health".equals(request.getServletPath()) ? "/health" : "/";
            }
            List<String> parts = parts(path);
            Object result;

            if (method.equals("GET") && path.equals("/health"))
            {
                result = health();
            }
            else if (method.equals("GET") && path.equals("/embedding/status"))
            {
                result = AppServices.PYTHON.status().get("embedding");
            }
            else if (method.equals("GET") && path.equals("/models"))
            {
                result = publicModels(currentUser(request));
            }
            else if (parts.size() == 1 && parts.get(0).equals("conversations") && method.equals("GET"))
            {
                result = Map.of("conversations", AppServices.CONVERSATIONS.list(currentUser(request)));
            }
            else if (parts.size() == 2 && parts.get(0).equals("conversations") && method.equals("GET"))
            {
                result = AppServices.CONVERSATIONS.get(integer(parts.get(1)), currentUser(request));
            }
            else if (parts.size() == 2 && parts.get(0).equals("conversations") && method.equals("DELETE"))
            {
                result = AppServices.CONVERSATIONS.delete(integer(parts.get(1)), currentUser(request));
            }
            else if (path.equals("/query") && method.equals("POST"))
            {
                Map<String, Object> query = body(request);
                query.put("user_id", currentUser(request));
                result = AppServices.CHAT.query(query);
            }
            else if (path.equals("/admin/tiers") && method.equals("GET"))
            {
                int adminId = administrator(request);
                Map<String, Object> discovery = AppServices.MODELS.discover();
                Map<String, Object> catalog = new LinkedHashMap<>(AppServices.ADMIN.listTiers(adminId));
                catalog.put("model_sync_error", discovery.get("database_error"));
                result = catalog;
            }
            else if (parts.size() == 3 && parts.get(0).equals("admin") && parts.get(1).equals("tiers") && method.equals("POST"))
            {
                result = updateTier(request, integer(parts.get(2)));
            }
            else if (path.equals("/admin/audit-logs") && method.equals("GET"))
            {
                result = Map.of("logs", AppServices.ADMIN.listAudit(administrator(request), parameter(request, "limit", 100)));
            }
            else if (path.equals("/admin/documents") && method.equals("GET"))
            {
                result = Map.of("documents", AppServices.ADMIN.listDocuments(administrator(request)));
            }
            else if (path.equals("/admin/documents") && method.equals("POST"))
            {
                result = AppServices.ADMIN.uploadDocument(administrator(request), part(request, "file"));
            }
            else if (parts.size() == 3 && parts.get(0).equals("admin") && parts.get(1).equals("documents") && method.equals("DELETE"))
            {
                result = AppServices.ADMIN.deleteDocument(administrator(request), integer(parts.get(2)));
            }
            else if (parts.size() == 4 && parts.get(0).equals("admin") && parts.get(1).equals("documents") && parts.get(3).equals("download")
                    && method.equals("GET"))
            {
                download(request, response, integer(parts.get(2)));
                return;
            }
            else if (path.equals("/payments/tiers") && method.equals("GET"))
            {
                result = AppServices.PAYMENT.userTiers(currentUser(request));
            }
            else if (path.equals("/payments/upgrade") && method.equals("POST"))
            {
                Map<String, Object> values = body(request);
                Object tierIdValue = values.get("tier_id");
                if (!(tierIdValue instanceof Number))
                {
                    throw new IllegalArgumentException("tier_id is required.");
                }
                result = AppServices.PAYMENT.upgradeTier(currentUser(request), ((Number) tierIdValue).intValue());
            }
            else
            {
                send(response, 404, Map.of("detail", "API route not found: " + method + " " + path));
                return;
            }
            send(response, 200, result);
        }
        catch (SecurityException error)
        {
            send(response, 403, Map.of("detail", error.getMessage()));
        }
        catch (IllegalArgumentException error)
        {
            send(response, 400, Map.of("detail", error.getMessage()));
        }
        catch (SQLException error)
        {
            send(response, 503, Map.of("detail", "MySQL request failed: " + error.getMessage()));
        }
        catch (IllegalStateException error)
        {
            send(response, 503, Map.of("detail", error.getMessage()));
        }
        catch (Exception error)
        {
            String message = error.getMessage() == null ? error.toString() : error.getMessage();
            send(response, 500, Map.of("detail", message));
        }
    }

    private Map<String, Object> health()
    {
        Map<String, Object> health = new LinkedHashMap<>();
        health.put("status", "ok");
        Map<String, Object> discovery = AppServices.MODELS.discover();
        health.put("model_count", ((List<?>) discovery.get("models")).size());
        health.put("database_connected", discovery.get("database_connected"));
        health.put("database_error", discovery.get("database_error"));
        try
        {
            health.putAll(AppServices.PYTHON.status());
        }
        catch (IOException error)
        {
            health.put("model_worker_error", error.getMessage());
        }
        health.put("rag_enabled", Config.RAG_ENABLED);
        health.put("rag_min_similarity", Config.RAG_MIN_SIMILARITY);
        return health;
    }

    private Map<String, Object> publicModels(int userId)
    {
        Map<String, Object> discovery = new LinkedHashMap<>(AppServices.MODELS.discoverForUser(userId));
        if (!Boolean.TRUE.equals(discovery.get("database_connected")))
        {
            throw new IllegalStateException("Database access is required to verify model-tier permissions.");
        }
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> source = (List<Map<String, Object>>) discovery.get("models");
        List<Map<String, Object>> models = new ArrayList<>();
        for (Map<String, Object> model : source)
        {
            Map<String, Object> copy = new LinkedHashMap<>(model);
            copy.remove("absolute_path");
            models.add(copy);
        }
        discovery.put("models", models);
        return discovery;
    }

    private Map<String, Object> updateTier(HttpServletRequest request, int tierId) throws Exception
    {
        Map<String, Object> values = body(request);
        Object price = values.get("price");
        if (!(price instanceof Number))
        {
            throw new IllegalArgumentException("price is required.");
        }
        List<Integer> modelIds = new ArrayList<>();
        if (values.get("model_ids") instanceof List<?> ids)
        {
            for (Object id : ids)
            {
                if (!(id instanceof Number number))
                {
                    throw new IllegalArgumentException("model_ids must contain integers.");
                }
                modelIds.add(number.intValue());
            }
        }
        Map<String, Object> tier = AppServices.ADMIN.updateTier(administrator(request), tierId, ((Number) price).doubleValue(), modelIds);
        return Map.of("updated", true, "tier", tier);
    }

    private void download(HttpServletRequest request, HttpServletResponse response, int documentId) throws Exception
    {
        int adminId = administrator(request);
        Map<String, Object> document = AppServices.ADMIN.findDocument(adminId, documentId);
        Path path = AppServices.ADMIN.downloadPath(adminId, documentId);
        String name = String.valueOf(document.get("file_name"));
        response.setContentType("application/octet-stream");
        response.setHeader("Content-Disposition", "attachment; filename*=UTF-8''" + URLEncoder.encode(name, StandardCharsets.UTF_8).replace("+", "%20"));
        response.setContentLengthLong(Files.size(path));
        try (InputStream input = Files.newInputStream(path))
        {
            input.transferTo(response.getOutputStream());
        }
    }

    private Map<String, Object> body(HttpServletRequest request) throws IOException
    {
        String text = request.getReader().lines().collect(Collectors.joining("\n"));
        return Json.object(text);
    }

    private Part part(HttpServletRequest request, String name) throws IOException, ServletException
    {
        Part value = request.getPart(name);
        if (value == null)
        {
            throw new IllegalArgumentException(name + " is required.");
        }
        return value;
    }

    private List<String> parts(String path)
    {
        return java.util.Arrays.stream(path.split("/")).filter(value -> !value.isBlank()).toList();
    }

    private int parameter(HttpServletRequest request, String name, int fallback)
    {
        String value = request.getParameter(name);
        return value == null || value.isBlank() ? fallback : integer(value);
    }

    private int administrator(HttpServletRequest request)
    {
        if (request.getSession(false) == null || request.getSession(false).getAttribute("adminUserId") == null)
        {
            throw new SecurityException("Administrator session is required.");
        }
        return integer(String.valueOf(request.getSession(false).getAttribute("adminUserId")));
    }

    private int currentUser(HttpServletRequest request)
    {
        if (request.getSession(false) == null)
        {
            throw new SecurityException("Login is required.");
        }
        Object adminId = request.getSession(false).getAttribute("adminUserId");
        Object userId = request.getSession(false).getAttribute("userId");
        Object selected = adminId == null ? userId : adminId;
        if (selected == null)
        {
            throw new SecurityException("Login is required.");
        }
        return integer(String.valueOf(selected));
    }

    private int integer(String value)
    {
        try
        {
            return Integer.parseInt(value);
        }
        catch (Exception error)
        {
            throw new IllegalArgumentException("Expected an integer but received: " + value);
        }
    }

    private void send(HttpServletResponse response, int status, Object value) throws IOException
    {
        response.setStatus(status);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json");
        response.getWriter().write(Json.stringify(value));
    }
}

/** Shared model, chat, and administrator services. */
final class AppServices
{
    static final PythonModelClient PYTHON = new PythonModelClient();
    static final ModelService MODELS = new ModelService();
    static final ConversationRepository CONVERSATIONS = new ConversationRepository();
    static final RagService RAG = new RagService(PYTHON);
    static final ChatService CHAT = new ChatService(MODELS, CONVERSATIONS, RAG, PYTHON);
    static final AdminService ADMIN = new AdminService(PYTHON);
    static final PaymentService PAYMENT = new PaymentService();

    private AppServices()
    {
    }
}

/** Minimal JSON reader/writer so the project needs no extra JSON library. */
final class Json
{
    private Json()
    {
    }

    public static Object parse(String text)
    {
        Parser parser = new Parser(text);
        Object value = parser.value();
        parser.space();
        if (!parser.finished())
        {
            throw new IllegalArgumentException("Unexpected JSON after position " + parser.index);
        }
        return value;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> object(String text)
    {
        Object value = parse(text);
        if (!(value instanceof Map))
        {
            throw new IllegalArgumentException("Expected a JSON object");
        }
        return (Map<String, Object>) value;
    }

    public static String stringify(Object value)
    {
        StringBuilder output = new StringBuilder();
        write(value, output);
        return output.toString();
    }

    private static void write(Object value, StringBuilder output)
    {
        if (value == null)
        {
            output.append("null");
        }
        else if (value instanceof String || value instanceof Character || value instanceof TemporalAccessor)
        {
            quote(String.valueOf(value), output);
        }
        else if (value instanceof Number || value instanceof Boolean)
        {
            output.append(value);
        }
        else if (value instanceof Map<?, ?> map)
        {
            output.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : map.entrySet())
            {
                if (!first)
                    output.append(',');
                quote(String.valueOf(entry.getKey()), output);
                output.append(':');
                write(entry.getValue(), output);
                first = false;
            }
            output.append('}');
        }
        else if (value instanceof Iterable<?> items)
        {
            output.append('[');
            boolean first = true;
            for (Object item : items)
            {
                if (!first)
                    output.append(',');
                write(item, output);
                first = false;
            }
            output.append(']');
        }
        else if (value.getClass().isArray())
        {
            output.append('[');
            for (int index = 0; index < Array.getLength(value); index++)
            {
                if (index > 0)
                    output.append(',');
                write(Array.get(value, index), output);
            }
            output.append(']');
        }
        else
        {
            quote(String.valueOf(value), output);
        }
    }

    private static void quote(String text, StringBuilder output)
    {
        output.append('"');
        for (int index = 0; index < text.length(); index++)
        {
            char character = text.charAt(index);
            switch (character)
            {
            case '"' -> output.append("\\\"");
            case '\\' -> output.append("\\\\");
            case '\b' -> output.append("\\b");
            case '\f' -> output.append("\\f");
            case '\n' -> output.append("\\n");
            case '\r' -> output.append("\\r");
            case '\t' -> output.append("\\t");
            default ->
            {
                if (character < 32)
                {
                    output.append(String.format("\\u%04x", (int) character));
                }
                else if (Character.isHighSurrogate(character))
                {
                    if (index + 1 < text.length()
                            && Character.isLowSurrogate(text.charAt(index + 1)))
                    {
                        output.append(character);
                        output.append(text.charAt(++index));
                    }
                    else
                    {
                        output.append("\\ufffd");
                    }
                }
                else if (Character.isLowSurrogate(character))
                {
                    output.append("\\ufffd");
                }
                else
                {
                    output.append(character);
                }
            }
            }
        }
        output.append('"');
    }

    private static final class Parser
    {
        private final String text;
        private int index;

        private Parser(String text)
        {
            this.text = text == null ? "" : text;
        }

        private Object value()
        {
            space();
            if (finished())
                throw error("Missing JSON value");
            return switch (text.charAt(index))
            {
            case '{' -> object();
            case '[' -> array();
            case '"' -> string();
            case 't' -> literal("true", Boolean.TRUE);
            case 'f' -> literal("false", Boolean.FALSE);
            case 'n' -> literal("null", null);
            default -> number();
            };
        }

        private Map<String, Object> object()
        {
            Map<String, Object> result = new LinkedHashMap<>();
            index++;
            space();
            if (take('}'))
                return result;
            do
            {
                space();
                if (finished() || text.charAt(index) != '"')
                    throw error("Expected object key");
                String key = string();
                space();
                if (!take(':'))
                    throw error("Expected ':'");
                result.put(key, value());
                space();
            } while (take(','));
            if (!take('}'))
                throw error("Expected '}'");
            return result;
        }

        private List<Object> array()
        {
            List<Object> result = new ArrayList<>();
            index++;
            space();
            if (take(']'))
                return result;
            do
            {
                result.add(value());
                space();
            } while (take(','));
            if (!take(']'))
                throw error("Expected ']'");
            return result;
        }

        private String string()
        {
            index++;
            StringBuilder result = new StringBuilder();
            while (!finished())
            {
                char character = text.charAt(index++);
                if (character == '"')
                    return result.toString();
                if (character != '\\')
                {
                    result.append(character);
                    continue;
                }
                if (finished())
                    throw error("Incomplete escape");
                char escaped = text.charAt(index++);
                switch (escaped)
                {
                case '"', '\\', '/' -> result.append(escaped);
                case 'b' -> result.append('\b');
                case 'f' -> result.append('\f');
                case 'n' -> result.append('\n');
                case 'r' -> result.append('\r');
                case 't' -> result.append('\t');
                case 'u' ->
                {
                    if (index + 4 > text.length())
                        throw error("Incomplete unicode escape");
                    result.append((char) Integer.parseInt(text.substring(index, index + 4), 16));
                    index += 4;
                }
                default -> throw error("Unknown escape");
                }
            }
            throw error("Unclosed string");
        }

        private Object number()
        {
            int start = index;
            while (!finished() && "-+0123456789.eE".indexOf(text.charAt(index)) >= 0)
                index++;
            if (start == index)
                throw error("Expected number");
            BigDecimal value = new BigDecimal(text.substring(start, index));
            try
            {
                return value.scale() <= 0 ? value.longValueExact() : value.doubleValue();
            }
            catch (ArithmeticException ignored)
            {
                return value.doubleValue();
            }
        }

        private Object literal(String expected, Object value)
        {
            if (!text.startsWith(expected, index))
                throw error("Invalid literal");
            index += expected.length();
            return value;
        }

        private boolean take(char expected)
        {
            if (!finished() && text.charAt(index) == expected)
            {
                index++;
                return true;
            }
            return false;
        }

        private void space()
        {
            while (!finished() && Character.isWhitespace(text.charAt(index)))
                index++;
        }

        private boolean finished()
        {
            return index >= text.length();
        }

        private IllegalArgumentException error(String message)
        {
            return new IllegalArgumentException(message + " at JSON position " + index);
        }
    }
}