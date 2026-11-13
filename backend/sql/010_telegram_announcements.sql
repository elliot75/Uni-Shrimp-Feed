CREATE TABLE IF NOT EXISTS shrimp.telegram_announcements (
    id uuid PRIMARY KEY,
    created_by uuid NOT NULL REFERENCES shrimp.users(id),
    message text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS shrimp.telegram_announcement_chats (
    announcement_id uuid NOT NULL REFERENCES shrimp.telegram_announcements(id) ON DELETE CASCADE,
    chat_id text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'unknown', 'sent', 'failed', 'skipped')),
    started_at timestamptz,
    PRIMARY KEY (announcement_id, chat_id)
);
CREATE TABLE IF NOT EXISTS shrimp.telegram_announcement_recipients (
    announcement_id uuid NOT NULL REFERENCES shrimp.telegram_announcements(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES shrimp.users(id),
    chat_id text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'unknown', 'sent', 'failed', 'skipped')),
    PRIMARY KEY (announcement_id, user_id),
    FOREIGN KEY (announcement_id, chat_id) REFERENCES shrimp.telegram_announcement_chats(announcement_id, chat_id)
);
