-- Миграция для создания таблицы истории диалогов

-- Таблица для хранения истории сообщений
CREATE TABLE IF NOT EXISTS chat_history (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,                    -- ID пользователя (Telegram ID или другой идентификатор)
    session_id VARCHAR(255),                          -- ID сессии для группировки сообщений
    message_type VARCHAR(50) NOT NULL,                -- Тип сообщения: 'user' или 'assistant'
    content TEXT NOT NULL,                            -- Текст сообщения
    metadata JSONB,                                   -- Дополнительная информация в JSON
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() -- Время создания сообщения
);

-- Индексы для оптимизации запросов
CREATE INDEX idx_chat_history_user_id ON chat_history(user_id);
CREATE INDEX idx_chat_history_session_id ON chat_history(session_id);
CREATE INDEX idx_chat_history_created_at ON chat_history(created_at);
CREATE INDEX idx_chat_history_user_created ON chat_history(user_id, created_at DESC);

-- Комментарии к таблице
COMMENT ON TABLE chat_history IS 'История диалогов пользователей с ботом';
COMMENT ON COLUMN chat_history.user_id IS 'Идентификатор пользователя (Telegram ID или другой)';
COMMENT ON COLUMN chat_history.session_id IS 'Идентификатор сессии для группировки сообщений';
COMMENT ON COLUMN chat_history.message_type IS 'Тип сообщения: user или assistant';
COMMENT ON COLUMN chat_history.content IS 'Текст сообщения';
COMMENT ON COLUMN chat_history.metadata IS 'Дополнительная информация (source, tools_used и т.д.)';
COMMENT ON COLUMN chat_history.created_at IS 'Время создания сообщения';
