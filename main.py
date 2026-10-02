import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

import config
import database as db
from content_filter import check_message
from keyboards import (
    admin_kb, ban_kb, chat_kb, language_kb, role_kb, topic_kb,
)
from nicknames import generate_nickname


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

router = Router()


# ---------- FSM ----------

class Setup(StatesGroup):
    language = State()
    role = State()
    topic = State()


class Chat(StatesGroup):
    report_reason = State()


# ---------- HELPERS ----------

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def send_match_notification(bot: Bot, user_id: int, partner_nickname: str, topic: str) -> None:
    try:
        await bot.send_message(
            user_id,
            f"🎉 <b>Нашёл пару!</b>\n\n"
            f"Твой собеседник: <b>{partner_nickname}</b>\n"
            f"Тема: {config.TOPICS[topic]}\n\n"
            f"Просто пиши сообщения — я буду пересылать их собеседнику.\n"
            f"/stop — завершить чат.",
            reply_markup=chat_kb(),
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("Не удалось отправить уведомление о паре user=%s", user_id)


async def try_match(bot: Bot, user_id: int) -> None:
    user = await db.get_user(user_id)
    if not user:
        return

    opposite_role = "seeker" if user["role"] == "helper" else "helper"

    candidate = await db.find_candidate(
        language=user["language"],
        role=opposite_role,
        topic=user["topic"],
        exclude_id=user_id,
    )

    if candidate:
        await db.set_pair(user_id, candidate["user_id"])
        await send_match_notification(bot, user_id, candidate["nickname"], user["topic"])
        await send_match_notification(bot, candidate["user_id"], user["nickname"], user["topic"])
    else:
        await db.update_user(user_id, state="searching")
        await bot.send_message(
            user_id,
            "⏳ Пока никого нет. Я сообщу, как только найдётся подходящий собеседник.\n\n"
            "Напиши /cancel, чтобы отменить поиск.",
        )


async def end_chat(bot: Bot, user_id: int, notify_partner: bool = True) -> None:
    user = await db.get_user(user_id)
    if not user:
        return
    partner_id = user["partner_id"]

    await db.update_user(user_id, state="idle", partner_id=None)

    if partner_id and notify_partner:
        partner = await db.get_user(partner_id)
        if partner and partner["state"] == "in_chat":
            await db.update_user(partner_id, state="idle", partner_id=None)
            try:
                await bot.send_message(
                    partner_id,
                    "🚪 Собеседник завершил чат.\n\n/start — найти нового.",
                )
            except Exception:
                pass


# ---------- /start ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if user and user["is_banned"]:
        await message.answer("🚫 Вы забанены и не можете пользоваться ботом.")
        return

    # Если пользователь уже в чате — сообщаем и не сбиваем сессию
    if user and user["state"] == "in_chat":
        await message.answer("Ты сейчас в чате. Напиши /stop, чтобы завершить.")
        return

    # Если идёт поиск — отменяем, начинаем заново
    if user and user["state"] == "searching":
        await db.update_user(user_id, state="idle")

    await state.clear()

    if not user:
        nickname = generate_nickname()
        await db.create_user(user_id, message.from_user.username, nickname)
        await message.answer(
            f"👋 Привет! Я — анонимный помощник.\n\n"
            f"Твой анонимный ник: <b>{nickname}</b>\n\n"
            f"Здесь ты можешь получить честный совет или помочь другим — "
            f"без осуждения, понтов и раскрытия личности.\n\n"
            f"🌍 Выбери язык общения:",
            reply_markup=language_kb(),
            parse_mode="HTML",
        )
        await state.set_state(Setup.language)
        return

    # Существующий пользователь — сразу к выбору роли
    await message.answer(
        f"С возвращением, <b>{user['nickname']}</b>!\n\n"
        f"Кем ты хочешь быть в этом разговоре?",
        reply_markup=role_kb(),
        parse_mode="HTML",
    )
    await state.set_state(Setup.role)


# ---------- LANGUAGE ----------

@router.callback_query(F.data.startswith("lang:"), Setup.language)
async def set_language(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(":")[1]
    if lang not in config.LANGUAGES:
        await callback.answer("Неизвестный язык", show_alert=True)
        return

    await db.update_user(callback.from_user.id, language=lang)
    await callback.message.edit_text(
        "✅ Язык сохранён.\n\nТеперь выбери свою роль:",
        reply_markup=role_kb(),
    )
    await state.set_state(Setup.role)
    await callback.answer()


# ---------- ROLE ----------

@router.callback_query(F.data.startswith("role:"), Setup.role)
async def set_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    if role not in config.ROLES:
        await callback.answer("Неизвестная роль", show_alert=True)
        return

    await db.update_user(callback.from_user.id, role=role)
    await callback.message.edit_text(
        "Отлично! Теперь выбери тему:",
        reply_markup=topic_kb(),
    )
    await state.set_state(Setup.topic)
    await callback.answer()


# ---------- TOPIC ----------

@router.callback_query(F.data.startswith("topic:"), Setup.topic)
async def set_topic(callback: CallbackQuery, state: FSMContext) -> None:
    topic = callback.data.split(":")[1]
    if topic not in config.TOPICS:
        await callback.answer("Неизвестная тема", show_alert=True)
        return

    await db.update_user(callback.from_user.id, topic=topic)
    await state.clear()
    await callback.message.edit_text("🔎 Ищу собеседника...")
    await callback.answer()
    await try_match(callback.bot, callback.from_user.id)


# ---------- /cancel ----------

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    user = await db.get_user(message.from_user.id)
    if user and user["state"] == "searching":
        await db.update_user(user["user_id"], state="idle")
    await state.clear()
    await message.answer("Отменено. Напиши /start, чтобы начать заново.")


# ---------- /stop ----------

@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or user["state"] != "in_chat":
        await message.answer("Ты сейчас не в чате.")
        return
    await end_chat(message.bot, user["user_id"])
    await message.answer("✅ Чат завершён. Напиши /start, чтобы найти нового собеседника.")


# ---------- /profile ----------

@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Напиши /start, чтобы начать.")
        return
    lang = config.LANGUAGES.get(user["language"], "—")
    role = config.ROLES.get(user["role"], "—")
    topic = config.TOPICS.get(user["topic"], "—")
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"Ник: <b>{user['nickname']}</b>\n"
        f"Язык: {lang}\n"
        f"Роль: {role}\n"
        f"Тема: {topic}\n"
        f"Премиум: {'да' if user['is_premium'] else 'нет'}",
        parse_mode="HTML",
    )


# ---------- /help ----------

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Как это работает</b>\n\n"
        "1. /start — выбираешь язык, роль и тему.\n"
        "2. Бот ищет собеседника с противоположной ролью в той же теме.\n"
        "3. Когда пара найдена — вы общаетесь анонимно через бота.\n"
        "4. /stop — завершить чат.\n"
        "5. /cancel — отменить поиск.\n\n"
        "🔒 Ссылки, телефоны и мат блокируются автоматически.",
        parse_mode="HTML",
    )


