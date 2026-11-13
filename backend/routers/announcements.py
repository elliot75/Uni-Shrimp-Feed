from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from auth import require_admin
from db import get_db
from models import TelegramAnnouncement
from telegram_service import bot_configured

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def job_result(conn, job_id, admin):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, message, created_by FROM shrimp.telegram_announcements WHERE id = %s", (str(job_id),))
        job = cur.fetchone()
        if not job or str(job['created_by']) != str(admin['id']):
            raise HTTPException(status_code=404, detail="announcement_not_found")
        cur.execute("""SELECT r.user_id, r.status, u.username, u.display_name
                       FROM shrimp.telegram_announcement_recipients r JOIN shrimp.users u ON u.id = r.user_id
                       WHERE r.announcement_id = %s ORDER BY u.username""", (str(job_id),))
        recipients = cur.fetchall()
    return {"id": str(job_id), "message": job['message'], "recipients": [
        {"id": str(r['user_id']), "name": r['display_name'] or r['username'], "username": r['username'], "status": r['status']}
        for r in recipients]}


@router.post('/telegram', status_code=202)
def create_announcement(body: TelegramAnnouncement, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    if not bot_configured():
        raise HTTPException(status_code=503, detail='telegram_not_configured')
    ids = list(dict.fromkeys(str(uid) for uid in body.user_ids))
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""INSERT INTO shrimp.telegram_announcements (id, created_by, message)
                       VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
                    (str(body.id), admin['id'], body.message))
        created = cur.fetchone()
        if created:
            cur.execute("""SELECT id, telegram_chat_id FROM shrimp.users WHERE id = ANY(%s::uuid[])
                           AND is_active AND telegram_chat_id IS NOT NULL AND telegram_chat_id <> ''""", (ids,))
            recipients = cur.fetchall()
            if len(recipients) != len(ids):
                conn.rollback()
                raise HTTPException(status_code=409, detail='recipients_changed')
            for chat in set(r['telegram_chat_id'] for r in recipients):
                cur.execute("INSERT INTO shrimp.telegram_announcement_chats (announcement_id, chat_id) VALUES (%s, %s)", (str(body.id), chat))
            for r in recipients:
                cur.execute("INSERT INTO shrimp.telegram_announcement_recipients (announcement_id, user_id, chat_id) VALUES (%s, %s, %s)",
                            (str(body.id), str(r['id']), r['telegram_chat_id']))
            conn.commit()
        else:
            result = job_result(conn, body.id, admin)
            if result['message'] != body.message or {r['id'] for r in result['recipients']} != set(ids):
                raise HTTPException(status_code=409, detail='announcement_conflict')
            return result
    return job_result(conn, body.id, admin)


@router.get('/telegram/{job_id}')
def get_announcement(job_id: UUID, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    return job_result(conn, job_id, admin)
