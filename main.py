import telebot
from telebot import types
import threading
import time
from datetime import datetime, timedelta
from config import *
from database import Database

bot = telebot.TeleBot(BOT_TOKEN)
db = Database()

# Кэш для оптимизации (хранит последние проверки подписки)
subscription_cache = {}
cache_lock = threading.Lock()

# Кэш для username бота (чтобы не запрашивать каждый раз)
_bot_username_cache = None
_bot_username_lock = threading.Lock()

def get_bot_username():
    """Получить username бота (с кэшированием)"""
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    try:
        with _bot_username_lock:
            if not _bot_username_cache:
                _bot_username_cache = bot.get_me().username
        return _bot_username_cache
    except:
        return "your_bot_username"

def generate_referral_code(user_id):
    """Генерация уникального реферального кода"""
    import hashlib
    code = hashlib.md5(f"{user_id}{BOT_TOKEN}".encode()).hexdigest()[:8].upper()
    return code

def check_subscription(user_id, force_check=False):
    """Проверка подписки пользователя на канал (МАКСИМАЛЬНО ОПТИМИЗИРОВАННАЯ)"""
    try:
        # Если force_check=True, игнорируем кэш (для проверки после подписки)
        if not force_check:
            # Быстрая проверка кэша (без блокировки для чтения)
            cache_entry = subscription_cache.get(user_id)
            if cache_entry:
                cached_time, cached_result = cache_entry
                time_diff = (datetime.now() - cached_time).total_seconds()
                if time_diff < CHECK_SUBSCRIPTION_INTERVAL:
                    return cached_result
        
        # Проверка через API (только если кэш устарел или force_check=True)
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        is_subscribed = member.status in ['member', 'administrator', 'creator']
        
        # Обновление кэша (оптимизированное)
        with cache_lock:
            # LRU-подобная очистка: удаляем 20% самых старых записей
            if len(subscription_cache) > MAX_CACHE_SIZE:
                # Сортируем по времени и удаляем старые
                sorted_items = sorted(subscription_cache.items(), 
                                    key=lambda x: x[1][0])
                to_remove = len(sorted_items) // 5  # Удаляем 20%
                for key, _ in sorted_items[:to_remove]:
                    del subscription_cache[key]
            
            subscription_cache[user_id] = (datetime.now(), is_subscribed)
        
        return is_subscribed
    except Exception:
        # Возвращаем False при ошибке (не логируем для скорости)
        return False

def clear_subscription_cache(user_id):
    """Очистить кэш подписки для пользователя (для принудительной проверки)"""
    with cache_lock:
        if user_id in subscription_cache:
            del subscription_cache[user_id]

def validate_referral(referrer_id, referred_id):
    """Валидация реферала с анти-читом"""
    # Проверка 1: Пользователь не может пригласить сам себя
    if referrer_id == referred_id:
        return False, "Нельзя использовать свою собственную ссылку!"
    
    # Проверка 2: Реферал уже существует
    if db.check_referral_exists(referrer_id, referred_id):
        return False, "Вы уже были засчитаны как реферал этого пользователя!"
    
    # Проверка 3: Проверка подозрительной активности
    if db.check_suspicious_activity(referred_id):
        return False, "Обнаружена подозрительная активность. Реферал не засчитан."
    
    # Проверка 4: Пользователь должен быть подписан
    if not check_subscription(referred_id):
        return False, "Вы должны быть подписаны на канал!"
    
    return True, "Реферал успешно засчитан!"

def get_start_menu():
    """Создать меню /start"""
    keyboard = types.InlineKeyboardMarkup()
    
    # Кнопка с реферальной ссылкой
    keyboard.add(types.InlineKeyboardButton("🔗 Моя реферальная ссылка", callback_data="my_referral"))
    
    # ТОП пользователей
    keyboard.add(types.InlineKeyboardButton("🏆 ТОП участников", callback_data="top_users"))
    
    # Правила
    keyboard.add(types.InlineKeyboardButton("📋 Правила конкурса", callback_data="rules"))
    
    return keyboard