# ---------- REPORT ----------

@router.callback_query(F.data == "chat:report")
async def report_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = await db.get_user(callback.from_user.id)
    if not user or user["state"] != "in_chat":
        await callback.answer("Ты не в чате.", show_alert=True)
        return
    await state.set_state(Chat.report_reason)
    await callback.message.answer(
        "Опиши коротко, что не так с собеседником. Это увидит только администратор:"
    )
    await callback.answer()


@router.message(Chat.report_reason)
async def report_submit(message: Message, state: FSMContext) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or user["state"] != "in_chat":
        await state.clear()
        await message.answer("Чат уже завершён.")
        return

    reason = (message.text or "").strip() or "(без описания)"
    partner_id = user["partner_id"]

    await db.add_complaint(user["user_id"], partner_id, reason)
    await state.clear()
    await message.answer("✅ Жалоба отправлена администратору. Спасибо!")

    # Уведомляем всех админов
    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"⚠️ <b>Новая жалоба</b>\n"
                f"От: {user['nickname']} (<code>{user['user_id']}</code>)\n"
                f"На: <code>{partner_id}</code>\n"
                f"Причина: {html.escape(reason)}",
                reply_markup=ban_kb(partner_id),
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("Не удалось уведомить админа %s", admin_id)


# ---------- STOP CHAT BUTTON ----------

@router.callback_query(F.data == "chat:stop")
async def stop_chat_cb(callback: CallbackQuery, state: FSMContext) -> None:
    user = await db.get_user(callback.from_user.id)
    if not user or user["state"] != "in_chat":
        await callback.answer("Ты не в чате.", show_alert=True)
        return
    await state.clear()
    await end_chat(callback.bot, user["user_id"])
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Чат завершён")


