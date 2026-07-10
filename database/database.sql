DROP DATABASE IF EXISTS ragdoll_db;
CREATE DATABASE ragdoll_db;
USE ragdoll_db;

CREATE TABLE `Users` (
    user_id INT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL
);

CREATE TABLE `User_Hashes` (
    user_id INT PRIMARY KEY,
    password_hash VARCHAR(64) NOT NULL,
    salt VARCHAR(255) NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE
);

CREATE TABLE `Admins` (
    user_id INT PRIMARY KEY,
    company_id VARCHAR(50) NOT NULL,
    admin_email VARCHAR(100) NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE
);

CREATE TABLE `Tiers` (
    tier_id INT PRIMARY KEY,
    tier_name VARCHAR(50) NOT NULL UNIQUE,
    price DECIMAL(8,2) NOT NULL
);

CREATE TABLE `Payments` (
    payment_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    tier_id INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    payment_date DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id),
    FOREIGN KEY (tier_id) REFERENCES `Tiers`(tier_id)
);

CREATE TABLE `Models` (
    model_id INT PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL UNIQUE,
    model_type VARCHAR(50) NOT NULL,
    model_path VARCHAR(255) NOT NULL
);

CREATE TABLE `Documents` (
    document_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    uploaded_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
);

CREATE TABLE `Chunks` (
    chunk_id INT PRIMARY KEY,
    document_id INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding_vector TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES `Documents`(document_id)
        ON DELETE CASCADE
);

CREATE TABLE `Conversations` (
    conversation_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(100) NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE
);

CREATE TABLE `Queries` (
    query_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    query_text TEXT NOT NULL,
    embedding_vector TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE
);

CREATE TABLE `Responses` (
    response_id INT PRIMARY KEY,
    query_id INT NOT NULL,
    model_id INT NOT NULL,
    response_text TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES `Models`(model_id)
);

CREATE TABLE `Audit_Log` (
    log_id INT PRIMARY KEY,
    user_id INT NULL,
    action_log VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    action_date DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE SET NULL
);

CREATE TABLE `Triggers` (
    user_id INT NULL,
    log_id INT NOT NULL,
    PRIMARY KEY (log_id),
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE SET NULL,
    FOREIGN KEY (log_id) REFERENCES `Audit_Log`(log_id)
        ON DELETE CASCADE
);

CREATE TABLE `Pays` (
    user_id INT NOT NULL,
    payment_id INT NOT NULL,
    PRIMARY KEY (payment_id),
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (payment_id) REFERENCES `Payments`(payment_id)
        ON DELETE CASCADE
);

CREATE TABLE `Sets` (
    tier_id INT NOT NULL,
    payment_id INT NOT NULL,
    PRIMARY KEY (payment_id),
    FOREIGN KEY (tier_id) REFERENCES `Tiers`(tier_id)
        ON DELETE CASCADE,
    FOREIGN KEY (payment_id) REFERENCES `Payments`(payment_id)
        ON DELETE CASCADE
);

CREATE TABLE `Has` (
    user_id INT NOT NULL,
    tier_id INT NOT NULL,
    assigned_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, tier_id),
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tier_id) REFERENCES `Tiers`(tier_id)
        ON DELETE CASCADE
);

CREATE TABLE `Creates` (
    user_id INT NOT NULL,
    query_id INT NOT NULL,
    PRIMARY KEY (query_id),
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE
);

