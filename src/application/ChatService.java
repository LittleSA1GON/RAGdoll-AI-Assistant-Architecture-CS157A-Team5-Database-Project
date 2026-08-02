package application;

import java.io.IOException;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Coordinates model selection, RAG, conversation memory, inference, and saving.
 */
public final class ChatService
{
    private final ModelService models;
    private final ConversationRepository conversations;
    private final RagService rag;
    private final PythonModelClient python;

    public ChatService(ModelService models, ConversationRepository conversations, RagService rag, PythonModelClient python)
    {
        this.models = models;
        this.conversations = conversations;
        this.rag = rag;
        this.python = python;
    }

    public Map<String, Object> query(Map<String, Object> request) throws Exception
    {
        String queryText = requiredText(request, "query_text");
        int userId = number(request.get("user_id"), Config.DEFAULT_USER_ID);
        Integer conversationId = optionalNumber(request.get("conversation_id"));
        int maxTokens = Math.max(1, Math.min(4096, number(request.get("max_tokens"), 256)));
        double temperature = Math.max(0, Math.min(2, decimal(request.get("temperature"), 0.7)));
        Map<String, Object> selected = models.select(request, userId);

        List<Map<String, String>> history = conversationId == null ? List.of() : conversations.history(conversationId, userId);

        RagService.Result retrieval = null;
        String ragError = null;
        try
        {
            retrieval = rag.retrieve(queryText);
        }
        catch (Exception error)
        {
            ragError = error.getMessage();
        }

        List<Map<String, String>> messages = messages(request, history, queryText, retrieval, false);
        long started = System.nanoTime();
        String response = python.generate(Path.of(String.valueOf(selected.get("absolute_path"))), messages, maxTokens, temperature);
        boolean groundingRetry = false;
        boolean extractiveFallback = false;
        if (retrieval != null && !retrieval.chunks.isEmpty() && falseRefusal(response))
        {
            groundingRetry = true;
            response = python.generate(Path.of(String.valueOf(selected.get("absolute_path"))), messages(request, List.of(), queryText, retrieval, true),
                    maxTokens, Math.min(temperature, 0.2));
            if (falseRefusal(response))
            {
                extractiveFallback = true;
                response = extractiveAnswer(retrieval.chunks);
            }
        }
        double elapsed = Math.round((System.nanoTime() - started) / 1_000_000.0) / 1000.0;

        boolean saved = false;
        String saveError = null;
        Integer savedConversation = conversationId;
        try
        {
            Object modelIdValue = selected.get("model_id");
            if (!(modelIdValue instanceof Number))
            {
                throw new IllegalStateException("The selected model is not registered in MySQL.");
            }
            savedConversation = conversations.saveTurn(userId, conversationId, queryText, response, ((Number) modelIdValue).intValue(),
                    retrieval == null ? List.of() : retrieval.queryVector, retrieval == null ? null : retrieval.embeddingModel,
                    retrieval == null ? List.of() : retrieval.chunks, retrieval == null || retrieval.eligible);
            saved = true;
        }
        catch (Exception error)
        {
            saveError = error.getMessage();
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("response_text", response);
        result.put("model_id", selected.get("model_id"));
        result.put("model_name", selected.get("model_name"));
        result.put("model_file", selected.get("file_name"));
        result.put("elapsed_seconds", elapsed);
        result.put("conversation_id", savedConversation);
        result.put("conversation_saved", saved);
        result.put("conversation_error", saveError);
        result.put("remembered_turn_count", Math.min(history.size(), Config.MAX_HISTORY_TURNS));
        result.put("conversation_memory_used", !history.isEmpty());
        result.put("rag_enabled", Config.RAG_ENABLED);
        result.put("rag_eligible", retrieval == null || retrieval.eligible);
        result.put("rag_used", retrieval != null && !retrieval.chunks.isEmpty());
        result.put("rag_skip_reason", retrieval == null ? "retrieval_error" : retrieval.skipReason);
        result.put("rag_top_score", retrieval == null ? null : retrieval.topScore);
        result.put("rag_min_similarity", Config.RAG_MIN_SIMILARITY);
        result.put("rag_candidate_count", retrieval == null ? 0 : retrieval.candidateCount);
        result.put("rag_grounding_retry", groundingRetry);
        result.put("rag_extractive_fallback", extractiveFallback);
        result.put("rag_error", ragError);
        result.put("embedding_model", retrieval == null ? null : retrieval.embeddingModel);
        result.put("retrieved_sources", retrieval == null ? List.of() : retrieval.sources());
        return result;
    }

    private List<Map<String, String>> messages(Map<String, Object> request, List<Map<String, String>> history, String query, RagService.Result retrieval,
            boolean strict)
    {
        List<Map<String, String>> messages = new ArrayList<>();
        List<String> system = new ArrayList<>();
        Object customSystem = request.get("system_prompt");
        if (customSystem != null && !String.valueOf(customSystem).isBlank())
        {
            system.add(String.valueOf(customSystem));
        }
        if (retrieval != null && !retrieval.context().isBlank())
        {
            system.add(retrieval.context());
            if (strict)
                system.add("Answer directly from the excerpts. Do not claim they are unavailable.");
        }
        else if (retrieval != null && "social_or_greeting_query".equals(retrieval.skipReason))
        {
            system.add("Reply naturally without mentioning uploaded documents.");
        }
        if (!system.isEmpty())
            messages.add(message("system", String.join("\n\n", system)));

        int first = Math.max(0, history.size() - Config.MAX_HISTORY_TURNS);
        for (int index = first; index < history.size(); index++)
        {
            Map<String, String> turn = history.get(index);
            messages.add(message("user", turn.get("query_text")));
            if (!turn.getOrDefault("response_text", "").isBlank())
            {
                messages.add(message("assistant", turn.get("response_text")));
            }
        }
        messages.add(message("user", query));
        return messages;
    }

    private Map<String, String> message(String role, String content)
    {
        return Map.of("role", role, "content", content);
    }

    private boolean falseRefusal(String response)
    {
        String text = response.toLowerCase(Locale.ROOT);
        return text.contains("do not have access") || text.contains("don't have access") || text.contains("cannot access") || text.contains("can't access");
    }

    private String extractiveAnswer(List<Map<String, Object>> chunks)
    {
        StringBuilder answer = new StringBuilder("Based on the uploaded documents:\n\n");
        for (int index = 0; index < chunks.size(); index++)
        {
            String text = String.valueOf(chunks.get(index).get("chunk_text")).replaceAll("\\s+", " ");
            if (text.length() > 700)
                text = text.substring(0, 697) + "...";
            answer.append("- ").append(text).append(" [Source ").append(index + 1).append("]\n");
        }
        return answer.toString().trim();
    }

    private String requiredText(Map<String, Object> request, String name)
    {
        String value = String.valueOf(request.getOrDefault(name, "")).trim();
        if (value.isEmpty())
            throw new IllegalArgumentException(name + " is required.");
        return value;
    }

    private int number(Object value, int fallback)
    {
        return value instanceof Number number ? number.intValue() : fallback;
    }

    private Integer optionalNumber(Object value)
    {
        return value instanceof Number number ? number.intValue() : null;
    }

    private double decimal(Object value, double fallback)
    {
        return value instanceof Number number ? number.doubleValue() : fallback;
    }
}

/** Embeds a query, compares it with stored chunks, and builds model context. */
final class RagService
{
    private static final Pattern SOCIAL = Pattern.compile("^(hi|hello|hey|thanks|thank you|bye|goodbye|good morning|good evening|how are" + " you)[!. ]*$",
            Pattern.CASE_INSENSITIVE);

