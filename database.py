import sqlite3
import threading
from datetime import datetime, timedelta
from config import CONTEST_DURATION_DAYS, MIN_REFERRALS_FOR_PRIZE

class Database:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        try:
            # Максимальная оптимизация SQLite
            self.conn = sqlite3.connect('referral_bot.db', check_same_thread=False, timeout=10.0)
            self.conn.row_factory = sqlite3.Row
            # Включаем оптимизации SQLite (с обработкой ошибок)
            try:
                self.conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging для скорости
            except:
                pass
            try:
                self.conn.execute('PRAGMA synchronous=NORMAL')  # Баланс скорости и надежности
            except:
                pass
            try:
                self.conn.execute('PRAGMA cache_size=10000')  # Увеличенный кэш
            except:
                pass
            try:
                self.conn.execute('PRAGMA temp_store=MEMORY')  # Временные данные в памяти
            except:
                pass
            # Уменьшенный mmap_size для систем с ограниченной памятью (может вызывать segfault)
            try:
                self.conn.execute('PRAGMA mmap_size=67108864')  # 64MB вместо 256MB
            except:
                pass
            self.cursor = self.conn.cursor()
            self.pending_commits = 0  # Счетчик для батчинга коммитов
            self.init_database()
        except Exception as e:
            print(f"Ошибка инициализации базы данных: {e}")
            raise
    
    def init_database(self):
        """Инициализация базы данных"""
        try:
            # Таблица пользователей
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    referral_code TEXT UNIQUE,
                    referrals_count INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_check TIMESTAMP
                )
            ''')
        
            # Таблица рефералов (кто кого пригласил)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER,
                    referred_id INTEGER,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_valid INTEGER DEFAULT 1,
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                    FOREIGN KEY (referred_id) REFERENCES users(user_id),
                    UNIQUE(referrer_id, referred_id)
                )
            ''')
            
            # Таблица проверок подписки (анти-чит)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscription_checks (
                    user_id INTEGER,
                    check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    was_subscribed INTEGER,
                    PRIMARY KEY (user_id, check_time)
                )
            ''')
            
            # Таблица истории подписок (для отслеживания отписок/подписок)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица ожидающих рефералов (для обработки после подписки)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_referrals (
                    user_id INTEGER PRIMARY KEY,
                    referrer_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица настроек конкурса
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS contest_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Инициализация даты начала конкурса, если её нет
            self.cursor.execute('SELECT value FROM contest_settings WHERE key = ?', ('start_date',))
            if not self.cursor.fetchone():
                start_date = datetime.now().isoformat()
                self.cursor.execute('INSERT INTO contest_settings (key, value) VALUES (?, ?)', ('start_date', start_date))
            
            # Инициализация победителя за 50 рефералов
            self.cursor.execute('SELECT value FROM contest_settings WHERE key = ?', ('first_50_winner',))
            if not self.cursor.fetchone():
                self.cursor.execute('INSERT INTO contest_settings (key, value) VALUES (?, ?)', ('first_50_winner', ''))
            
            # Таблица участников конкурса на печеньку (Clover Pin)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS clover_contest_participants (
                    user_id INTEGER PRIMARY KEY,
                    notified INTEGER DEFAULT 0,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
        
            # Создание индексов для оптимизации (ускоряют запросы)
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_referrals ON users(referrals_count)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id, is_valid)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_clover_participants ON clover_contest_participants(user_id)')
            
            self.conn.commit()
        except Exception as e:
            print(f"Ошибка при инициализации базы данных: {e}")
            self.conn.rollback()
            raise
    
    # Кэш для часто используемых запросов
    _user_cache = {}
    _cache_lock = threading.Lock()
    
    def get_user(self, user_id):
        """Получить пользователя (с кэшированием)"""
        # Проверка кэша
        with self._cache_lock:
            if user_id in self._user_cache:
                cached_time, cached_data = self._user_cache[user_id]
                if (datetime.now() - cached_time).total_seconds() < 60:  # Кэш на 1 минуту
                    return cached_data
        
        # Запрос к БД
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        result = dict(row) if row else None
        
        # Сохранение в кэш
        if result:
            with self._cache_lock:
                self._user_cache[user_id] = (datetime.now(), result)
                # Очистка старого кэша
                if len(self._user_cache) > 500:
                    oldest = min(self._user_cache.keys(), 
                               key=lambda k: self._user_cache[k][0])
                    del self._user_cache[oldest]
        
        return result
    
    def create_user(self, user_id, username, first_name, referral_code):
        """Создать нового пользователя"""
        try:
            self.cursor.execute('''
                INSERT INTO users (user_id, username, first_name, referral_code)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, referral_code))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_referral_code(self, user_id):
        """Получить реферальный код пользователя"""
        user = self.get_user(user_id)
        return user['referral_code'] if user else None
    
    def get_referrer_id(self, referral_code):
        """Получить ID реферера по коду"""
        self.cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        row = self.cursor.fetchone()
        return row['user_id'] if row else None
    
    def add_referral(self, referrer_id, referred_id):
        """Добавить реферала"""
        try:
            self.cursor.execute('''
                INSERT INTO referrals (referrer_id, referred_id, subscribed_at)
                VALUES (?, ?, ?)
            ''', (referrer_id, referred_id, datetime.now().isoformat()))
            
            # Увеличить счетчик рефералов и получить новое значение за один запрос (оптимизация)
            self.cursor.execute('''
                UPDATE users SET referrals_count = referrals_count + 1
                WHERE user_id = ?
            ''', (referrer_id,))
            
            # Получаем новое количество рефералов
            self.cursor.execute('SELECT referrals_count FROM users WHERE user_id = ?', (referrer_id,))
            user_row = self.cursor.fetchone()
            new_count = user_row['referrals_count'] if user_row else 0
            
            # Проверка на достижение 50 рефералов (только если >= 50)
            if new_count >= 50:
                # Проверяем и обновляем за один запрос (максимальная оптимизация)
                self.cursor.execute('''
                    UPDATE contest_settings 
                    SET value = ?
                    WHERE key = 'first_50_winner' AND (value IS NULL OR value = '')
                ''', (str(referrer_id),))
            
            # Коммитим сразу для критичных операций
            self.conn.commit()
            
            # Инвалидация кэша пользователя
            with self._cache_lock:
                if referrer_id in self._user_cache:
                    del self._user_cache[referrer_id]
            
            return True
        except sqlite3.IntegrityError:
            return False
    
    def check_referral_exists(self, referrer_id, referred_id):
        """Проверить, существует ли уже такой реферал"""
        self.cursor.execute('''
            SELECT * FROM referrals 
            WHERE referrer_id = ? AND referred_id = ?
        ''', (referrer_id, referred_id))
        return self.cursor.fetchone() is not None
    
    def invalidate_referral(self, referrer_id, referred_id):
        """Аннулировать реферала (анти-чит)"""
        self.cursor.execute('''
            UPDATE referrals SET is_valid = 0
            WHERE referrer_id = ? AND referred_id = ?
        ''', (referrer_id, referred_id))
        
        # Уменьшить счетчик
        self.cursor.execute('''
            UPDATE users SET referrals_count = referrals_count - 1
            WHERE user_id = ?
        ''', (referrer_id,))
        
        self.conn.commit()
    
    def get_top_users(self, limit=10):
        """Получить ТОП пользователей (все пользователи, отсортированные по количеству рефералов)"""
        self.cursor.execute('''
            SELECT user_id, username, first_name, referrals_count
            FROM users
            WHERE is_banned = 0 AND referrals_count > 0
            ORDER BY referrals_count DESC
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in self.cursor.fetchall()]
    
    def get_top_users_for_prize(self, limit=10):
        """Получить ТОП пользователей для приза (только с минимальным порогом)"""
        self.cursor.execute('''
            SELECT user_id, username, first_name, referrals_count
            FROM users
            WHERE is_banned = 0 AND referrals_count >= ?
            ORDER BY referrals_count DESC
            LIMIT ?
        ''', (MIN_REFERRALS_FOR_PRIZE, limit))
        return [dict(row) for row in self.cursor.fetchall()]
    
    def log_subscription_check(self, user_id, was_subscribed):
        """Логировать проверку подписки"""
        self.cursor.execute('''
            INSERT INTO subscription_checks (user_id, check_time, was_subscribed)
            VALUES (?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), 1 if was_subscribed else 0))
        self.conn.commit()
    
    def log_subscription_action(self, user_id, action):
        """Логировать действие подписки (subscribe/unsubscribe)"""
        self.cursor.execute('''
            INSERT INTO subscription_history (user_id, action, timestamp)
            VALUES (?, ?, ?)
        ''', (user_id, action, datetime.now().isoformat()))
        self.conn.commit()
    
    def check_suspicious_activity(self, user_id):
        """Проверить подозрительную активность пользователя"""
        # Проверяем последние 10 проверок подписки
        self.cursor.execute('''
            SELECT was_subscribed FROM subscription_checks
            WHERE user_id = ?
            ORDER BY check_time DESC
            LIMIT 10
        ''', (user_id,))
        
        checks = [row['was_subscribed'] for row in self.cursor.fetchall()]
        
        # Если есть переключения подписки (0->1->0->1), это подозрительно
        if len(checks) >= 4:
            switches = sum(1 for i in range(len(checks)-1) if checks[i] != checks[i+1])
            if switches >= 3:  # 3+ переключения - подозрительно
                return True
        
        return False
    
    def ban_user(self, user_id):
        """Забанить пользователя"""
        self.cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
        self.conn.commit()
        # Инвалидация кэша
        with self._ban_cache_lock:
            if user_id in self._ban_cache:
                del self._ban_cache[user_id]
        with self._cache_lock:
            if user_id in self._user_cache:
                del self._user_cache[user_id]
    
    def unban_user(self, user_id):
        """Разбанить пользователя"""
        self.cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
        self.conn.commit()
        # Инвалидация кэша
        with self._ban_cache_lock:
            if user_id in self._ban_cache:
                del self._ban_cache[user_id]
        with self._cache_lock:
            if user_id in self._user_cache:
                del self._user_cache[user_id]
    
    # Кэш для проверки бана (для максимальной скорости)
    _ban_cache = {}
    _ban_cache_lock = threading.Lock()
    
    def is_banned(self, user_id):
        """Проверить, забанен ли пользователь (с кэшированием)"""
        # Быстрая проверка кэша
        with self._ban_cache_lock:
            if user_id in self._ban_cache:
                cached_time, cached_result = self._ban_cache[user_id]
                if (datetime.now() - cached_time).total_seconds() < 300:  # Кэш на 5 минут
                    return cached_result
        
        # Запрос к БД (использует кэш пользователя)
        user = self.get_user(user_id)
        result = user and user['is_banned'] == 1
        
        # Сохранение в кэш
        with self._ban_cache_lock:
            self._ban_cache[user_id] = (datetime.now(), result)
            # Очистка старого кэша
            if len(self._ban_cache) > 500:
                oldest = min(self._ban_cache.keys(), 
                           key=lambda k: self._ban_cache[k][0])
                del self._ban_cache[oldest]
        
        return result
    
    def get_contest_start_date(self):
        """Получить дату начала конкурса"""
        self.cursor.execute('SELECT value FROM contest_settings WHERE key = ?', ('start_date',))
        row = self.cursor.fetchone()
        if row:
            return datetime.fromisoformat(row['value'])
        return datetime.now()
    
    def is_contest_ended(self):
        """Проверить, закончился ли конкурс"""
        start_date = self.get_contest_start_date()
        end_date = start_date + timedelta(days=CONTEST_DURATION_DAYS)
        return datetime.now() >= end_date
    
    def get_contest_end_date(self):
        """Получить дату окончания конкурса"""
        start_date = self.get_contest_start_date()
        return start_date + timedelta(days=CONTEST_DURATION_DAYS)
    
    def get_first_50_winner(self):
        """Получить победителя за первое достижение 50 рефералов"""
        self.cursor.execute('SELECT value FROM contest_settings WHERE key = ?', ('first_50_winner',))
        row = self.cursor.fetchone()
        if row and row['value']:
            try:
                winner_id = int(row['value'])
                user = self.get_user(winner_id)
                return user
            except:
                return None
        return None
    
    def check_and_set_first_50_winner(self, user_id, referrals_count):
        """Проверить и установить победителя за 50 рефералов (оптимизированная версия)"""
        if referrals_count >= 50:
            self.cursor.execute('SELECT value FROM contest_settings WHERE key = ?', ('first_50_winner',))
            winner_row = self.cursor.fetchone()
            if winner_row and not winner_row['value']:
                self.cursor.execute('UPDATE contest_settings SET value = ? WHERE key = ?', 
                                  (str(user_id), 'first_50_winner'))
                self.conn.commit()
                return True
        return False
    
    def add_pending_referral(self, user_id, referrer_id):
        """Добавить ожидающий реферал (пользователь еще не подписан)"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO pending_referrals (user_id, referrer_id)
                VALUES (?, ?)
            ''', (user_id, referrer_id))
            self.conn.commit()
            return True
        except:
            return False
    
    def get_pending_referral(self, user_id):
        """Получить ожидающий реферал для пользователя"""
        self.cursor.execute('SELECT referrer_id FROM pending_referrals WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row['referrer_id'] if row else None
    
    def remove_pending_referral(self, user_id):
        """Удалить ожидающий реферал"""
        self.cursor.execute('DELETE FROM pending_referrals WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def get_all_users(self):
        """Получить всех пользователей"""
        self.cursor.execute('SELECT * FROM users')
        return [dict(row) for row in self.cursor.fetchall()]
    
    # Методы для конкурса на печеньку (Clover Pin)
    def add_clover_participant(self, user_id):
        """Добавить участника конкурса на печеньку"""
        try:
            self.cursor.execute('''
                INSERT OR IGNORE INTO clover_contest_participants (user_id, notified, joined_at)
                VALUES (?, 0, ?)
            ''', (user_id, datetime.now().isoformat()))
            self.conn.commit()
            return True
        except:
            return False
    
    def is_clover_participant(self, user_id):
        """Проверить, является ли пользователь участником конкурса на печеньку"""
        self.cursor.execute('SELECT user_id FROM clover_contest_participants WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def mark_clover_notified(self, user_id):
        """Отметить, что участнику отправлено уведомление о участии"""
        try:
            self.cursor.execute('''
                UPDATE clover_contest_participants 
                SET notified = 1 
                WHERE user_id = ?
            ''', (user_id,))
            self.conn.commit()
            return True
        except:
            return False
    
    def is_clover_notified(self, user_id):
        """Проверить, отправлено ли уведомление участнику"""
        self.cursor.execute('SELECT notified FROM clover_contest_participants WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row and row['notified'] == 1
    
    def get_all_clover_participants(self):
        """Получить всех участников конкурса на печеньку"""
        self.cursor.execute('''
            SELECT p.user_id, u.username, u.first_name, u.referrals_count
            FROM clover_contest_participants p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.is_banned = 0
        ''')
        return [dict(row) for row in self.cursor.fetchall()]
    
    def close(self):
        """Закрыть соединение"""
        self.conn.close()

