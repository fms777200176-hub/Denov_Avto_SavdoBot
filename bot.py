import os
import logging
import uuid

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL = os.getenv("CHANNEL", "@denov_avto_savdo")

# Tasdiqlanishini kutayotgan e'lonlar
PENDING_ADS = {}

FIELDS = [
    ("model", "🚘 Mashina markasi va modeli"),
    ("year", "📅 Ishlab chiqarilgan yili"),
    ("gearbox", "⚙️ Korobkasi (avtomat yoki mexanika)"),
    ("fuel", "⛽ Yoqilg‘i turi"),
    ("mileage", "🛣 Yurgan masofasi (km)"),
    ("color", "🎨 Rangi va holati"),
    ("phone", "📞 Bog‘lanish uchun telefon raqami"),
]


def make_ad(ad):
    extra = ad.get("extra", "").strip()

    text = (
        f"🚘 #{ad['model'].replace(' ', '_')}\n"
        f"📅 Yili: {ad['year']}\n"
        f"⚙️ Korobkasi: {ad['gearbox']}\n"
        f"⛽ Yoqilg‘i: {ad['fuel']}\n"
        f"🛣 Yurgan masofasi: {ad['mileage']} km\n"
        f"🎨 Rangi va holati: {ad['color']}\n"
        f"💰 Narxi: {ad['price']} {ad['currency']}\n"
        f"📞 Telefon: {ad['phone']}\n"
    )

    if extra:
        text += f"\n📝 Qo‘shimcha ma’lumot: {extra}\n"

    text += "\n📢 E’lon bepul joylashtirildi!"
    return text


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    keyboard = [[
        InlineKeyboardButton(
            "🚗 E'lon berish",
            callback_data="new_ad",
        )
    ]]

    await update.message.reply_text(
        "🚘 DENOV AVTO SAVDO BOT\n\n"
        "Assalomu alaykum!\n"
        "Avtomobilingizni sotmoqchimisiz?\n"
        "E'lon joylashtirish mutlaqo bepul!\n\n"
        "Boshlash uchun tugmani bosing.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def ask_next(message, context):
    step = context.user_data.get("step", 0)

    if step < len(FIELDS):
        _, question = FIELDS[step]
        await message.reply_text(
            f"{step + 1}/{len(FIELDS)}. {question}"
        )
        return

    if step == len(FIELDS):
        keyboard = [[
            InlineKeyboardButton(
                "🇺🇿 So‘m",
                callback_data="currency_som",
            ),
            InlineKeyboardButton(
                "🇺🇸 Dollar",
                callback_data="currency_usd",
            ),
        ]]

        await message.reply_text(
            "💰 Narxni qaysi valyutada kiritasiz?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if step == len(FIELDS) + 1:
        await message.reply_text(
            "💵 Mashina narxini raqam bilan yozing.\n"
            "Masalan: 85000000 yoki 12500."
        )
        return

    if step == len(FIELDS) + 2:
        keyboard = [[
            InlineKeyboardButton(
                "⏭ O‘tkazib yuborish",
                callback_data="skip_extra",
            )
        ]]

        await message.reply_text(
            "📝 Qo‘shimcha ma’lumot bo‘lsa yozing.\n"
            "Masalan: kraskasi, motor holati, "
            "savdolashish yoki boshqa ma’lumotlar.\n\n"
            "Bu maydon ixtiyoriy.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if step == len(FIELDS) + 3:
        context.user_data["photos"] = []

        await message.reply_text(
            "📸 Endi avtomobil rasmlarini yuboring.\n"
            "Bir nechta rasm yuborishingiz mumkin.\n\n"
            "Barcha rasmlarni yuborgach, /done buyrug‘ini yozing.\n\n"
            "⚠️ Davlat raqami ko‘rinib turgan rasmlarni "
            "kanalga joylashdan oldin tekshiring."
        )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "new_ad":
        context.user_data.clear()
        context.user_data["ad"] = {}
        context.user_data["step"] = 0

        await ask_next(query.message, context)
        return

    if data in ("currency_som", "currency_usd"):
        ad = context.user_data.get("ad")

        if not ad:
            await query.message.reply_text(
                "Avval /start buyrug‘ini yuboring."
            )
            return

        ad["currency"] = (
            "so‘m" if data == "currency_som"
            else "AQSH dollari"
        )
        context.user_data["step"] = len(FIELDS) + 1

        await ask_next(query.message, context)
        return

    if data == "skip_extra":
        context.user_data.setdefault("ad", {})["extra"] = ""
        context.user_data["step"] = len(FIELDS) + 3

        await ask_next(query.message, context)
        return

    # Quyidagi tugmalar faqat admin uchun
    if data.startswith(("approve_", "reject_")):
        if query.from_user.id != ADMIN_ID:
            await query.message.reply_text(
                "Bu amal faqat admin uchun."
            )
            return

        action, ad_id = data.split("_", 1)
        ad = PENDING_ADS.get(ad_id)

        if not ad:
            await query.message.reply_text(
                "Bu e'lon topilmadi yoki allaqachon ko‘rib chiqilgan."
            )
            return

        if action == "reject":
            PENDING_ADS.pop(ad_id, None)

            await query.edit_message_reply_markup(
                reply_markup=None
            )

            await query.message.reply_text(
                "❌ E'lon rad etildi."
            )

            try:
                await context.bot.send_message(
                    chat_id=ad["user_id"],
                    text="❌ E'loningiz admin tomonidan rad etildi.",
                )
            except Exception:
                logging.exception("Foydalanuvchiga xabar yuborilmadi")

            return

        text = make_ad(ad)
        photos = ad["photos"]

        try:
            if len(photos) == 1:
                await context.bot.send_photo(
                    chat_id=CHANNEL,
                    photo=photos[0],
                    caption=text,
                )
            else:
                media = [
                    InputMediaPhoto(
                        media=photo,
                        caption=text if i == 0 else None,
                    )
                    for i, photo in enumerate(photos)
                ]

                await context.bot.send_media_group(
                    chat_id=CHANNEL,
                    media=media,
                )

            PENDING_ADS.pop(ad_id, None)

            await query.edit_message_reply_markup(
                reply_markup=None
            )

            await query.message.reply_text(
                "✅ E'lon kanalga joylandi!"
            )

            await context.bot.send_message(
                chat_id=ad["user_id"],
                text=(
                    "✅ E'loningiz tasdiqlandi va "
                    "kanalga joylandi!\n\n"
                    "Rahmat!"
                ),
            )

        except Exception:
            logging.exception("E'lon kanalga joylanmadi")

            await query.message.reply_text(
                "❌ E'lon joylanmadi. "
                "Botning kanalga admin qilib qo‘shilganini "
                "va ruxsatlarini tekshiring."
            )


async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    step = context.user_data.get("step")

    if step is None:
        await update.message.reply_text(
            "Boshlash uchun /start buyrug‘ini yuboring."
        )
        return

    ad = context.user_data.setdefault("ad", {})

    if step < len(FIELDS):
        key, _ = FIELDS[step]

        if not text:
            await update.message.reply_text(
                "Iltimos, ma'lumot kiriting."
            )
            return

        ad[key] = text
        context.user_data["step"] = step + 1

        await ask_next(update.message, context)
        return

    if step == len(FIELDS):
        await update.message.reply_text(
            "Iltimos, valyutani tugma orqali tanlang."
        )
        return

    if step == len(FIELDS) + 1:
        digits = "".join(c for c in text if c.isdigit())

        if not digits:
            await update.message.reply_text(
                "Narxni raqam bilan kiriting. Masalan: 85000000"
            )
            return

        ad["price"] = f"{int(digits):,}".replace(",", " ")
        context.user_data["step"] = len(FIELDS) + 2

        await ask_next(update.message, context)
        return

    if step == len(FIELDS) + 2:
        ad["extra"] = text
        context.user_data["step"] = len(FIELDS) + 3

        await ask_next(update.message, context)
        return

    if step == len(FIELDS) + 3:
        await update.message.reply_text(
            "Rasm yuboring yoki barcha rasmlarni yuborgan "
            "bo‘lsangiz /done buyrug‘ini yozing."
        )


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if context.user_data.get("step") != len(FIELDS) + 3:
        await update.message.reply_text(
            "Avval /start orqali e'lon berishni boshlang."
        )
        return

    photos = context.user_data.setdefault("photos", [])

    if len(photos) >= 10:
        await update.message.reply_text(
            "Ko‘pi bilan 10 ta rasm yuborishingiz mumkin. "
            "/done buyrug‘ini yozing."
        )
        return

    photos.append(update.message.photo[-1].file_id)

    await update.message.reply_text(
        f"✅ Rasm qabul qilindi ({len(photos)}/10).\n"
        "Yana rasm yuboring yoki /done yozing."
    )


async def done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if context.user_data.get("step") != len(FIELDS) + 3:
        await update.message.reply_text(
            "Avval e'lon ma'lumotlarini to‘ldiring."
        )
        return

    photos = context.user_data.get("photos", [])

    if not photos:
        await update.message.reply_text(
            "❗ Kamida bitta avtomobil rasmi yuboring."
        )
        return

    ad = context.user_data["ad"]
    ad["photos"] = photos
    ad["user_id"] = update.effective_user.id

    ad_id = uuid.uuid4().hex[:10]
    PENDING_ADS[ad_id] = ad.copy()

    text = make_ad(ad)

    keyboard = [[
        InlineKeyboardButton(
            "✅ Tasdiqlash",
            callback_data=f"approve_{ad_id}",
        ),
        InlineKeyboardButton(
            "❌ Rad etish",
            callback_data=f"reject_{ad_id}",
        ),
    ]]

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 YANGI E'LON\n\n{text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        await context.bot.send_media_group(
            chat_id=ADMIN_ID,
            media=[
                InputMediaPhoto(media=p)
                for p in photos
            ],
        )

        await update.message.reply_text(
            "✅ E'loningiz adminga tekshirish uchun yuborildi.\n"
            "Tasdiqlangach, kanalga joylanadi."
        )

        context.user_data.clear()

    except Exception:
        PENDING_ADS.pop(ad_id, None)
        logging.exception("Adminga e'lon yuborilmadi")

        await update.message.reply_text(
            "❌ E'lonni adminga yuborishda xatolik yuz berdi. "
            "Birozdan so‘ng qayta urinib ko‘ring."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN server sozlamalarida kiritilmagan."
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID server sozlamalarida kiritilmagan."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