    private final PythonModelClient python;

    public RagService(PythonModelClient python)
    {
        this.python = python;
    }

    public Result retrieve(String query) throws IOException, SQLException
    {
        boolean eligible = !SOCIAL.matcher(query.trim()).matches();
        if (!Config.RAG_ENABLED)
            return new Result(false, "rag_disabled", List.of(), null, List.of(), null, 0);
        if (!eligible)
            return new Result(false, "social_or_greeting_query", List.of(), null, List.of(), null, 0);

        Map<String, Object> embedding = python.embedQuery(query);
        List<Double> queryVector = PythonModelClient.numberList(embedding.get("vector"));
        String embeddingModel = String.valueOf(embedding.getOrDefault("model", "")).trim();
        if (queryVector.isEmpty() || embeddingModel.isEmpty())
        {
            throw new IOException("The embedding worker returned incomplete embedding data.");
        }
        List<Map<String, Object>> candidates = loadCandidates();
        List<Map<String, Object>> scored = new ArrayList<>();
        for (Map<String, Object> row : candidates)
        {
            Object parsed;
            try
            {
                parsed = Json.parse(String.valueOf(row.get("embedding_vector")));
            }
            catch (RuntimeException ignored)
            {
                continue;
            }
            List<Double> vector = PythonModelClient.numberList(parsed);
            if (vector.size() != queryVector.size())
                continue;
            String storedModel = String.valueOf(row.getOrDefault("embedding_model", ""));
            if (!storedModel.isBlank() && !storedModel.equals(embeddingModel))
                continue;
            row.put("score", cosine(queryVector, vector));
            scored.add(row);
        }
        scored.sort(Comparator.comparingDouble(row -> -((Number) row.get("score")).doubleValue()));

        Double topScore = scored.isEmpty() ? null : ((Number) scored.get(0).get("score")).doubleValue();
        List<Map<String, Object>> accepted = new ArrayList<>();
        if (topScore != null && topScore >= Config.RAG_MIN_SIMILARITY)
        {
            int topDocument = ((Number) scored.get(0).get("document_id")).intValue();
            double strictFloor = Math.max(Config.RAG_MIN_SIMILARITY, topScore - Config.RAG_SCORE_MARGIN);
            for (Map<String, Object> row : scored)
            {
                double score = ((Number) row.get("score")).doubleValue();
                int document = ((Number) row.get("document_id")).intValue();
                if (score >= strictFloor || (document == topDocument && score >= Config.RAG_CONTEXT_MIN_SIMILARITY))
                {
                    accepted.add(row);
                    if (accepted.size() == Config.RAG_TOP_K)
                        break;
                }
            }
        }
        String skip = accepted.isEmpty() ? "below_similarity_threshold" : null;
        return new Result(true, skip, queryVector, embeddingModel, accepted, topScore, scored.size());
    }