def get_admin_menu():
    """Меню админа"""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"))
    keyboard.add(types.InlineKeyboardButton("🚫 Забанить пользователя", callback_data="admin_ban"))
    keyboard.add(types.InlineKeyboardButton("✅ Разбанить пользователя", callback_data="admin_unban"))
    keyboard.add(types.InlineKeyboardButton("🔄 Сбросить конкурс", callback_data="admin_reset"))
    return keyboard

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Проверка бана
    if db.is_banned(user_id):
        bot.reply_to(message, "❌ Вы заблокированы в этом боте.")
        return
    
    # Проверка окончания конкурса
    if db.is_contest_ended():
        winners = db.get_top_users_for_prize(1)  # Используем функцию для призов
        first_100_winner = db.get_first_100_winner()
        
        text = "🎉 <b>КОНКУРС ЗАВЕРШЕН!</b>\n\n"
        
        if len(winners) >= 1:
            text += f"🥇 <b>1 МЕСТО:</b>\n"
            text += f"@{winners[0].get('username', 'N/A')} - {winners[0]['referrals_count']} рефералов\n"
            text += f"Приз: {PRIZE_1ST}\n\n"
        
        if first_100_winner:
            text += f"⚡ <b>ПЕРВЫЙ, КТО НАБРАЛ 100 РЕФЕРАЛОВ:</b>\n"
            text += f"@{first_100_winner.get('username', 'N/A')} - {first_100_winner['referrals_count']} рефералов\n"
            text += f"Приз: {PRIZE_FIRST_100}\n\n"
        
        text += "Спасибо всем за участие! 🎊"
        bot.reply_to(message, text, parse_mode='HTML')
        return
    
    # Получение или создание пользователя
    user = db.get_user(user_id)
    referral_code = None
    
    if not user:
        # Создание нового пользователя
        referral_code = generate_referral_code(user_id)
        db.create_user(user_id, username, first_name, referral_code)
        
        # Уведомление админа
        try:
            admin_text = f"🆕 Новый пользователь зарегистрирован!\n\n"
            admin_text += f"ID: {user_id}\n"
            admin_text += f"Имя: {first_name}\n"
            admin_text += f"Username: @{username if username else 'N/A'}\n"
            admin_text += f"Реферальный код: {referral_code}"
            bot.send_message(ADMIN_ID, admin_text)
        except:
            pass
    else:
        referral_code = user['referral_code']
    
    # Обработка реферального кода из параметра
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
        referrer_id = db.get_referrer_id(ref_code)
        
        if referrer_id and referrer_id != user_id:
            # Очищаем кэш для принудительной проверки (пользователь мог только что подписаться)
            clear_subscription_cache(user_id)
            
            # Принудительная проверка подписки перед засчитыванием реферала (игнорируем кэш)
            if check_subscription(user_id, force_check=True):
                # Валидация реферала
                is_valid, msg = validate_referral(referrer_id, user_id)
                
                if is_valid:
                    # Добавление реферала
                    if db.add_referral(referrer_id, user_id):
                        # Получаем обновленное количество рефералов
                        referrer_user = db.get_user(referrer_id)
                        referrals_count = referrer_user['referrals_count'] if referrer_user else 0
                        
                        # Проверка на достижение 100 рефералов (проверяем, стал ли этот пользователь победителем)
                        if referrals_count >= 100:
                            first_100_winner = db.get_first_100_winner()
                            if first_100_winner and first_100_winner['user_id'] == referrer_id:
                                # Уведомление о победе за 100 рефералов (только если он первый)
                                try:
                                    winner_text = f"🎉 ПОЗДРАВЛЯЕМ!\n\n"
                                    winner_text += f"Вы первым достигли 100 рефералов!\n\n"
                                    winner_text += f"🏆 Ваш приз: {PRIZE_FIRST_100}"
                                    bot.send_message(referrer_id, winner_text)
                                except:
                                    pass
                        
                        bot.reply_to(message, f"✅ {msg}")
                        # Удаляем ожидающий реферал, если был
                        db.remove_pending_referral(user_id)
                    else:
                        bot.reply_to(message, "❌ Ошибка при добавлении реферала.")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            else:
                # Сохраняем реферальный код для последующей обработки после подписки
                db.add_pending_referral(user_id, referrer_id)
    
    # Проверка подписки
    if not check_subscription(user_id):
        text = f"👋 Добро пожаловать, {first_name}!\n\n"
        text += "⚠️ Для использования бота необходимо подписаться на канал:\n"
        text += f"{CHANNEL_INVITE_LINK}\n\n"
        text += "После подписки нажмите /start снова."
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription"))
        keyboard.add(types.InlineKeyboardButton("📢 Перейти в канал", url=CHANNEL_INVITE_LINK))
        
        bot.reply_to(message, text, reply_markup=keyboard)
        return
    
    # Проверяем ожидающие рефералы (если пользователь только что подписался)
    pending_referrer_id = db.get_pending_referral(user_id)
    if pending_referrer_id:
        # Очищаем кэш для принудительной проверки
        clear_subscription_cache(user_id)
        
        # Принудительная проверка подписки (игнорируем кэш)
        if check_subscription(user_id, force_check=True):
            # Валидация и добавление реферала
            is_valid, msg = validate_referral(pending_referrer_id, user_id)
            if is_valid:
                if db.add_referral(pending_referrer_id, user_id):
                    bot.send_message(user_id, f"✅ {msg}")
        db.remove_pending_referral(user_id)
    
    # Главное меню (используем HTML вместо Markdown для избежания ошибок парсинга)
    text = f"🎉 Добро пожаловать, {first_name}!\n\n"
    text += "🏆 <b>КОНКУРС РЕФЕРАЛОВ</b>\n\n"
    text += "🎁 <b>ПРИЗЫ:</b>\n"
    text += f"🥇 <b>1 место</b> (больше всех рефералов): NFT Snoop Dogg\n{PRIZE_1ST}\n\n"
    text += f"⚡ <b>Первый, кто наберет 100 рефералов</b>: NFT Instant Ramen\n{PRIZE_FIRST_100}\n\n"
    text += "📋 <b>ПРАВИЛА:</b>\n"
    text += f"• Минимальный порог для 1 места: {MIN_REFERRALS_FOR_PRIZE} приглашений\n"
    text += f"• Конкурс длится {CONTEST_DURATION_DAYS} дней\n"
    text += "• 1 место получает тот, кто пригласит больше всего друзей\n"
    text += "• Приз за 100 рефералов получает тот, кто первым достигнет этой отметки\n"
    text += "• Обязательна подписка на канал для засчитывания рефералов\n\n"
    text += "🔗 Получите свою реферальную ссылку и приглашайте друзей!"
    
    bot.reply_to(message, text, reply_markup=get_start_menu(), parse_mode='HTML')
    
    # Админ меню
    if user_id == ADMIN_ID:
        bot.send_message(user_id, "🔧 Админ панель:", reply_markup=get_admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Проверка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    user_id = call.from_user.id
    
    # Очищаем кэш для принудительной проверки (пользователь мог только что подписаться)
    clear_subscription_cache(user_id)
    
    # Принудительная проверка подписки (игнорируем кэш)
    if check_subscription(user_id, force_check=True):
        try:
            bot.answer_callback_query(call.id, "✅ Вы подписаны!")
        except:
            pass  # Игнорируем ошибку, если callback устарел
        
        # Проверяем, есть ли ожидающий реферал (в фоне)
        pending_referrer_id = db.get_pending_referral(user_id)
        if pending_referrer_id:
            # Валидация и добавление реферала
            is_valid, msg = validate_referral(pending_referrer_id, user_id)
            if is_valid:
                if db.add_referral(pending_referrer_id, user_id):
                    bot.send_message(user_id, f"✅ {msg}")
            db.remove_pending_referral(user_id)
        
        # Обновляем меню
        start_command(call.message)
    else:
        try:
            bot.answer_callback_query(call.id, "❌ Вы не подписаны на канал!")
        except:
            pass  # Игнорируем ошибку, если callback устарел

@bot.callback_query_handler(func=lambda call: call.data == "my_referral")
def my_referral_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    user_id = call.from_user.id
    
    # Быстрая проверка бана (использует кэш)
    if db.is_banned(user_id):
        try:
            bot.answer_callback_query(call.id, "❌ Вы заблокированы!")
        except:
            pass
        return
    
    # Быстрая проверка подписки (использует кэш)
    if not check_subscription(user_id):
        try:
            bot.answer_callback_query(call.id, "❌ Подпишитесь на канал!")
        except:
            pass
        return
    
    # Получаем данные (использует кэш)
    user = db.get_user(user_id)
    referral_code = user['referral_code'] if user else None
    referrals_count = user['referrals_count'] if user else 0
    
    if not referral_code:
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка!")
        except:
            pass
        return
    
    # Используем кэшированный username
    bot_username = get_bot_username()
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    text = "🔗 <b>Ваша реферальная ссылка:</b>\n\n"
    text += f"<code>{referral_link}</code>\n\n"
    text += f"📊 Ваших рефералов: <b>{referrals_count}</b>\n\n"
    text += "📋 Скопируйте ссылку и отправьте друзьям!"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📋 Скопировать ссылку", url=referral_link))
    keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                             reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        pass  # Уже ответили на callback

@bot.callback_query_handler(func=lambda call: call.data == "top_users")
def top_users_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    user_id = call.from_user.id
    
    # Быстрая проверка бана (использует кэш)
    if db.is_banned(user_id):
        return
    
    # Быстрый запрос к БД (оптимизированный)
    top_users = db.get_top_users(10)
    
    if not top_users:
        text = "📊 Пока нет участников в ТОПе.\n\n"
        text += "Пригласите друзей, чтобы попасть в ТОП!"
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return
    
    # Быстрое формирование текста
    text = "🏆 <b>ТОП участников:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        username = user.get('username', 'N/A')
        count = user['referrals_count']
        text += f"{medal} @{username} - <b>{count}</b> рефералов\n"
    
    text += f"\n📋 Минимальный порог для 1 места: {MIN_REFERRALS_FOR_PRIZE} приглашений"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="top_users"))
    keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        pass  # Уже ответили на callback

