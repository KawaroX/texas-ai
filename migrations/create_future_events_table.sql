-- 未来事件管理表
-- 创建时间: 2024-12-14
-- 用途: 存储从对话中提取的未来事件，支持提醒功能

CREATE TABLE IF NOT EXISTS future_events (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 事件基本信息
    event_text TEXT NOT NULL,                    -- 原始描述（用户说的话）
    event_summary VARCHAR(100) NOT NULL,         -- AI生成的简短摘要（5-10字）
    event_date DATE,                             -- 事件日期（可为null，表示不确定时间）
    event_time TIME,                             -- 事件时间（可为null）

    -- 时间戳
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- 状态管理
    status VARCHAR(20) DEFAULT 'pending',        -- pending/active/expired/completed/cancelled

    -- 提醒功能
    need_reminder BOOLEAN DEFAULT false,         -- 是否需要主动提醒
    reminder_datetime TIMESTAMP,                 -- 提醒时间点（event_datetime - advance_time）
    reminder_sent BOOLEAN DEFAULT false,         -- 是否已发送提醒
    reminder_advance_minutes INTEGER DEFAULT 30, -- 提前多久提醒（分钟）

    -- 上下文信息
    source_channel VARCHAR(50),                  -- 来源频道ID
    created_by VARCHAR(100),                     -- 用户ID
    context_messages JSONB,                      -- 提取时的对话上下文（用于调试和AI学习）

    -- 元数据
    extraction_confidence FLOAT,                 -- AI提取的置信度（0.0-1.0）
    metadata JSONB,                              -- 额外元数据（如地点、参与人等）

    -- 归档信息
    archived_to_mem0 BOOLEAN DEFAULT false,      -- 是否已归档到Mem0
    mem0_memory_id VARCHAR(100)                  -- Mem0中的记忆ID
);

-- 索引优化
-- 1. 按日期时间查询活跃事件
CREATE INDEX idx_future_events_datetime ON future_events(event_date, event_time)
WHERE status IN ('pending', 'active');

-- 2. 查询待发送的提醒
CREATE INDEX idx_future_events_reminder ON future_events(reminder_datetime)
WHERE need_reminder = true AND reminder_sent = false AND status = 'active';

-- 3. 按状态查询
CREATE INDEX idx_future_events_status ON future_events(status);

-- 4. 按用户和频道查询
CREATE INDEX idx_future_events_user ON future_events(created_by, source_channel);

-- 5. 查询未归档的过期事件
CREATE INDEX idx_future_events_archive ON future_events(status, archived_to_mem0)
WHERE status = 'expired' AND archived_to_mem0 = false;

-- 自动更新updated_at触发器
CREATE OR REPLACE FUNCTION update_future_events_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_future_events_updated_at
BEFORE UPDATE ON future_events
FOR EACH ROW
EXECUTE FUNCTION update_future_events_updated_at();

-- 事件修改历史表（用于审计）
CREATE TABLE IF NOT EXISTS future_events_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES future_events(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,                 -- create/update/cancel/complete/expire
    changed_fields JSONB,                        -- 修改的字段
    changed_by VARCHAR(100),                     -- 操作人
    changed_at TIMESTAMP DEFAULT NOW(),
    reason TEXT                                  -- 修改原因
);

-- 历史表索引
CREATE INDEX idx_events_history_event_id ON future_events_history(event_id);
CREATE INDEX idx_events_history_action ON future_events_history(action);

-- 插入示例数据的函数（可选，用于测试）
CREATE OR REPLACE FUNCTION insert_sample_future_event()
RETURNS UUID AS $$
DECLARE
    new_event_id UUID;
BEGIN
    INSERT INTO future_events (
        event_text,
        event_summary,
        event_date,
        event_time,
        need_reminder,
        reminder_datetime,
        reminder_advance_minutes,
        source_channel,
        created_by,
        extraction_confidence,
        metadata
    ) VALUES (
        '明天下午三点我要去考试',
        '参加考试',
        CURRENT_DATE + INTERVAL '1 day',
        '15:00:00',
        true,
        (CURRENT_DATE + INTERVAL '1 day' + TIME '15:00:00') - INTERVAL '30 minutes',
        30,
        'test_channel_123',
        'kawaro',
        0.95,
        '{"location": "考场A101", "importance": "high"}'::jsonb
    ) RETURNING id INTO new_event_id;

    RETURN new_event_id;
END;
$$ LANGUAGE plpgsql;

-- 清理过期事件的函数
CREATE OR REPLACE FUNCTION cleanup_old_archived_events()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- 删除90天前已归档的过期事件
    DELETE FROM future_events
    WHERE status = 'expired'
      AND archived_to_mem0 = true
      AND updated_at < NOW() - INTERVAL '90 days';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- 标记过期事件的函数
CREATE OR REPLACE FUNCTION expire_past_events()
RETURNS TABLE (
    event_id UUID,
    event_summary VARCHAR(100),
    event_date DATE,
    event_time TIME
) AS $$
BEGIN
    RETURN QUERY
    UPDATE future_events
    SET status = 'expired',
        updated_at = NOW()
    WHERE status IN ('pending', 'active')
      AND (
          -- 有日期时间的事件
          (event_date IS NOT NULL AND event_time IS NOT NULL
           AND (event_date + event_time) < NOW())
          OR
          -- 只有日期的事件（当天结束）
          (event_date IS NOT NULL AND event_time IS NULL
           AND event_date < CURRENT_DATE)
      )
    RETURNING id, event_summary, event_date, event_time;
END;
$$ LANGUAGE plpgsql;

-- 添加注释
COMMENT ON TABLE future_events IS '未来事件管理表，存储从对话中提取的事件';
COMMENT ON COLUMN future_events.event_text IS '用户原话';
COMMENT ON COLUMN future_events.event_summary IS 'AI生成的简短摘要';
COMMENT ON COLUMN future_events.reminder_datetime IS '提醒时间点 = event_datetime - advance_minutes';
COMMENT ON COLUMN future_events.context_messages IS '提取时的对话上下文（JSONB数组）';
COMMENT ON COLUMN future_events.metadata IS '额外元数据，如 {"location": "...", "participants": [...], "importance": "high"}';
