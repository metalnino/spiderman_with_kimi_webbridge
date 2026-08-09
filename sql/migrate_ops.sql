USE spiderman_bids;

ALTER TABLE notices
  ADD COLUMN IF NOT EXISTS clean_status VARCHAR(32) NULL COMMENT 'pass/drop/review' AFTER bid_status,
  ADD COLUMN IF NOT EXISTS clean_reason VARCHAR(255) NULL AFTER clean_status,
  ADD COLUMN IF NOT EXISTS manual_label VARCHAR(32) NULL COMMENT 'relevant/irrelevant/followed' AFTER clean_reason;

-- MySQL 8.0.28 may not support ADD COLUMN IF NOT EXISTS; use procedure-free checks in Python migrate

CREATE TABLE IF NOT EXISTS clean_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  notice_id BIGINT UNSIGNED NULL,
  title VARCHAR(512) NOT NULL,
  source_id VARCHAR(32) NULL,
  decision VARCHAR(32) NOT NULL,
  reason VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_decision (decision),
  KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS captcha_todos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id VARCHAR(32) NOT NULL,
  detail_url VARCHAR(1024) NOT NULL,
  title VARCHAR(512) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'open',
  note VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keyword_state (
  keyword VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  group_name VARCHAR(32) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (keyword)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