    private List<Map<String, Object>> loadCandidates() throws SQLException
    {
        try (Connection connection = Database.open();
                PreparedStatement statement = connection.prepareStatement("SELECT c.chunk_id, c.document_id, c.chunk_text,"
                        + " c.embedding_vector, c.embedding_model, d.file_name FROM" + " Chunks c JOIN Documents d ON d.document_id = c.document_id"
                        + " WHERE d.processing_status = 'ready' AND d.rag_access_scope" + " = 'all_users' ORDER BY c.chunk_id DESC"))
        {
            List<Map<String, Object>> candidates = Database.rows(statement);
            int count = Math.min(candidates.size(), Config.RAG_MAX_CHUNKS);
            return new ArrayList<>(candidates.subList(0, count));
        }
    }

    private double cosine(List<Double> left, List<Double> right)
    {
        double dot = 0;
        double leftLength = 0;
        double rightLength = 0;
        for (int index = 0; index < left.size(); index++)
        {
            dot += left.get(index) * right.get(index);
            leftLength += left.get(index) * left.get(index);
            rightLength += right.get(index) * right.get(index);
        }
        return leftLength == 0 || rightLength == 0 ? -1 : dot / (Math.sqrt(leftLength) * Math.sqrt(rightLength));
    }

    public static final class Result
    {
        public final boolean eligible;
        public final String skipReason;
        public final List<Double> queryVector;
        public final String embeddingModel;
        public final List<Map<String, Object>> chunks;
        public final Double topScore;
        public final int candidateCount;

        private Result(boolean eligible, String skipReason, List<Double> queryVector, String embeddingModel, List<Map<String, Object>> chunks,
                Double topScore, int candidateCount)
        {
            this.eligible = eligible;
            this.skipReason = skipReason;
            this.queryVector = queryVector;
            this.embeddingModel = embeddingModel;
            this.chunks = chunks;
            this.topScore = topScore;
            this.candidateCount = candidateCount;
        }

        public String context()
        {
            if (chunks.isEmpty())
                return "";
            StringBuilder context = new StringBuilder("Use the following uploaded document excerpts as evidence. " + "Cite them as [Source N].\n\n");
            for (int index = 0; index < chunks.size(); index++)
            {
                Map<String, Object> chunk = chunks.get(index);
                context.append("[Source ").append(index + 1).append(": ").append(chunk.get("file_name")).append("]\n").append(chunk.get("chunk_text"))
                        .append("\n\n");
            }
            return context.toString().trim();
        }

