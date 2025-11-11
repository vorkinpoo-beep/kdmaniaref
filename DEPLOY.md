# 📦 Инструкция по развертыванию

## Загрузка в GitHub

### 1. Инициализация Git репозитория

```bash
cd kdmaniaref
git init
git add .
git commit -m "Initial commit: Referral bot for Ksody Design"
```

### 2. Подключение к GitHub

```bash
git remote add origin https://github.com/Vorkinpoo-beep/kdmaniaref.git
git branch -M main
git push -u origin main
```

## Развертывание на VNC сервере

### Подключение к VNC

1. Откройте VNC клиент (TightVNC, RealVNC, TigerVNC)
2. Подключитесь к вашему серверу
3. Откройте терминал в VNC сессии

### Установка необходимого ПО

```bash
# Обновление системы (Ubuntu/Debian)
sudo apt update && sudo apt upgrade -y

# Установка Python и Git
sudo apt install python3 python3-pip git screen -y
```

### Клонирование и настройка

```bash
# Переход в домашнюю директорию
cd ~

# Клонирование репозитория
git clone https://github.com/Vorkinpoo-beep/kdmaniaref.git
cd kdmaniaref

# Установка зависимостей
pip3 install -r requirements.txt
```

### Запуск бота

```bash
# Создание screen сессии
screen -S referral_bot

# Запуск бота
python3 main.py

# Отключение от screen: Ctrl+A, затем D
```

### Проверка работы

```bash
# Возврат к сессии
screen -r referral_bot

# Просмотр логов (если нужно)
# Логи будут видны в screen сессии
```

## Автозапуск при перезагрузке (опционально)

### Создание systemd сервиса

```bash
sudo nano /etc/systemd/system/referral-bot.service
```

Вставьте следующее содержимое (замените `your_username` на ваше имя пользователя):

```ini
[Unit]
Description=Ksody Design Referral Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/kdmaniaref
ExecStart=/usr/bin/python3 /home/your_username/kdmaniaref/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Активация сервиса

```bash
# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable referral-bot

# Запуск сервиса
sudo systemctl start referral-bot

# Проверка статуса
sudo systemctl status referral-bot

# Просмотр логов
sudo journalctl -u referral-bot -f
```

## Обновление бота

```bash
cd ~/kdmaniaref
git pull origin main

# Если используете systemd
sudo systemctl restart referral-bot

# Если используете screen
screen -r referral_bot
# Остановите бота (Ctrl+C) и запустите снова
python3 main.py
```

## Мониторинг

### Проверка использования ресурсов

```bash
# CPU и память
top

# Только процессы Python
ps aux | grep python3
```

### Проверка базы данных

```bash
cd ~/kdmaniaref
sqlite3 referral_bot.db

# Полезные команды SQLite:
# .tables - показать таблицы
# SELECT * FROM users LIMIT 10; - показать пользователей
# SELECT * FROM referrals LIMIT 10; - показать рефералов
# .quit - выйти
```

## Резервное копирование

```bash
# Создание бэкапа базы данных
cp ~/kdmaniaref/referral_bot.db ~/referral_bot_backup_$(date +%Y%m%d).db

# Автоматический бэкап (можно добавить в cron)
# 0 2 * * * cp ~/kdmaniaref/referral_bot.db ~/backups/referral_bot_$(date +\%Y\%m\%d).db
```

## Устранение неполадок

### Бот не отвечает

1. Проверьте, запущен ли процесс:
   ```bash
   ps aux | grep main.py
   ```

2. Проверьте логи в screen:
   ```bash
   screen -r referral_bot
   ```

3. Проверьте токен бота в `config.py`

### Ошибки подключения к Telegram

- Убедитесь, что токен бота правильный
- Проверьте интернет-соединение
- Убедитесь, что бот не заблокирован

### Проблемы с проверкой подписки

- Убедитесь, что бот добавлен как администратор в канал
- Проверьте правильность `CHANNEL_ID` в `config.py`
- Убедитесь, что у бота есть права на просмотр участников

## Контакты

По вопросам: @Ksodydes