@bot.callback_query_handler(func=lambda call: call.data == "rules")
def rules_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    # Формируем текст (без запросов к БД)
    text = "📋 <b>ПРАВИЛА КОНКУРСА:</b>\n\n"
    text += f"🎯 <b>Минимальный порог для 1 места:</b> {MIN_REFERRALS_FOR_PRIZE} приглашений\n\n"
    text += f"⏰ <b>Длительность:</b> {CONTEST_DURATION_DAYS} дней\n\n"
    text += "🏆 <b>Призы:</b>\n"
    text += f"🥇 <b>1 место</b> (больше всех рефералов): NFT Snoop Dogg\n{PRIZE_1ST}\n\n"
    text += f"⚡ <b>Первый, кто наберет 100 рефералов</b>: NFT Instant Ramen\n{PRIZE_FIRST_100}\n\n"
    text += "📌 <b>Важно:</b>\n"
    text += "• Реферал должен быть подписан на канал\n"
    text += "• Запрещено использование ботов и накрутка\n"
    text += "• Система автоматически блокирует подозрительную активность\n"
    text += "• Один пользователь может быть рефералом только один раз\n"
    text += "• Победит участник с наибольшим количеством рефералов\n\n"
    
    # Быстрый запрос к БД (кэшируется)
    end_date = db.get_contest_end_date()
    text += f"⏳ Конкурс завершится: {end_date.strftime('%d.%m.%Y %H:%M')}"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        pass  # Уже ответили на callback

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
def back_to_menu_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    # Используем данные из callback (не запрашиваем БД)
    first_name = call.from_user.first_name
    
    text = f"🎉 Добро пожаловать, {first_name}!\n\n"
    text += "🏆 <b>КОНКУРС РЕФЕРАЛОВ</b>\n\n"
    text += "🎁 <b>ПРИЗЫ:</b>\n"
    text += f"🥇 <b>1 место</b> (больше всех рефералов): NFT Snoop Dogg\n{PRIZE_1ST}\n\n"
    text += f"⚡ <b>Первый, кто наберет 100 рефералов</b>: NFT Instant Ramen\n{PRIZE_FIRST_100}\n\n"
    text += "🔗 Получите свою реферальную ссылку и приглашайте друзей!"
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             reply_markup=get_start_menu(), parse_mode='HTML')
    except Exception:
        pass  # Уже ответили на callback