        public List<Map<String, Object>> sources()
        {
            List<Map<String, Object>> sources = new ArrayList<>();
            for (Map<String, Object> chunk : chunks)
            {
                Map<String, Object> source = new LinkedHashMap<>();
                source.put("document_id", chunk.get("document_id"));
                source.put("chunk_id", chunk.get("chunk_id"));
                source.put("file_name", chunk.get("file_name"));
                source.put("score", Math.round(((Number) chunk.get("score")).doubleValue() * 10000.0) / 10000.0);
                sources.add(source);
            }
            return sources;
        }
    }
}

/** Reads and writes conversation, query, response, and retrieval history. */
final class ConversationRepository
{
    public List<Map<String, Object>> list(int userId) throws SQLException
    {
        verifyUser(userId);
        try (Connection connection = Database.open();
                PreparedStatement statement = connection.prepareStatement("SELECT c.conversation_id, c.title, c.created_at,"
                        + " MAX(q.created_at) query_updated_at, MAX(r.created_at)" + " response_updated_at FROM Conversations c LEFT JOIN"
                        + " Contains_Query cq ON cq.conversation_id = c.conversation_id" + " LEFT JOIN Queries q ON q.query_id = cq.query_id LEFT JOIN"
                        + " Responses r ON r.query_id = q.query_id WHERE c.user_id = ?" + " GROUP BY c.conversation_id, c.title, c.created_at"))
        {
            statement.setInt(1, userId);
            List<Map<String, Object>> conversations = Database.rows(statement);
            for (Map<String, Object> conversation : conversations)
            {
                Object updatedAt = latest(conversation.get("created_at"), conversation.remove("query_updated_at"), conversation.remove("response_updated_at"));
                conversation.put("updated_at", updatedAt);
            }
            conversations.sort(Comparator.comparing(row -> String.valueOf(row.get("updated_at")), Comparator.reverseOrder()));
            return new ArrayList<>(conversations.subList(0, Math.min(conversations.size(), 50)));
        }
    }

    public Map<String, Object> get(int conversationId, int userId) throws SQLException
    {
        Map<String, Object> conversation = conversation(conversationId, userId);
        try (Connection connection = Database.open();
                PreparedStatement statement = connection.prepareStatement("SELECT q.query_text, q.created_at query_created_at, r.response_id,"
                        + " r.response_text, r.created_at response_created_at," + " m.model_id, m.model_name FROM Contains_Query cq JOIN"
                        + " Queries q ON q.query_id = cq.query_id LEFT JOIN Responses r" + " ON r.query_id = q.query_id LEFT JOIN Models m ON m.model_id"
                        + " = r.model_id WHERE cq.conversation_id = ? AND q.user_id = ?" + " ORDER BY q.created_at, q.query_id, r.created_at"))
        {
            statement.setInt(1, conversationId);
            statement.setInt(2, userId);
            List<Map<String, Object>> messages = new ArrayList<>();
            for (Map<String, Object> row : Database.rows(statement))
            {
                Map<String, Object> user = new LinkedHashMap<>();
                user.put("role", "user");
                user.put("text", row.get("query_text"));
                user.put("created_at", row.get("query_created_at"));
                messages.add(user);
                if (row.get("response_id") != null)
                {
                    Map<String, Object> assistant = new LinkedHashMap<>();
                    assistant.put("role", "assistant");
                    assistant.put("text", row.get("response_text"));
                    assistant.put("created_at", row.get("response_created_at"));
                    assistant.put("model_id", row.get("model_id"));
                    assistant.put("model_name", row.get("model_name"));
                    messages.add(assistant);
                }
            }
            conversation.put("messages", messages);
            return conversation;
        }
    }

    public List<Map<String, String>> history(int conversationId, int userId) throws SQLException
    {
        conversation(conversationId, userId);
        try (Connection connection = Database.open();
                PreparedStatement statement = connection.prepareStatement("SELECT q.query_text, r.response_text"
                        + " FROM Contains_Query cq JOIN Queries q ON q.query_id =" + " cq.query_id LEFT JOIN Responses r ON r.query_id ="
                        + " q.query_id WHERE cq.conversation_id = ? AND q.user_id = ?" + " ORDER BY q.created_at, q.query_id"))
        {
            statement.setInt(1, conversationId);
            statement.setInt(2, userId);
            List<Map<String, String>> history = new ArrayList<>();
            for (Map<String, Object> row : Database.rows(statement))
            {
                Object responseText = row.get("response_text");
                history.add(
                        Map.of("query_text", String.valueOf(row.get("query_text")), "response_text", responseText == null ? "" : String.valueOf(responseText)));
            }
            return history;
        }
    }

