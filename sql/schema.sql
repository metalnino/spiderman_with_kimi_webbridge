-- 招采爬虫库：强制 utf8mb4 支持中文
CREATE DATABASE IF NOT EXISTS spiderman_bids
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE spiderman_bids;

CREATE TABLE IF NOT EXISTS notices (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id VARCHAR(32) NOT NULL COMMENT 'cebpub/ggzy/ccgp/chinabidding',
  source_name VARCHAR(64) NOT NULL,
  external_id VARCHAR(128) NULL COMMENT '站点主键 uuid/id',
  title VARCHAR(512) NOT NULL,
  publish_date DATETIME NULL,
  open_time DATETIME NULL,
  deadline DATETIME NULL,
  province VARCHAR(64) NULL,
  city VARCHAR(64) NULL,
  region_text VARCHAR(128) NULL,
  keyword VARCHAR(64) NULL,
  bid_status VARCHAR(32) NULL COMMENT '可投标/已开标/未知',
  clean_status VARCHAR(32) NULL COMMENT 'pass/drop/review',
  clean_reason VARCHAR(255) NULL,
  manual_label VARCHAR(32) NULL COMMENT 'relevant/irrelevant/followed',
  amount DECIMAL(18,2) NULL,
  amount_text VARCHAR(128) NULL,
  buyer VARCHAR(256) NULL,
  agency VARCHAR(256) NULL,
  project_code VARCHAR(128) NULL,
  notice_type VARCHAR(64) NULL,
  detail_url VARCHAR(1024) NULL,
  official_url VARCHAR(1024) NULL,
  raw_json JSON NULL,
  content_hash CHAR(40) NOT NULL COMMENT '去重哈希',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_source_external (source_id, external_id),
  UNIQUE KEY uk_content_hash (content_hash),
  KEY idx_city (city),
  KEY idx_publish_date (publish_date),
  KEY idx_keyword (keyword),
  KEY idx_bid_status (bid_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS entities (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(256) NOT NULL,
  entity_type VARCHAR(32) NULL COMMENT 'buyer/agency/other',
  city VARCHAR(64) NULL,
  province VARCHAR(64) NULL,
  notice_count INT NOT NULL DEFAULT 0,
  last_notice_at DATETIME NULL,
  next_bid_hint VARCHAR(256) NULL,
  meta_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS crawl_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id VARCHAR(32) NOT NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status VARCHAR(32) NOT NULL,
  item_count INT NOT NULL DEFAULT 0,
  note VARCHAR(512) NULL,
  meta_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_source_started (source_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