# Админ функции
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback (убирает загрузку кнопки)
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    user_id = call.from_user.id
    
    if user_id != ADMIN_ID:
        return
    
    if call.data == "admin_stats":
        all_users = db.get_all_users()
        total_users = len(all_users)
        total_referrals = sum(u['referrals_count'] for u in all_users)
        banned_users = sum(1 for u in all_users if u['is_banned'])
        
        top_users = db.get_top_users_for_prize(5)  # Для статистики админа используем функцию для призов
        
        text = "📊 <b>СТАТИСТИКА:</b>\n\n"
        text += f"👥 Всего пользователей: {total_users}\n"
        text += f"🔗 Всего рефералов: {total_referrals}\n"
        text += f"🚫 Забанено: {banned_users}\n\n"
        text += "🏆 <b>ТОП-5:</b>\n"
        
        for i, user in enumerate(top_users, 1):
            username = user.get('username', 'N/A')
            count = user['referrals_count']
            text += f"{i}. @{username} - {count}\n"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                 reply_markup=keyboard, parse_mode='HTML')
        except Exception:
            try:
                bot.answer_callback_query(call.id, "✅ Информация актуальна!")
            except:
                pass  # Игнорируем ошибку, если callback устарел
    
    elif call.data == "admin_ban":
        bot.send_message(user_id, "Введите ID пользователя для бана:")
        bot.register_next_step_handler(call.message, admin_ban_handler)
    
    elif call.data == "admin_unban":
        bot.send_message(user_id, "Введите ID пользователя для разбана:")
        bot.register_next_step_handler(call.message, admin_unban_handler)
    
    elif call.data == "admin_reset":
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data="admin_reset_confirm"))
        keyboard.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_back"))
        try:
            bot.edit_message_text("⚠️ Вы уверены, что хотите сбросить конкурс?", 
                                call.message.chat.id, call.message.message_id,
                                reply_markup=keyboard)
        except Exception:
            try:
                bot.answer_callback_query(call.id, "✅")
            except:
                pass  # Игнорируем ошибку, если callback устарел
    
    elif call.data == "admin_back":
        try:
            bot.edit_message_text("🔧 Админ панель:", call.message.chat.id, call.message.message_id,
                                 reply_markup=get_admin_menu())
        except Exception:
            try:
                bot.answer_callback_query(call.id, "✅")
            except:
                pass  # Игнорируем ошибку, если callback устарел