CREATE TABLE `Owns` (
    user_id INT NOT NULL,
    conversation_id INT NOT NULL,
    PRIMARY KEY (conversation_id),
    FOREIGN KEY (user_id) REFERENCES `Users`(user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES `Conversations`(conversation_id)
        ON DELETE CASCADE
);

CREATE TABLE `Access` (
    tier_id INT NOT NULL,
    model_id INT NOT NULL,
    PRIMARY KEY (tier_id, model_id),
    FOREIGN KEY (tier_id) REFERENCES `Tiers`(tier_id)
        ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES `Models`(model_id)
        ON DELETE CASCADE
);

CREATE TABLE `Prompts` (
    query_id INT NOT NULL,
    model_id INT NOT NULL,
    prompted_at DATETIME NOT NULL,
    PRIMARY KEY (query_id, model_id),
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES `Models`(model_id)
        ON DELETE CASCADE
);

CREATE TABLE `Generates` (
    model_id INT NOT NULL,
    response_id INT NOT NULL,
    PRIMARY KEY (response_id),
    FOREIGN KEY (model_id) REFERENCES `Models`(model_id)
        ON DELETE CASCADE,
    FOREIGN KEY (response_id) REFERENCES `Responses`(response_id)
        ON DELETE CASCADE
);

CREATE TABLE `Retrieves` (
    query_id INT NOT NULL,
    document_id INT NOT NULL,
    chunk_id INT NOT NULL,
    PRIMARY KEY (query_id, chunk_id),
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES `Documents`(document_id)
        ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES `Chunks`(chunk_id)
        ON DELETE CASCADE
);

CREATE TABLE `Answers` (
    query_id INT NOT NULL,
    response_id INT NOT NULL,
    PRIMARY KEY (response_id),
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE,
    FOREIGN KEY (response_id) REFERENCES `Responses`(response_id)
        ON DELETE CASCADE
);

CREATE TABLE `Contains_Response` (
    conversation_id INT NOT NULL,
    response_id INT NOT NULL,
    PRIMARY KEY (conversation_id, response_id),
    FOREIGN KEY (conversation_id) REFERENCES `Conversations`(conversation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (response_id) REFERENCES `Responses`(response_id)
        ON DELETE CASCADE
);

CREATE TABLE `Contains_Query` (
    conversation_id INT NOT NULL,
    query_id INT NOT NULL,
    PRIMARY KEY (conversation_id, query_id),
    FOREIGN KEY (conversation_id) REFERENCES `Conversations`(conversation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (query_id) REFERENCES `Queries`(query_id)
        ON DELETE CASCADE
);

CREATE TABLE `Manages` (
    admin_user_id INT NOT NULL,
    document_id INT NOT NULL,
    managed_at DATETIME NOT NULL,
    PRIMARY KEY (admin_user_id, document_id),
    FOREIGN KEY (admin_user_id) REFERENCES `Admins`(user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES `Documents`(document_id)
        ON DELETE CASCADE
);

CREATE TABLE `Splits_Into` (
    document_id INT NOT NULL,
    chunk_id INT NOT NULL,
    PRIMARY KEY (chunk_id),
    FOREIGN KEY (document_id) REFERENCES `Documents`(document_id)
        ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES `Chunks`(chunk_id)
        ON DELETE CASCADE
);

INSERT INTO `Users` VALUES
(1, 'ethanv', 'ethan.vu@sjsu.edu', '2026-07-01 10:00:00'),
(2, 'geolalu', 'geo.lalu@sjsu.edu', '2026-07-01 10:05:00'),
(3, 'namank', 'naman.kumar@sjsu.edu', '2026-07-01 10:10:00'),
(4, 'sophial', 'sophia.lee@example.com', '2026-07-01 10:15:00'),
(5, 'michaelc', 'michael.chen@example.com', '2026-07-01 10:20:00'),
(6, 'priyap', 'priya.patel@example.com', '2026-07-01 10:25:00'),
(7, 'jordanw', 'jordan.wong@example.com', '2026-07-01 10:30:00'),
(8, 'mariag', 'maria.garcia@example.com', '2026-07-01 10:35:00'),
(9, 'omarh', 'omar.hassan@example.com', '2026-07-01 10:40:00'),
(10, 'lisaw', 'lisa.wilson@example.com', '2026-07-01 10:45:00'),
(11, 'admin_avery', 'avery.admin@ragdoll.local', '2026-07-01 09:00:00'),
(12, 'admin_blake', 'blake.admin@ragdoll.local', '2026-07-01 09:05:00'),
(13, 'admin_casey', 'casey.admin@ragdoll.local', '2026-07-01 09:10:00'),
(14, 'admin_devon', 'devon.admin@ragdoll.local', '2026-07-01 09:15:00'),
(15, 'admin_emery', 'emery.admin@ragdoll.local', '2026-07-01 09:20:00'),
(16, 'admin_finn', 'finn.admin@ragdoll.local', '2026-07-01 09:25:00'),
(17, 'admin_gale', 'gale.admin@ragdoll.local', '2026-07-01 09:30:00'),
(18, 'admin_harper', 'harper.admin@ragdoll.local', '2026-07-01 09:35:00'),
(19, 'admin_iris', 'iris.admin@ragdoll.local', '2026-07-01 09:40:00'),
(20, 'admin_riley', 'riley.admin@ragdoll.local', '2026-07-01 09:45:00');

INSERT INTO `User_Hashes` (user_id, password_hash, salt)
SELECT user_id, SHA2(CONCAT(username, '_password_', user_id), 256), CONCAT('salt_', username, '_', user_id)
FROM `Users`;

INSERT INTO `Admins` VALUES
(11, 'RAGDOLL001', 'avery.admin@ragdoll.local'),
(12, 'RAGDOLL002', 'blake.admin@ragdoll.local'),
(13, 'RAGDOLL003', 'casey.admin@ragdoll.local'),
(14, 'RAGDOLL004', 'devon.admin@ragdoll.local'),
(15, 'RAGDOLL005', 'emery.admin@ragdoll.local'),
(16, 'RAGDOLL006', 'finn.admin@ragdoll.local'),
(17, 'RAGDOLL007', 'gale.admin@ragdoll.local'),
(18, 'RAGDOLL008', 'harper.admin@ragdoll.local'),
(19, 'RAGDOLL009', 'iris.admin@ragdoll.local'),
(20, 'RAGDOLL010', 'riley.admin@ragdoll.local');

INSERT INTO `Tiers` VALUES
(1, 'Free', 0.00),
(2, 'Student', 4.99),
(3, 'Standard', 9.99),
(4, 'Plus', 14.99),
(5, 'Premium', 19.99),
(6, 'Research', 24.99),
(7, 'Developer', 29.99),
(8, 'Team', 49.99),
(9, 'Enterprise', 99.99),
(10, 'Admin Access', 0.00);

INSERT INTO `Payments` VALUES
(1, 1, 1, 'Free Tier', '2026-07-02 12:00:00'),
(2, 2, 2, 'Completed', '2026-07-02 12:05:00'),
(3, 3, 3, 'Completed', '2026-07-02 12:10:00'),
(4, 4, 4, 'Completed', '2026-07-02 12:15:00'),
(5, 5, 5, 'Completed', '2026-07-02 12:20:00'),
(6, 6, 6, 'Completed', '2026-07-02 12:25:00'),
(7, 7, 7, 'Completed', '2026-07-02 12:30:00'),
(8, 8, 8, 'Completed', '2026-07-02 12:35:00'),
(9, 9, 9, 'Completed', '2026-07-02 12:40:00'),
(10, 10, 5, 'Completed', '2026-07-02 12:45:00');

INSERT INTO `Models` VALUES
(1, 'Llama 3.1 8B', 'LLM', '/models/llama-3.1-8b.gguf'),
(2, 'Gemma 2B', 'LLM', '/models/gemma-2b.gguf'),
(3, 'Mistral 7B', 'LLM', '/models/mistral-7b.gguf'),
(4, 'Phi 3 Mini', 'LLM', '/models/phi-3-mini.gguf'),
(5, 'Mythos Vision', 'Multimodal', '/models/mythos-vision.safetensors'),
(6, 'MiniLM Embedder', 'Embedding', '/models/all-MiniLM-L6-v2'),
(7, 'BGE Small Embedder', 'Embedding', '/models/bge-small-en-v1.5'),
(8, 'CodeLlama 7B', 'Code', '/models/codellama-7b.gguf'),
(9, 'TinyLlama 1.1B', 'LLM', '/models/tinyllama-1.1b.gguf'),
(10, 'Whisper Base', 'Speech', '/models/whisper-base.bin');

INSERT INTO `Documents` VALUES
(1, 11, 'rag_overview.pdf', 'PDF', '2026-07-03 09:00:00'),
(2, 12, 'mysql_notes.txt', 'TXT', '2026-07-03 09:10:00'),
(3, 13, 'project_requirements.pdf', 'PDF', '2026-07-03 09:20:00'),
(4, 14, 'vector_search_guide.pdf', 'PDF', '2026-07-03 09:30:00'),
(5, 15, 'prompt_engineering.md', 'MD', '2026-07-03 09:40:00'),
(6, 1, 'ethan_research_notes.pdf', 'PDF', '2026-07-03 10:00:00'),
(7, 2, 'geo_database_summary.docx', 'DOCX', '2026-07-03 10:10:00'),
(8, 3, 'naman_model_access.txt', 'TXT', '2026-07-03 10:20:00'),
(9, 4, 'sophia_api_reference.pdf', 'PDF', '2026-07-03 10:30:00'),
(10, 5, 'michael_testing_plan.md', 'MD', '2026-07-03 10:40:00');

INSERT INTO `Chunks` VALUES
(1, 1, 'Retrieval augmented generation uses retrieved context to improve model answers.', '[0.12, 0.25, 0.33, 0.41]'),
(2, 2, 'MySQL stores relational data using tables, primary keys, and foreign keys.', '[0.05, 0.15, 0.28, 0.36]'),
(3, 3, 'The project requires updated functional requirements, ERD, schemas, and table screenshots.', '[0.21, 0.30, 0.40, 0.52]'),
(4, 4, 'Vector search compares query embeddings with stored document chunk embeddings.', '[0.18, 0.22, 0.39, 0.44]'),
(5, 5, 'Prompt engineering improves model output by providing clear instructions and context.', '[0.14, 0.27, 0.31, 0.49]'),
(6, 6, 'The RAGdoll application stores user prompts and generated responses for conversation history.', '[0.19, 0.24, 0.38, 0.50]'),
(7, 7, 'Database normalization reduces duplicated data and improves consistency.', '[0.08, 0.17, 0.33, 0.42]'),
(8, 8, 'Premium tiers can unlock additional local models and expanded usage privileges.', '[0.22, 0.31, 0.45, 0.58]'),
(9, 9, 'API documentation explains how the application sends queries to the local model server.', '[0.11, 0.29, 0.37, 0.47]'),
(10, 10, 'Testing plans include authentication, document upload, retrieval, and response generation cases.', '[0.16, 0.26, 0.34, 0.46]');

INSERT INTO `Conversations` VALUES
(1, 1, 'RAG System Help', '2026-07-04 14:00:00'),
(2, 2, 'Database Design Questions', '2026-07-04 14:30:00'),
(3, 3, 'Model Access Discussion', '2026-07-04 15:00:00'),
(4, 4, 'Vector Search Setup', '2026-07-04 15:30:00'),
(5, 5, 'Prompt Writing Help', '2026-07-04 16:00:00'),
(6, 6, 'Conversation History Review', '2026-07-04 16:30:00'),
(7, 7, 'Normalization Practice', '2026-07-04 17:00:00'),
(8, 8, 'Payment Tier Question', '2026-07-04 17:30:00'),
(9, 9, 'Local Model Server', '2026-07-04 18:00:00'),
(10, 10, 'Testing Checklist', '2026-07-04 18:30:00');

INSERT INTO `Queries` VALUES
(1, 1, 'How does RAG retrieve relevant chunks?', '[0.13, 0.24, 0.35, 0.48]', '2026-07-04 14:01:00'),
(2, 2, 'How should I store chunks in MySQL?', '[0.07, 0.16, 0.29, 0.37]', '2026-07-04 14:31:00'),
(3, 3, 'Which models can premium users access?', '[0.22, 0.31, 0.45, 0.58]', '2026-07-04 15:01:00'),
(4, 4, 'What is the purpose of an embedding vector?', '[0.18, 0.23, 0.36, 0.43]', '2026-07-04 15:31:00'),
(5, 5, 'How can prompts be written more clearly?', '[0.15, 0.28, 0.32, 0.50]', '2026-07-04 16:01:00'),
(6, 6, 'Where is conversation history stored?', '[0.20, 0.25, 0.39, 0.51]', '2026-07-04 16:31:00'),
(7, 7, 'Why should database tables be normalized?', '[0.09, 0.18, 0.34, 0.43]', '2026-07-04 17:01:00'),
(8, 8, 'How are paid tiers connected to model access?', '[0.23, 0.32, 0.46, 0.59]', '2026-07-04 17:31:00'),
(9, 9, 'How does the local model server receive requests?', '[0.12, 0.30, 0.38, 0.48]', '2026-07-04 18:01:00'),
(10, 10, 'What should be tested before demo day?', '[0.17, 0.27, 0.35, 0.47]', '2026-07-04 18:31:00');

INSERT INTO `Responses` VALUES
(1, 1, 1, 'The system compares the query embedding against stored chunk embeddings and retrieves the most similar chunks as context.', '2026-07-04 14:01:10'),
(2, 2, 1, 'Store each chunk with a chunk_id, document_id, chunk_text, and embedding_vector so the RAG system can retrieve it.', '2026-07-04 14:31:10'),
(3, 3, 2, 'Premium users can access models connected to their tier through the Access relationship.', '2026-07-04 15:01:10'),
(4, 4, 6, 'An embedding vector is a numeric representation of text that allows similarity comparison during retrieval.', '2026-07-04 15:31:10'),
(5, 5, 3, 'A clear prompt states the task, gives useful context, and specifies the desired output format.', '2026-07-04 16:01:10'),
(6, 6, 4, 'Conversation history is stored through Conversations, Queries, Responses, and their relationship tables.', '2026-07-04 16:31:10'),
(7, 7, 1, 'Normalization helps avoid duplicated facts and keeps updates consistent across related tables.', '2026-07-04 17:01:10'),
(8, 8, 2, 'Paid tier access is modeled by connecting Users to Tiers and Tiers to Models.', '2026-07-04 17:31:10'),
(9, 9, 8, 'The application sends the prompt and retrieved context to the local model server, then stores the returned answer.', '2026-07-04 18:01:10'),
(10, 10, 9, 'Before demo day, test account creation, login, uploads, chunk retrieval, model responses, and audit logging.', '2026-07-04 18:31:10');

INSERT INTO `Audit_Log` VALUES
(1, 1, 'User account created for ethanv', 'CREATE_USER', '2026-07-01 10:00:00'),
(2, 2, 'Payment completed for Student tier', 'PAYMENT', '2026-07-02 12:05:00'),
(3, 11, 'Admin uploaded rag_overview.pdf', 'UPLOAD_DOCUMENT', '2026-07-03 09:00:00'),
(4, 1, 'User submitted query about RAG retrieval', 'SUBMIT_QUERY', '2026-07-04 14:01:00'),
(5, 3, 'Payment completed for Standard tier', 'PAYMENT', '2026-07-02 12:10:00'),
(6, 12, 'Admin uploaded mysql_notes.txt', 'UPLOAD_DOCUMENT', '2026-07-03 09:10:00'),
(7, 5, 'User created prompt writing conversation', 'CREATE_CONVERSATION', '2026-07-04 16:00:00'),
(8, 8, 'User asked about paid model access', 'SUBMIT_QUERY', '2026-07-04 17:31:00'),
(9, 14, 'Admin reviewed vector_search_guide.pdf', 'ADMIN_REVIEW', '2026-07-03 09:35:00'),
(10, 10, 'User submitted testing checklist query', 'SUBMIT_QUERY', '2026-07-04 18:31:00');

INSERT INTO `Triggers` VALUES
(1, 1),
(2, 2),
(11, 3),
(1, 4),
(3, 5),
(12, 6),
(5, 7),
(8, 8),
(14, 9),
(10, 10);

INSERT INTO `Pays` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Sets` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(5, 10);

INSERT INTO `Has` VALUES
(1, 1, '2026-07-02 12:00:00'),
(2, 2, '2026-07-02 12:05:00'),
(3, 3, '2026-07-02 12:10:00'),
(4, 4, '2026-07-02 12:15:00'),
(5, 5, '2026-07-02 12:20:00'),
(6, 6, '2026-07-02 12:25:00'),
(7, 7, '2026-07-02 12:30:00'),
(8, 8, '2026-07-02 12:35:00'),
(9, 9, '2026-07-02 12:40:00'),
(10, 5, '2026-07-02 12:45:00');

INSERT INTO `Creates` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Owns` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Access` VALUES
(1, 1),
(2, 1),
(2, 6),
(3, 1),
(3, 2),
(4, 3),
(5, 1),
(5, 2),
(6, 7),
(7, 8);

INSERT INTO `Prompts` VALUES
(1, 1, '2026-07-04 14:01:05'),
(2, 1, '2026-07-04 14:31:05'),
(3, 2, '2026-07-04 15:01:05'),
(4, 6, '2026-07-04 15:31:05'),
(5, 3, '2026-07-04 16:01:05'),
(6, 4, '2026-07-04 16:31:05'),
(7, 1, '2026-07-04 17:01:05'),
(8, 2, '2026-07-04 17:31:05'),
(9, 8, '2026-07-04 18:01:05'),
(10, 9, '2026-07-04 18:31:05');

INSERT INTO `Generates` VALUES
(1, 1),
(1, 2),
(2, 3),
(6, 4),
(3, 5),
(4, 6),
(1, 7),
(2, 8),
(8, 9),
(9, 10);

INSERT INTO `Retrieves` VALUES
(1, 1, 1),
(2, 2, 2),
(3, 3, 3),
(4, 4, 4),
(5, 5, 5),
(6, 6, 6),
(7, 7, 7),
(8, 8, 8),
(9, 9, 9),
(10, 10, 10);

INSERT INTO `Answers` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Contains_Response` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Contains_Query` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

INSERT INTO `Manages` VALUES
(11, 1, '2026-07-03 09:00:00'),
(12, 2, '2026-07-03 09:10:00'),
(13, 3, '2026-07-03 09:20:00'),
(14, 4, '2026-07-03 09:30:00'),
(15, 5, '2026-07-03 09:40:00'),
(16, 6, '2026-07-03 10:00:00'),
(17, 7, '2026-07-03 10:10:00'),
(18, 8, '2026-07-03 10:20:00'),
(19, 9, '2026-07-03 10:30:00'),
(20, 10, '2026-07-03 10:40:00');

INSERT INTO `Splits_Into` VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10);

SELECT 'Users' AS table_name, COUNT(*) AS row_count FROM `Users`
UNION ALL SELECT 'User_Hashes', COUNT(*) FROM `User_Hashes`
UNION ALL SELECT 'Admins', COUNT(*) FROM `Admins`
UNION ALL SELECT 'Tiers', COUNT(*) FROM `Tiers`
UNION ALL SELECT 'Payments', COUNT(*) FROM `Payments`
UNION ALL SELECT 'Models', COUNT(*) FROM `Models`
UNION ALL SELECT 'Documents', COUNT(*) FROM `Documents`
UNION ALL SELECT 'Chunks', COUNT(*) FROM `Chunks`
UNION ALL SELECT 'Conversations', COUNT(*) FROM `Conversations`
UNION ALL SELECT 'Queries', COUNT(*) FROM `Queries`
UNION ALL SELECT 'Responses', COUNT(*) FROM `Responses`
UNION ALL SELECT 'Audit_Log', COUNT(*) FROM `Audit_Log`
UNION ALL SELECT 'Triggers', COUNT(*) FROM `Triggers`
UNION ALL SELECT 'Pays', COUNT(*) FROM `Pays`
UNION ALL SELECT 'Sets', COUNT(*) FROM `Sets`
UNION ALL SELECT 'Has', COUNT(*) FROM `Has`
UNION ALL SELECT 'Creates', COUNT(*) FROM `Creates`
UNION ALL SELECT 'Owns', COUNT(*) FROM `Owns`
UNION ALL SELECT 'Access', COUNT(*) FROM `Access`
UNION ALL SELECT 'Prompts', COUNT(*) FROM `Prompts`
UNION ALL SELECT 'Generates', COUNT(*) FROM `Generates`
UNION ALL SELECT 'Retrieves', COUNT(*) FROM `Retrieves`
UNION ALL SELECT 'Answers', COUNT(*) FROM `Answers`
UNION ALL SELECT 'Contains_Response', COUNT(*) FROM `Contains_Response`
UNION ALL SELECT 'Contains_Query', COUNT(*) FROM `Contains_Query`
UNION ALL SELECT 'Manages', COUNT(*) FROM `Manages`
UNION ALL SELECT 'Splits_Into', COUNT(*) FROM `Splits_Into`;
