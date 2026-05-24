import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import TelegramError

# ══════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════
BOT_TOKEN  = "8874575430:AAEl5c4uu0-Nt6IvDNnZY21bZbr_2xV4e7k"
ADMIN_ID   = 8582094304
DATA_FILE  = "channels.json"          # файл хранения каналов
LINK_HOURS = 1                         # срок действия ссылки по умолчанию

# ══════════════════════════════════════════════
#  СОСТОЯНИЯ ConversationHandler
# ══════════════════════════════════════════════
WAIT_CHANNEL_ID, WAIT_CHANNEL_NAME, WAIT_HOURS = range(3)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  ХРАНИЛИЩЕ КАНАЛОВ (JSON)
# ══════════════════════════════════════════════

def load_data() -> dict:
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"channels": {}, "link_hours": LINK_HOURS}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список каналов",    callback_data="admin_list")],
        [InlineKeyboardButton("➕ Добавить канал",     callback_data="admin_add")],
        [InlineKeyboardButton("🗑 Удалить канал",      callback_data="admin_delete_menu")],
        [InlineKeyboardButton("⏱ Время ссылки",       callback_data="admin_hours")],
        [InlineKeyboardButton("🔗 Получить ссылку",   callback_data="admin_get_link")],
    ])


async def send_admin_menu(update: Update, text: str = "👑 <b>Панель администратора</b>") -> None:
    kb = admin_main_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def create_link(bot, channel_id: str, user_id: int, hours: int) -> str:
    expire_date = datetime.now(timezone.utc) + timedelta(hours=hours)
    invite = await bot.create_chat_invite_link(
        chat_id=channel_id,
        expire_date=expire_date,
        member_limit=1,
        name=f"tmp_{user_id}",
    )
    return invite.invite_link