@bot.callback_query_handler(func=lambda call: call.data == "admin_reset_confirm")
def admin_reset_confirm(call):
    # МГНОВЕННЫЙ ОТВЕТ на callback
    try:
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
    except:
        pass  # Игнорируем ошибку, если callback устарел
    
    user_id = call.from_user.id
    if user_id != ADMIN_ID:
        return
    
    # Сброс даты начала конкурса
    start_date = datetime.now().isoformat()
    db.cursor.execute('UPDATE contest_settings SET value = ? WHERE key = ?', (start_date, 'start_date'))
    db.conn.commit()
    
    try:
        bot.edit_message_text("✅ Конкурс успешно сброшен!", call.message.chat.id, call.message.message_id)
    except Exception:
        pass

def admin_ban_handler(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(message.text)
        db.ban_user(user_id)
        bot.reply_to(message, f"✅ Пользователь {user_id} забанен!")
    except ValueError:
        bot.reply_to(message, "❌ Неверный ID!")

def admin_unban_handler(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(message.text)
        db.unban_user(user_id)
        bot.reply_to(message, f"✅ Пользователь {user_id} разбанен!")
    except ValueError:
        bot.reply_to(message, "❌ Неверный ID!")

# Фоновая задача для проверки подписок и анти-чита (МАКСИМАЛЬНО ОПТИМИЗИРОВАННАЯ)
def background_anti_cheat():
    """Фоновая задача для проверки подписок и анти-чита (УЛЬТРА ОПТИМИЗАЦИЯ)"""
    last_contest_check = datetime.now()
    last_cache_cleanup = datetime.now()
    processed_users = set()  # Кэш обработанных пользователей
    
    while True:
        try:
            time.sleep(BACKGROUND_CHECK_INTERVAL)  # Проверка каждые 30 минут
            
            current_time = datetime.now()
            
            # Очистка кэша (раз в 2 часа) - реже для скорости
            cache_time_diff = current_time - last_cache_cleanup
            if cache_time_diff.total_seconds() >= CACHE_CLEANUP_INTERVAL:
                last_cache_cleanup = current_time
                with cache_lock:
                    # Удаляем только очень старые записи (старше 2 часов)
                    keys_to_remove = [
                        k for k, (cached_time, _) in subscription_cache.items()
                        if (current_time - cached_time).total_seconds() > 7200
                    ]
                    for key in keys_to_remove[:100]:  # Удаляем максимум 100 за раз
                        del subscription_cache[key]
                
                # Очистка кэша обработанных пользователей
                processed_users.clear()
            
            # Проверка окончания конкурса (раз в 2 часа)
            time_diff = current_time - last_contest_check
            if time_diff.total_seconds() >= 7200:
                last_contest_check = current_time
                if db.is_contest_ended():
                    notify_contest_end()
                    continue
            
            # Получаем только активных пользователей с рефералами (оптимизированный запрос)
            db.cursor.execute('''
                SELECT user_id FROM users 
                WHERE is_banned = 0 AND referrals_count > 0
                ORDER BY referrals_count DESC
                LIMIT 30
            ''')
            active_users = db.cursor.fetchall()
            
            # Обрабатываем только новых пользователей (не обработанных ранее)
            new_users = [u for u in active_users if u['user_id'] not in processed_users]
            
            # Обрабатываем по частям (маленькие батчи для скорости)
            batch_size = 3  # Минимальный батч для максимальной скорости
            for i in range(0, len(new_users), batch_size):
                batch = new_users[i:i+batch_size]
                
                for user_row in batch:
                    user_id = user_row['user_id']
                    
                    try:
                        # Проверяем подписку (использует кэш - очень быстро)
                        is_subscribed = check_subscription(user_id)
                        
                        # Если пользователь отписался, проверяем только его активных рефералов
                        if not is_subscribed:
                            # Оптимизированный запрос - только валидные рефералы, ограничение
                            db.cursor.execute('''
                                SELECT referred_id FROM referrals
                                WHERE referrer_id = ? AND is_valid = 1
                                LIMIT 5
                            ''', (user_id,))
                            
                            referrals = db.cursor.fetchall()
                            
                            # Проверяем только первых 5 рефералов (максимальная оптимизация)
                            for ref in referrals:
                                referred_id = ref['referred_id']
                                try:
                                    if not check_subscription(referred_id):
                                        db.invalidate_referral(user_id, referred_id)
                                except:
                                    pass
                        
                        # Проверка подозрительной активности (только для каждого 20-го)
                        if is_subscribed and i % 20 == 0:
                            if db.check_suspicious_activity(user_id):
                                db.ban_user(user_id)
                                try:
                                    bot.send_message(user_id, "❌ Вы заблокированы за подозрительную активность!")
                                except:
                                    pass
                        
                        processed_users.add(user_id)
                    except:
                        pass
                
                # Минимальная пауза между батчами
                time.sleep(0.5)
        
        except Exception:
            # Без логирования для максимальной скорости
            time.sleep(60)

def notify_contest_end():
    """Уведомить всех пользователей о завершении конкурса"""
    try:
        winners = db.get_top_users_for_prize(1)  # Используем функцию для призов
        first_100_winner = db.get_first_100_winner()
        
        text = "🎉 <b>КОНКУРС ЗАВЕРШЕН!</b>\n\n"
        
        if len(winners) >= 1:
            text += f"🥇 <b>1 МЕСТО:</b>\n"
            text += f"@{winners[0].get('username', 'N/A')} - {winners[0]['referrals_count']} рефералов\n"
            text += f"Приз: {PRIZE_1ST}\n\n"
        
        if first_100_winner:
            text += f"⚡ <b>ПЕРВЫЙ, КТО НАБРАЛ 100 РЕФЕРАЛОВ:</b>\n"
            text += f"@{first_100_winner.get('username', 'N/A')} - {first_100_winner['referrals_count']} рефералов\n"
            text += f"Приз: {PRIZE_FIRST_100}\n\n"
        
        text += "Спасибо всем за участие! 🎊"
        
        # Отправляем сообщение всем пользователям (оптимизированно - батчами)
        all_users = db.get_all_users()
        batch_size = 20  # Отправляем по 20 сообщений за раз
        for i in range(0, len(all_users), batch_size):
            batch = all_users[i:i+batch_size]
            for user in batch:
                try:
                    bot.send_message(user['user_id'], text, parse_mode='HTML')
                except:
                    pass
            time.sleep(0.1)  # Небольшая задержка между батчами
    except Exception as e:
        pass  # Минимальное логирование для оптимизации

# Запуск фоновой задачи
threading.Thread(target=background_anti_cheat, daemon=True).start()

# Обработка ошибок с неизвестными типами обновлений (Stories и др.)
# Проблема: библиотека pyTelegramBotAPI 4.14.0 не может обработать новые типы обновлений (Stories)
# Решение: патчим десериализацию для игнорирования Story обновлений

import telebot.types

# Патчим десериализацию Message для удаления story перед десериализацией
_original_message_de_json = telebot.types.Message.de_json

def safe_message_de_json(json_string):
    """Безопасная десериализация Message с удалением Story"""
    try:
        # Если это словарь, удаляем story перед десериализацией
        if isinstance(json_string, dict):
            json_string = json_string.copy()
            if 'story' in json_string:
                del json_string['story']
        # Вызываем оригинальную функцию десериализации
        return _original_message_de_json(json_string)
    except Exception as e:
        # Игнорируем ошибки с Story
        error_str = str(e)
        if "Story" in error_str or "unexpected keyword argument" in error_str:
            return None
        # Для других ошибок пробрасываем исключение
        raise

# Заменяем метод десериализации Message
telebot.types.Message.de_json = staticmethod(safe_message_de_json)

# Патчим десериализацию Update для пропуска обновлений со Stories
_original_update_de_json = telebot.types.Update.de_json

def safe_update_de_json(json_string):
    """Безопасная десериализация Update с пропуском Story обновлений"""
    try:
        # Если это словарь, проверяем наличие story
        if isinstance(json_string, dict):
            # Пропускаем обновления со Stories полностью
            if 'story' in json_string:
                return None
            
            # Удаляем story из message, если есть
            if 'message' in json_string and isinstance(json_string['message'], dict):
                if 'story' in json_string['message']:
                    # Создаем копию без story
                    json_string = json_string.copy()
                    message = json_string['message'].copy()
                    del message['story']
                    json_string['message'] = message
        
        # Вызываем оригинальную функцию десериализации
        return _original_update_de_json(json_string)
    except Exception as e:
        # Игнорируем ошибки с Story
        error_str = str(e)
        if "Story" in error_str or "unexpected keyword argument" in error_str:
            return None
        # Для других ошибок пробрасываем исключение
        raise

# Заменяем метод десериализации Update
telebot.types.Update.de_json = staticmethod(safe_update_de_json)

if __name__ == "__main__":
    try:
        print("Инициализация бота...")
        print("Проверка базы данных...")
        # Проверка подключения к базе данных
        test_user = db.get_user(1)  # Тестовая проверка
        print("База данных подключена успешно!")
        
        print("Проверка токена бота...")
        # Проверка токена бота
        bot_info = bot.get_me()
        print(f"Бот подключен: @{bot_info.username}")
        
        print("Бот запущен!")
        # Используем allowed_updates для фильтрации только нужных типов обновлений
        # skip_pending=True пропускает старые обновления (включая те, что содержат Stories)
        # Обрабатываем ошибки Story внутри polling через патч Message.de_json
        bot.polling(none_stop=True, interval=1, timeout=20, skip_pending=True, allowed_updates=['message', 'callback_query', 'edited_message'])
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

