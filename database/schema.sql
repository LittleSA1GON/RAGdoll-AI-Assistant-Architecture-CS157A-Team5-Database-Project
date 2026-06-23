CREATE DATABASE IF NOT EXISTS ragdoll;
USE ragdoll;

DROP TABLE IF EXISTS models;

CREATE TABLE models (
    model_id INT AUTO_INCREMENT PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    access_level VARCHAR(50) NOT NULL
);

INSERT INTO models (model_name, access_level)
VALUES
('Llama', 'Free'),
('Gemma', 'Paid'),
('Mythos', 'Admin');

SELECT * FROM models;