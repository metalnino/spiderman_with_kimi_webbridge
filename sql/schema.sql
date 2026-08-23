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
  read_at DATETIME NULL COMMENT '已读时间',
  lead_status VARCHAR(32) NOT NULL DEFAULT '待处理' COMMENT '待处理/跟进中/已成交/已放弃/忽略',
  amount_status VARCHAR(32) NULL COMMENT '待确认/已确认/无金额',
  remark VARCHAR(512) NULL COMMENT '备注',
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
  notice_stage VARCHAR(32) NULL COMMENT '阶段: intent/bidding/change/preselect/opening/candidate/result/terminated/other',
  stage_rank TINYINT UNSIGNED NULL COMMENT '时间线顺序',
  project_key CHAR(40) NULL COMMENT '项目时间线键 sha1(city|core)',
  project_name VARCHAR(512) NULL COMMENT '核心项目名（展示/调试）',
  summary TEXT NULL COMMENT '详情正文摘要（回填）',
  tenderfile_path VARCHAR(512) NULL COMMENT '附件落盘路径（回填）',
  detail_status VARCHAR(32) NULL COMMENT '最近一次回填状态',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_source_external (source_id, external_id),
  UNIQUE KEY uk_content_hash (content_hash),
  KEY idx_city (city),
  KEY idx_publish_date (publish_date),
  KEY idx_keyword (keyword),
  KEY idx_bid_status (bid_status),
  KEY idx_stage (notice_stage),
  KEY idx_project (project_key)
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
