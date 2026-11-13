"""Send queued Telegram announcements without retrying uncertain deliveries."""
from db import get_connection
from telegram_service import send_message


def process_announcements(limit=5):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE shrimp.telegram_announcement_recipients r SET status = 'unknown'
                           FROM shrimp.telegram_announcement_chats c WHERE r.announcement_id = c.announcement_id
                           AND r.chat_id = c.chat_id AND r.status = 'processing' AND c.status = 'processing'
                           AND c.started_at < now() - interval '2 minutes'""")
            cur.execute("""UPDATE shrimp.telegram_announcement_chats SET status = 'unknown'
                           WHERE status = 'processing' AND started_at < now() - interval '2 minutes'""")
        conn.commit()
        for _ in range(limit):
            with conn.cursor() as cur:
                cur.execute("""SELECT c.announcement_id, c.chat_id, a.message
                               FROM shrimp.telegram_announcement_chats c
                               JOIN shrimp.telegram_announcements a ON a.id = c.announcement_id
                               WHERE c.status = 'pending' ORDER BY a.created_at
                               FOR UPDATE OF c SKIP LOCKED LIMIT 1""")
                chat = cur.fetchone()
                if not chat:
                    conn.commit()
                    return
                key = (chat['announcement_id'], chat['chat_id'])
                cur.execute("""UPDATE shrimp.telegram_announcement_recipients r SET status = 'skipped'
                               FROM shrimp.users u WHERE r.user_id = u.id AND r.announcement_id = %s AND r.chat_id = %s
                               AND r.status = 'pending' AND (NOT u.is_active OR u.telegram_chat_id IS DISTINCT FROM r.chat_id)""", key)
                cur.execute("""UPDATE shrimp.telegram_announcement_recipients SET status = 'processing'
                               WHERE announcement_id = %s AND chat_id = %s AND status = 'pending' RETURNING user_id""", key)
                eligible = cur.fetchall()
                cur.execute("UPDATE shrimp.telegram_announcement_chats SET status = %s, started_at = now() WHERE announcement_id = %s AND chat_id = %s",
                            ('processing' if eligible else 'skipped', *key))
            conn.commit()
            if not eligible:
                continue
            success, _ = send_message(chat['chat_id'], chat['message'])
            # Failure can mean a timeout after Telegram accepted the message. Keep it uncertain.
            status = 'sent' if success else 'unknown'
            with conn.cursor() as cur:
                cur.execute("UPDATE shrimp.telegram_announcement_recipients SET status = %s WHERE announcement_id = %s AND chat_id = %s AND status = 'processing'", (status, *key))
                cur.execute("UPDATE shrimp.telegram_announcement_chats SET status = %s WHERE announcement_id = %s AND chat_id = %s AND status = 'processing'", (status, *key))
            conn.commit()
    finally:
        conn.close()