# ---------- ADMIN ----------

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 Админ-панель:", reply_markup=admin_kb())


@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/ban &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])

    target = await db.get_user(target_id)
    if not target:
        await message.answer("Пользователь не найден.")
        return

    # Если был в чате — завершим и уведомим партнёра
    if target["state"] == "in_chat" and target["partner_id"]:
        await end_chat(message.bot, target_id, notify_partner=False)
        try:
            await message.bot.send_message(
                target["partner_id"],
                "🚪 Собеседник был забанен администратором. Чат завершён.",
            )
        except Exception:
            pass

    await db.ban_user(target_id, reason="Ручной бан")
    await message.answer(f"✅ Пользователь <code>{target_id}</code> забанен.", parse_mode="HTML")
    try:
        await message.bot.send_message(target_id, "🚫 Вы были забанены администратором.")
    except Exception:
        pass


@router.callback_query(F.data == "admin:complaints")
async def show_complaints(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return

    complaints = await db.get_complaints(limit=20)
    if not complaints:
        await callback.message.answer("Жалоб нет.")
        await callback.answer()
        return

    for c in complaints:
        text = (
            f"⚠️ <b>Жалоба #{c['id']}</b>\n"
            f"От: <code>{c['from_user_id']}</code>\n"
            f"На: <code>{c['against_user_id']}</code>\n"
            f"Причина: {html.escape(c['reason'] or '—')}\n"
            f"Дата: {c['created_at']}"
        )
        await callback.message.answer(
            text,
            reply_markup=ban_kb(c["against_user_id"]),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ban:"))
async def ban_from_complaint(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return

    target_id = int(callback.data.split(":")[2])
    target = await db.get_user(target_id)

    if not target:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    if target["is_banned"]:
        await callback.answer("Уже забанен.", show_alert=True)
        return

    # Завершаем активный чат
    if target["state"] == "in_chat" and target["partner_id"]:
        partner_id = target["partner_id"]
        await end_chat(callback.bot, target_id, notify_partner=False)
        try:
            await callback.bot.send_message(
                partner_id,
                "🚪 Собеседник был забанен администратором. Чат завершён.",
            )
        except Exception:
            pass

    await db.ban_user(target_id, reason="Бан по жалобе")

    try:
        await callback.bot.send_message(target_id, "🚫 Вы были забанены администратором.")
    except Exception:
        pass

    try:
        await callback.message.edit_text(callback.message.html_text + "\n\n✅ <b>ЗАБАНЕН</b>", parse_mode="HTML")
    except Exception:
        pass

    await callback.answer("Пользователь забанен")


# ---------- CATCH-ALL: обычные сообщения ----------

@router.message(F.text | F.caption)
async def handle_message(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await message.answer("Напиши /start, чтобы начать.")
        return

    if user["is_banned"]:
        return

    # Если пользователь в процессе настройки через FSM — просим завершить
    current = await state.get_state()
    if current is not None:
        await message.answer("Пожалуйста, заверши настройку с помощью кнопок выше.")
        return

    if user["state"] == "in_chat":
        await relay_message(message, user)
    elif user["state"] == "searching":
        await message.answer("⏳ Всё ещё ищу собеседника… /cancel — отменить.")
    else:
        await message.answer("Напиши /start, чтобы выбрать роль и тему.")


@router.message()
async def handle_non_text(message: Message) -> None:
    await message.answer("Поддерживаются только текстовые сообщения.")


async def relay_message(message: Message, user: dict) -> None:
    text = message.text or message.caption or ""
    text = text.strip()
    if not text:
        return

    reason = check_message(text)
    if reason:
        await message.answer(f"❌ Сообщение не отправлено: {reason}")
        return

    partner_id = user["partner_id"]
    if not partner_id:
        await db.update_user(user["user_id"], state="idle", partner_id=None)
        await message.answer("Собеседник отключился. Напиши /start, чтобы найти нового.")
        return

    safe = html.escape(text)
    try:
        await message.bot.send_message(
            partner_id,
            f"<b>{user['nickname']}:</b>\n{safe}",
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("Ошибка пересылки от %s к %s", user["user_id"], partner_id)
        await message.answer("⚠️ Не удалось доставить сообщение. Возможно, собеседник заблокировал бота.")


# ---------- ENTRY POINT ----------

async def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    await db.init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info("Бот запущен. Админы: %s", config.ADMIN_IDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")