    public synchronized Map<String, Object> delete(int conversationId, int userId) throws SQLException
    {
        conversation(conversationId, userId);
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                List<Integer> queryIds = new ArrayList<>();
                try (PreparedStatement select = connection.prepareStatement("SELECT query_id FROM Contains_Query WHERE conversation_id = ?"))
                {
                    select.setInt(1, conversationId);
                    try (ResultSet rows = select.executeQuery())
                    {
                        while (rows.next())
                            queryIds.add(rows.getInt(1));
                    }
                }
                int responseCount = 0;
                if (!queryIds.isEmpty())
                {
                    String placeholders = String.join(",", queryIds.stream().map(id -> "?").toList());
                    try (PreparedStatement count = connection.prepareStatement("SELECT COUNT(*) FROM Responses WHERE query_id IN (" + placeholders + ")"))
                    {
                        for (int index = 0; index < queryIds.size(); index++)
                            count.setInt(index + 1, queryIds.get(index));
                        try (ResultSet rows = count.executeQuery())
                        {
                            rows.next();
                            responseCount = rows.getInt(1);
                        }
                    }
                }
                try (PreparedStatement remove = connection.prepareStatement("DELETE FROM Conversations WHERE conversation_id = ? AND user_id =" + " ?"))
                {
                    remove.setInt(1, conversationId);
                    remove.setInt(2, userId);
                    remove.executeUpdate();
                }
                if (!queryIds.isEmpty())
                {
                    String placeholders = String.join(",", queryIds.stream().map(id -> "?").toList());
                    try (PreparedStatement remove = connection.prepareStatement("DELETE FROM Queries WHERE query_id IN (" + placeholders + ")"))
                    {
                        for (int index = 0; index < queryIds.size(); index++)
                            remove.setInt(index + 1, queryIds.get(index));
                        remove.executeUpdate();
                    }
                }
                connection.commit();
                return Map.of("deleted", true, "conversation_id", conversationId, "deleted_queries", queryIds.size(), "deleted_responses", responseCount);
            }
            catch (SQLException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    public synchronized int saveTurn(int userId, Integer conversationId, String queryText, String responseText, int modelId, List<Double> queryEmbedding,
            String embeddingModel, List<Map<String, Object>> retrieved, boolean ragEligible) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            connection.setAutoCommit(false);
            try
            {
                verifyUser(connection, userId);
                Timestamp savedAt = new Timestamp(System.currentTimeMillis());
                if (conversationId == null)
                {
                    conversationId = Database.nextId(connection, "Conversations", "conversation_id");
                    try (PreparedStatement insert = connection.prepareStatement("INSERT INTO Conversations VALUES (?, ?, ?, ?)"))
                    {
                        insert.setInt(1, conversationId);
                        insert.setInt(2, userId);
                        insert.setString(3, title(queryText));
                        insert.setTimestamp(4, savedAt);
                        insert.executeUpdate();
                    }
                    execute(connection, "INSERT INTO Owns VALUES (?, ?)", userId, conversationId);
                }
                else
                {
                    verifyConversation(connection, conversationId, userId);
                }

                int queryId = Database.nextId(connection, "Queries", "query_id");
                int responseId = Database.nextId(connection, "Responses", "response_id");
                try (PreparedStatement insert = connection.prepareStatement("INSERT INTO Queries (query_id, user_id, query_text,"
                        + " embedding_vector, embedding_model, embedding_dimension," + " rag_eligible, created_at) VALUES (?, ?, ?, ?, ?, ?, ?," + " ?)"))
                {
                    insert.setInt(1, queryId);
                    insert.setInt(2, userId);
                    insert.setString(3, queryText);
                    insert.setString(4, Json.stringify(queryEmbedding));
                    insert.setString(5, queryEmbedding.isEmpty() ? null : embeddingModel);
                    if (queryEmbedding.isEmpty())
                        insert.setNull(6, java.sql.Types.INTEGER);
                    else
                        insert.setInt(6, queryEmbedding.size());
                    insert.setBoolean(7, ragEligible);
                    insert.setTimestamp(8, savedAt);
                    insert.executeUpdate();
                }
                execute(connection, "INSERT INTO Creates VALUES (?, ?)", userId, queryId);
                execute(connection, "INSERT INTO Contains_Query VALUES (?, ?)", conversationId, queryId);
                execute(connection, "INSERT INTO Prompts VALUES (?, ?, ?)", queryId, modelId, savedAt);

                try (PreparedStatement insert = connection.prepareStatement("INSERT INTO Responses VALUES (?, ?, ?, ?, ?)"))
                {
                    insert.setInt(1, responseId);
                    insert.setInt(2, queryId);
                    insert.setInt(3, modelId);
                    insert.setString(4, responseText);
                    insert.setTimestamp(5, savedAt);
                    insert.executeUpdate();
                }
                for (Map<String, Object> chunk : retrieved)
                {
                    try (PreparedStatement insert = connection.prepareStatement("INSERT INTO Retrieves VALUES (?, ?, ?, ?)"))
                    {
                        insert.setInt(1, queryId);
                        insert.setInt(2, ((Number) chunk.get("document_id")).intValue());
                        insert.setInt(3, ((Number) chunk.get("chunk_id")).intValue());
                        insert.setDouble(4, ((Number) chunk.get("score")).doubleValue());
                        insert.executeUpdate();
                    }
                }
                execute(connection, "INSERT INTO Answers VALUES (?, ?)", queryId, responseId);
                execute(connection, "INSERT INTO Generates VALUES (?, ?)", modelId, responseId);
                execute(connection, "INSERT INTO Contains_Response VALUES (?, ?)", conversationId, responseId);
                insertAudit(connection, userId, "User submitted a model query", "SUBMIT_QUERY");
                connection.commit();
                return conversationId;
            }
            catch (SQLException error)
            {
                connection.rollback();
                throw error;
            }
        }
    }

