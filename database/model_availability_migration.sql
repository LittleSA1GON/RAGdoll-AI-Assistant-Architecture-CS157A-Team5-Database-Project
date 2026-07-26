USE ragdoll_db;

-- Run this once for an existing database created before is_available existed.
SET @availability_column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'Models'
      AND COLUMN_NAME = 'is_available'
);

SET @availability_migration = IF(
    @availability_column_exists = 0,
    'ALTER TABLE Models ADD COLUMN is_available TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled',
    'SELECT ''Models.is_available already exists'' AS status'
);

PREPARE availability_statement FROM @availability_migration;
EXECUTE availability_statement;
DEALLOCATE PREPARE availability_statement;

-- The next local model scan will set files that exist to 1.
UPDATE Models
SET is_available = 0
WHERE model_location = 'local';
