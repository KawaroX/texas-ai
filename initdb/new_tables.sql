-- 创建 daily_schedules 表
CREATE TABLE IF NOT EXISTS daily_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL UNIQUE,
    schedule_data JSONB NOT NULL,
    weather VARCHAR(50),
    is_in_major_event BOOLEAN DEFAULT FALSE,
    major_event_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 添加触发器，以便在更新时自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_daily_schedules_updated_at ON daily_schedules;
CREATE TRIGGER set_daily_schedules_updated_at
BEFORE UPDATE ON daily_schedules
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- 创建 major_events 表（带数据完整性约束）
CREATE TABLE IF NOT EXISTS major_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    duration_days INTEGER NOT NULL CHECK (duration_days > 0),
    main_content TEXT,
    daily_summaries JSONB,
    event_type VARCHAR(100),
    status VARCHAR(50) DEFAULT 'planned',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_date >= start_date)
);

-- 创建 micro_experiences 表 (最终结构)
CREATE TABLE IF NOT EXISTS micro_experiences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    daily_schedule_id UUID NOT NULL REFERENCES daily_schedules(id) ON DELETE CASCADE,
    related_item_id UUID,
    experiences JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 创建GIN索引（提升JSON查询性能）
CREATE INDEX IF NOT EXISTS idx_micro_experiences_experiences_gin 
ON micro_experiences USING GIN(experiences);
-- 添加外键约束到 daily_schedules 表，关联 major_events
ALTER TABLE daily_schedules
ADD CONSTRAINT fk_major_event
FOREIGN KEY (major_event_id)
REFERENCES major_events(id)
ON DELETE SET NULL;

-- 创建每日计划的GIN索引
CREATE INDEX IF NOT EXISTS idx_daily_schedules_schedule_data_gin 
ON daily_schedules USING GIN(schedule_data);