    private Map<String, Object> conversation(int conversationId, int userId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            verifyConversation(connection, conversationId, userId);
            try (PreparedStatement statement = connection
                    .prepareStatement("SELECT conversation_id, title, created_at FROM Conversations " + "WHERE conversation_id = ? AND user_id = ?"))
            {
                statement.setInt(1, conversationId);
                statement.setInt(2, userId);
                return new LinkedHashMap<>(Database.rows(statement).get(0));
            }
        }
    }

    private void verifyUser(int userId) throws SQLException
    {
        try (Connection connection = Database.open())
        {
            verifyUser(connection, userId);
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
                    throw new IllegalArgumentException("User " + userId + " was not found.");
            }
        }
    }

    private void verifyConversation(Connection connection, int conversationId, int userId) throws SQLException
    {
        try (PreparedStatement statement = connection
                .prepareStatement("SELECT conversation_id FROM Conversations WHERE conversation_id = ? AND" + " user_id = ?"))
        {
            statement.setInt(1, conversationId);
            statement.setInt(2, userId);
            try (ResultSet rows = statement.executeQuery())
            {
                if (!rows.next())
                    throw new IllegalArgumentException("Conversation " + conversationId + " does not belong to user " + userId + ".");
            }
        }
    }

    private void insertAudit(Connection connection, int userId, String action, String type) throws SQLException
    {
        int logId = Database.nextId(connection, "Audit_Log", "log_id");
        try (PreparedStatement statement = connection.prepareStatement("INSERT INTO Audit_Log VALUES (?, ?, ?, ?, ?)"))
        {
            statement.setInt(1, logId);
            statement.setInt(2, userId);
            statement.setString(3, action);
            statement.setString(4, type);
            statement.setTimestamp(5, new Timestamp(System.currentTimeMillis()));
            statement.executeUpdate();
        }
        execute(connection, "INSERT INTO Triggers VALUES (?, ?)", userId, logId);
    }

    private void execute(Connection connection, String sql, int first, int second) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement(sql))
        {
            statement.setInt(1, first);
            statement.setInt(2, second);
            statement.executeUpdate();
        }
    }

    private void execute(Connection connection, String sql, int first, int second, Timestamp timestamp) throws SQLException
    {
        try (PreparedStatement statement = connection.prepareStatement(sql))
        {
            statement.setInt(1, first);
            statement.setInt(2, second);
            statement.setTimestamp(3, timestamp);
            statement.executeUpdate();
        }
    }

    private Object latest(Object... values)
    {
        Object latest = null;
        for (Object value : values)
        {
            if (value != null && (latest == null || String.valueOf(value).compareTo(String.valueOf(latest)) > 0))
            {
                latest = value;
            }
        }
        return latest;
    }

    private String title(String query)
    {
        String title = String.join(" ", query.trim().split("\\s+"));
        return title.length() <= 100 ? title : title.substring(0, 97) + "...";
    }
}
