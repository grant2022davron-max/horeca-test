import asyncio
import html
import json
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

BOT_TOKEN = os.environ["BOT_TOKEN"]
STAFF_CHAT_ID = int(os.environ["STAFF_CHAT_ID"])   # id группы персонала, например -1001234567890
WEBAPP_URL = os.environ["WEBAPP_URL"]              # https-адрес, где лежит index.html

with open(os.path.join(os.path.dirname(__file__), "menu.json"), encoding="utf-8") as f:
    MENU = json.load(f)
ITEMS = {item["id"]: item for cat in MENU["categories"] for item in cat["items"]}

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " сум"


def menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🍽 Открыть меню", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def validate(data: dict) -> dict:
    """Проверяет заказ и пересчитывает цены по menu.json. Клиентским суммам не доверяем."""
    if data.get("v") != 1:
        raise ValueError("bad version")

    mode = data.get("mode")
    if mode not in ("delivery", "pickup"):
        raise ValueError("bad mode")

    lines, total = [], 0
    for entry in data.get("items", []):
        item = ITEMS.get(entry.get("id"))
        qty = int(entry.get("qty", 0))
        if item is None or not 1 <= qty <= 50:
            raise ValueError("bad item")
        lines.append((item, qty))
        total += item["price"] * qty
    if not lines:
        raise ValueError("empty order")

    address = str(data.get("address", "")).strip()[:300]
    if mode == "delivery" and len(address) < 5:
        raise ValueError("no address")

    phone = str(data.get("phone", "")).strip()[:30]
    comment = str(data.get("comment", "")).strip()[:300]
    time = str(data.get("time", "asap"))[:5]

    return {
        "mode": mode,
        "address": address,
        "phone": phone,
        "comment": comment,
        "time": time,
        "lines": lines,
        "total": total,
    }


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать в <b>Шале</b>!\n"
        "Работаем с 07:00 до 23:00, ул. Шота Руставели, 89.\n\n"
        "Нажмите «Открыть меню», выберите блюда, способ получения и время.",
        reply_markup=menu_keyboard(),
    )


@dp.message(F.web_app_data)
async def on_order(message: types.Message):
    try:
        order = validate(json.loads(message.web_app_data.data))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        logging.warning("Invalid order: %s", e)
        await message.answer("Не удалось принять заказ. Попробуйте оформить его ещё раз.")
        return

    user = message.from_user
    who = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
    if user.username:
        who += f" (@{user.username})"

    is_delivery = order["mode"] == "delivery"
    time_text = "как можно скорее" if order["time"] == "asap" else order["time"]

    items_text = "\n".join(
        f"• {html.escape(item['name'])}"
        + (f" ({item['note']})" if item.get("note") else "")
        + f" × {qty} — {fmt(item['price'] * qty)}"
        for item, qty in order["lines"]
    )

    staff_text = (
        "🆕 <b>Новый заказ — Шале</b>\n\n"
        f"Клиент: {who}\n"
        f"Получение: {'🚗 Доставка' if is_delivery else '🏠 Самовывоз'}\n"
    )
    if is_delivery:
        staff_text += (
            f"Адрес: {html.escape(order['address'])}\n"
            "⚠️ Курьера вызвать вручную (Яндекс Про)\n"
        )
    staff_text += (
        f"Время: {time_text}\n"
        f"Телефон: {html.escape(order['phone']) or '—'}\n"
        f"Комментарий: {html.escape(order['comment']) or '—'}\n"
        "Оплата: перевод на карту (реквизиты выдаёт хостес)\n\n"
        f"<b>Состав:</b>\n{items_text}\n\n"
        f"<b>Итого: {fmt(order['total'])}</b>"
    )

    try:
        await bot.send_message(STAFF_CHAT_ID, staff_text, disable_web_page_preview=True)
    except Exception:
        logging.exception("Could not send order to staff chat")
        await message.answer("Не удалось отправить заказ. Пожалуйста, позвоните в ресторан.")
        return

    await message.answer(
        "✅ <b>Заказ принят!</b>\n"
        f"Итого: {fmt(order['total'])}\n\n"
        "Администратор свяжется с вами по телефону и сообщит реквизиты для перевода. "
        "После оплаты отправьте чек администратору."
    )


async def main():
    logging.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