# ══════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if is_admin(user_id):
        await send_admin_menu(update)
        return

    # Обычный пользователь
    data = load_data()
    channels = data.get("channels", {})

    if not channels:
        await update.message.reply_text(
            "😔 Каналы ещё не добавлены. Попробуйте позже."
        )
        return

    if len(channels) == 1:
        # Один канал — сразу ссылку
        ch_id, ch_name = next(iter(channels.items()))
        hours = data.get("link_hours", LINK_HOURS)
        try:
            link = await create_link(context.bot, ch_id, user_id, hours)
            await update.message.reply_text(
                f"🔗 <b>Ваша временная ссылка на канал «{ch_name}»:</b>\n\n"
                f"{link}\n\n"
                f"⏳ Действует <b>{hours} ч.</b> | 🔂 Одноразовая",
                parse_mode="HTML",
            )
        except TelegramError as e:
            logger.error("Ошибка ссылки: %s", e)
            await update.message.reply_text("❌ Не удалось создать ссылку. Попробуйте позже.")
        return

    # Несколько каналов — показать выбор
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"user_link:{ch_id}")]
        for ch_id, name in channels.items()
    ]
    await update.message.reply_text(
        "📢 Выберите канал, для которого нужна ссылка:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ══════════════════════════════════════════════
#  CALLBACK — обычный пользователь
# ══════════════════════════════════════════════

async def user_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    ch_id = query.data.split(":", 1)[1]
    data = load_data()
    ch_name = data["channels"].get(ch_id, ch_id)
    hours = data.get("link_hours", LINK_HOURS)

    try:
        link = await create_link(context.bot, ch_id, query.from_user.id, hours)
        await query.edit_message_text(
            f"🔗 <b>Ваша временная ссылка на канал «{ch_name}»:</b>\n\n"
            f"{link}\n\n"
            f"⏳ Действует <b>{hours} ч.</b> | 🔂 Одноразовая",
            parse_mode="HTML",
        )
    except TelegramError as e:
        logger.error("Ошибка ссылки: %s", e)
        await query.edit_message_text("❌ Не удалось создать ссылку. Попробуйте позже.")


# ══════════════════════════════════════════════
#  ADMIN CALLBACKS
# ══════════════════════════════════════════════

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    action = query.data
    data = load_data()
    channels = data.get("channels", {})

    # ── Список каналов ──────────────────────────
    if action == "admin_list":
        if not channels:
            text = "📋 <b>Каналы не добавлены</b>"
        else:
            lines = "\n".join(
                f"  • <b>{name}</b>  <code>{ch_id}</code>"
                for ch_id, name in channels.items()
            )
            text = f"📋 <b>Добавленные каналы ({len(channels)}):</b>\n\n{lines}"
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
            ]),
            parse_mode="HTML",
        )

    # ── Добавить канал ──────────────────────────
    elif action == "admin_add":
        await query.edit_message_text(
            "➕ <b>Добавление канала</b>\n\n"
            "Отправьте <b>ID канала</b> или <b>@username</b>.\n\n"
            "Например: <code>-1001234567890</code> или <code>@mychannel</code>\n\n"
            "❗ Убедитесь, что бот уже добавлен в канал как администратор.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_back")]
            ]),
            parse_mode="HTML",
        )
        return WAIT_CHANNEL_ID

    # ── Меню удаления ───────────────────────────
    elif action == "admin_delete_menu":
        if not channels:
            await query.edit_message_text(
                "🗑 Нет каналов для удаления.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
                ]),
            )
            return
        buttons = [
            [InlineKeyboardButton(f"🗑 {name}", callback_data=f"admin_del:{ch_id}")]
            for ch_id, name in channels.items()
        ]
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
        await query.edit_message_text(
            "🗑 <b>Выберите канал для удаления:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    # ── Удалить конкретный канал ─────────────────
    elif action.startswith("admin_del:"):
        ch_id = action.split(":", 1)[1]
        name = channels.pop(ch_id, ch_id)
        data["channels"] = channels
        save_data(data)
        await send_admin_menu(
            update,
            f"✅ Канал <b>«{name}»</b> удалён.\n\n👑 <b>Панель администратора</b>",
        )

    # ── Время ссылки ─────────────────────────────
    elif action == "admin_hours":
        current = data.get("link_hours", LINK_HOURS)
        buttons = [
            [
                InlineKeyboardButton("30 мин",  callback_data="set_hours:0.5"),
                InlineKeyboardButton("1 ч",     callback_data="set_hours:1"),
                InlineKeyboardButton("3 ч",     callback_data="set_hours:3"),
            ],
            [
                InlineKeyboardButton("6 ч",     callback_data="set_hours:6"),
                InlineKeyboardButton("12 ч",    callback_data="set_hours:12"),
                InlineKeyboardButton("24 ч",    callback_data="set_hours:24"),
            ],
            [InlineKeyboardButton("◀️ Назад",   callback_data="admin_back")],
        ]
        await query.edit_message_text(
            f"⏱ <b>Срок действия ссылки</b>\n\nСейчас: <b>{current} ч.</b>\n\nВыберите новое время:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    # ── Установить время ─────────────────────────
    elif action.startswith("set_hours:"):
        hours = float(action.split(":")[1])
        data["link_hours"] = hours
        save_data(data)
        label = "30 мин" if hours == 0.5 else f"{int(hours)} ч."
        await send_admin_menu(
            update,
            f"✅ Время ссылки установлено: <b>{label}</b>\n\n👑 <b>Панель администратора</b>",
        )

    # ── Получить ссылку (для себя) ───────────────
    elif action == "admin_get_link":
        if not channels:
            await query.edit_message_text(
                "📢 Каналы не добавлены.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
                ]),
            )
            return
        if len(channels) == 1:
            ch_id, ch_name = next(iter(channels.items()))
            hours = data.get("link_hours", LINK_HOURS)
            try:
                link = await create_link(context.bot, ch_id, query.from_user.id, hours)
                await query.edit_message_text(
                    f"🔗 <b>Временная ссылка на «{ch_name}»:</b>\n\n{link}\n\n⏳ {hours} ч.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
                    ]),
                    parse_mode="HTML",
                )
            except TelegramError as e:
                await query.edit_message_text(f"❌ Ошибка: {e}")
        else:
            buttons = [
                [InlineKeyboardButton(name, callback_data=f"admin_link:{ch_id}")]
                for ch_id, name in channels.items()
            ]
            buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
            await query.edit_message_text(
                "📢 Выберите канал:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )

    elif action.startswith("admin_link:"):
        ch_id = action.split(":", 1)[1]
        ch_name = channels.get(ch_id, ch_id)
        hours = data.get("link_hours", LINK_HOURS)
        try:
            link = await create_link(context.bot, ch_id, query.from_user.id, hours)
            await query.edit_message_text(
                f"🔗 <b>Временная ссылка на «{ch_name}»:</b>\n\n{link}\n\n⏳ {hours} ч.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
                ]),
                parse_mode="HTML",
            )
        except TelegramError as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")

    # ── Назад ────────────────────────────────────
    elif action == "admin_back":
        await send_admin_menu(update)


# ══════════════════════════════════════════════
#  CONVERSATION — добавление канала
# ══════════════════════════════════════════════

async def conv_get_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Шаг 1: получить ID канала."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    ch_id = update.message.text.strip()
    context.user_data["new_ch_id"] = ch_id

    await update.message.reply_text(
        f"✅ ID получен: <code>{ch_id}</code>\n\n"
        "Теперь отправьте <b>название канала</b> (любое удобное вам):",
        parse_mode="HTML",
    )
    return WAIT_CHANNEL_NAME


async def conv_get_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Шаг 2: получить название и сохранить."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    ch_id   = context.user_data.pop("new_ch_id", None)
    ch_name = update.message.text.strip()

    if not ch_id:
        await update.message.reply_text("❌ Что-то пошло не так. Начни заново.")
        return ConversationHandler.END

    data = load_data()
    data["channels"][ch_id] = ch_name
    save_data(data)

    await update.message.reply_text(
        f"✅ Канал <b>«{ch_name}»</b> добавлен!\n\n"
        "👑 <b>Панель администратора</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await send_admin_menu(update, "❌ Отменено.\n\n👑 <b>Панель администратора</b>")
    return ConversationHandler.END


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для добавления канала
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_callback, pattern="^admin_add$"),
        ],
        states={
            WAIT_CHANNEL_ID:   [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_get_channel_id)],
            WAIT_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, conv_get_channel_name)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(conv_cancel, pattern="^admin_back$"),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(user_link_callback, pattern=r"^user_link:"))
    app.add_handler(CallbackQueryHandler(admin_callback))

    logger.info("Бот запущен ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()