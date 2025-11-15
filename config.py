# Конфигурация бота
BOT_TOKEN = "8466231099:AAH5yQxLVqi0ldrn0MtHK6_Bkhf443mYXpo"

# ID канала для обязательной подписки
CHANNEL_ID = -1001959515253
CHANNEL_USERNAME = "Ksody Design"
CHANNEL_INVITE_LINK = "https://t.me/+rqIAvQVafGVhYWZi"

# Админ бота
ADMIN_ID = 1617188857
ADMIN_USERNAME = "@Ksodydes"

# Настройки конкурса
CONTEST_DURATION_DAYS = 14
MIN_REFERRALS_FOR_PRIZE = 50
FIRST_50_REFERRALS_PRIZE = 50  # Кто первый наберет 50 рефералов

# Призы
PRIZE_1ST = "https://t.me/nft/SnoopDogg-552170"  # 1 место (больше всех рефералов)
PRIZE_FIRST_50 = "https://t.me/nft/InstantRamen-284068"  # Первый, кто наберет 50 рефералов

# Конкурс на печеньку (Clover Pin)
CLOVER_CONTEST_LINK = "https://t.me/nft/CloverPin-192181"
CLOVER_CONTEST_MIN_REFERRALS = 3  # Минимальное количество рефералов для участия
CLOVER_CONTEST_NOTIFICATION_TEXT = "❤️ПРИГЛАСИ 3+ РЕФЕРАЛОВ И УЧАСТВУЙ В РОЗЫГРЫШЕ НА CLOVER PIN! (t.me/nft/CloverPin-192181)"

# База данных
DATABASE_FILE = "referral_bot.db"

# Настройки оптимизации (МАКСИМАЛЬНАЯ ОПТИМИЗАЦИЯ - БОТ ЛЕТАЕТ!)
CHECK_SUBSCRIPTION_INTERVAL = 300  # 5 минут между проверками подписки (максимальная оптимизация)
ANTI_CHEAT_COOLDOWN = 1800  # 30 минут между повторными проверками одного пользователя
BACKGROUND_CHECK_INTERVAL = 1800  # 30 минут между фоновыми проверками (увеличено для скорости)
CACHE_CLEANUP_INTERVAL = 7200  # 2 часа - очистка кэша
MAX_CACHE_SIZE = 2000  # Увеличенный размер кэша для лучшей производительности
DB_COMMIT_BATCH = 10  # Количество операций перед коммитом (батчинг)
ENABLE_QUERY_CACHE = True  # Кэширование запросов

