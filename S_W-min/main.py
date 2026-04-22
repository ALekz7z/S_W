#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт автоматической обработки данных парсера через OpenRouter API.

📋 ИНСТРУКЦИЯ ПО ЗАПУСКУ:
1. Установите зависимости: pip install -r requirements.txt
2. Настройте .env файл (укажите OPENROUTER_API_KEY)
3. В main.py укажите MODEL_ID в блоке CONFIG
4. Создайте system_prompt.txt с инструкцией для нейросети
5. Запустите браузер Thorium с флагом --remote-debugging-port=9222
6. Запустите: python main.py

Скрипт будет мониторить markup_output.txt и автоматически отправлять
новые данные в OpenRouter API, выводить ответы в консоль и нажимать
соответствующую клавишу (1-4) в браузере через CDP.
"""

import os
import sys
import time
import hashlib
import logging
import json
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import websocket

# 🔹 БЛОК КОНФИГУРАЦИИ (🔹 МЕСТА ДЛЯ МОИХ ДАННЫХ)
# =============================================================================
# 🔹 [❗ ВСТАВЬТЕ ВАШ API КЛЮЧ OPENROUTER В ФАЙЛ .env]
# 🔹 [❗ ВСТАВЬТЕ ID МОДЕЛИ, например: google/gemini-2.0-flash-lite-001:free]
MODEL_ID = "nvidia/nemotron-3-super-120b-a12b:free"
INPUT_FILE = "C:\\Users\\gahar\\Desktop\\P_W\\markup_output.txt"
PROMPT_FILE = "system_prompt.txt"
COOLDOWN_SEC = 10  # Минимальная пауза между запросами к API

# Настройки браузера Thorium
BROWSER_DEBUG_PORT = 9222
BROWSER_HOST = "localhost"
# =============================================================================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class BrowserCDPClient:
    """Клиент для подключения к браузеру через Chrome DevTools Protocol."""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.ws_url: str | None = None
        self.ws: websocket.WebSocket | None = None
    
    def get_ws_url(self) -> str | None:
        """Получает WebSocket URL для отладки первой вкладки."""
        try:
            response = requests.get(f"http://{self.host}:{self.port}/json/list", timeout=5)
            pages = response.json()
            for page in pages:
                if page.get("type") == "page":
                    return page.get("webSocketDebuggerUrl")
            logger.warning("Не найдено активных вкладок для отладки")
            return None
        except Exception as e:
            logger.error(f"Ошибка получения WebSocket URL: {e}")
            return None
    
    def connect(self) -> bool:
        """Подключается к браузеру через WebSocket."""
        ws_url = self.get_ws_url()
        if not ws_url:
            return False
        
        try:
            self.ws = websocket.create_connection(ws_url, timeout=5)
            self.ws_url = ws_url
            logger.info(f"Подключено к браузеру через CDP")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к браузеру: {e}")
            return False
    
    def send_command(self, method: str, params: dict | None = None) -> dict | None:
        """Отправляет команду через CDP."""
        if not self.ws:
            if not self.connect():
                return None
        
        command_id = int(time.time() * 1000) % 1000000
        payload = {
            "id": command_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            assert self.ws is not None
            self.ws.send(json.dumps(payload))
            response = self.ws.recv()
            result = json.loads(response)
            
            if "error" in result:
                logger.error(f"Ошибка CDP команды: {result['error']}")
                self.ws.close()
                self.ws = None
                return None
            
            return result.get("result", {})
        except Exception as e:
            logger.error(f"Ошибка отправки CDP команды: {e}")
            if self.ws:
                self.ws.close()
            self.ws = None
            return None
    
    def simulate_key_press(self, key: str):
        """Симулирует нажатие клавиши в браузере с человеческими задержками."""
        import random
        
        # Случайная задержка перед нажатием (от 1 до 3 секунд) для имитации человека
        delay = random.uniform(1.0, 3.0)
        logger.info(f"Задержка {delay:.2f} сек перед нажатием клавиши {key} (имитация человека)")
        time.sleep(delay)
        
        logger.info(f"Эмуляция нажатия клавиши: {key}")
        
        self.send_command("Input.enable")
        
        # Небольшая случайная задержка между keyDown и keyUp для реалистичности
        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "text": key,
            "unmodifiedText": key,
            "key": key,
            "code": f"Digit{key}" if key.isdigit() else key,
            "windowsVirtualKeyCode": ord(key),
            "nativeVirtualKeyCode": ord(key),
            "autoRepeat": False,
            "isKeypad": False,
            "isSystemKey": False
        })
        
        # Случайная задержка между нажатием и отпусканием клавиши (50-150 мс)
        press_duration = random.uniform(0.05, 0.15)
        time.sleep(press_duration)
        
        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "text": key,
            "unmodifiedText": key,
            "key": key,
            "code": f"Digit{key}" if key.isdigit() else key,
            "windowsVirtualKeyCode": ord(key),
            "nativeVirtualKeyCode": ord(key),
            "autoRepeat": False,
            "isKeypad": False,
            "isSystemKey": False
        })
        
        logger.info(f"Клавиша {key} успешно отправлена в браузер")
    
    def disconnect(self):
        """Отключается от браузера."""
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
            logger.info("Отключено от браузера")


class ParserFileHandler(FileSystemEventHandler):
    """Обработчик событий изменения файла парсера."""

    def __init__(self, input_file: str, system_prompt: str, api_key: str, model_id: str, cooldown: int, browser_client: BrowserCDPClient):
        super().__init__()
        self.input_file = input_file
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.model_id = model_id
        self.cooldown = cooldown
        self.browser_client = browser_client
        
        self.last_position = 0
        self.last_hash = None
        self.last_request_time = 0
        self.is_processing = False
        self.last_ai_response = None

    def _calculate_hash(self, data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    def _check_cooldown(self) -> bool:
        current_time = time.time()
        if current_time - self.last_request_time < self.cooldown:
            logger.debug(f"Cooldown активен. Осталось {self.cooldown - (current_time - self.last_request_time):.1f} сек.")
            return False
        return True

    def _send_to_openrouter(self, user_content: str) -> str | None:
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Parser-AI-Watcher"
        }
        
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content}
            ]
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            logger.info("Ответ успешно получен от OpenRouter API")
            return content
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error(f"Превышен лимит запросов (429). Ждём следующую итерацию.")
            else:
                logger.error(f"HTTP ошибка при запросе к API: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Сетевая ошибка при запросе к API: {e}")
        except KeyError as e:
            logger.error(f"Ошибка парсинга ответа API (отсутствует ключ {e})")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при запросе к API: {e}")
        
        return None

    def _extract_rating_from_response(self, ai_response: str) -> str | None:
        match = re.search(r"([1-4])", ai_response)
        if match:
            return match.group(1)
        match = re.search(r"[1-4]", ai_response)
        if match:
            return match.group(0)
        return None

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path != os.path.abspath(self.input_file):
            return
        if self.is_processing:
            logger.debug("Обработка уже идёт, пропускаем событие")
            return
        if not self._check_cooldown():
            return
        self.is_processing = True
        try:
            file_size = os.path.getsize(self.input_file)
            if file_size < self.last_position:
                logger.info("Файл был перезаписан (размер уменьшился). Сбрасываем позицию.")
                self.last_position = 0
                self.last_hash = None
            with open(self.input_file, "rb") as f:
                f.seek(self.last_position)
                new_data = f.read()
                if not new_data:
                    logger.debug("Новых данных не обнаружено")
                    return
                current_hash = self._calculate_hash(new_data)
                if current_hash == self.last_hash:
                    logger.debug("Данные идентичны предыдущим (по хешу). Пропускаем.")
                    return
                self.last_position = f.tell()
                self.last_hash = current_hash
                try:
                    user_content = new_data.decode("utf-8").strip()
                except UnicodeDecodeError:
                    logger.error("Ошибка декодирования данных (ожидался UTF-8)")
                    return
                if not user_content:
                    logger.debug("Пустые данные после декодирования")
                    return
                logger.info(f"Обнаружены новые данные ({len(user_content)} символов)")
                ai_response = self._send_to_openrouter(user_content)
                if ai_response:
                    self.last_ai_response = ai_response
                    print("=" * 60)
                    print("ОТВЕТ НЕЙРОСЕТИ:")
                    print("=" * 60)
                    print(ai_response)
                    print("=" * 60)
                    rating = self._extract_rating_from_response(ai_response)
                    if rating:
                        logger.info(f"Извлечена оценка: {rating}")
                        self.browser_client.simulate_key_press(rating)
                    else:
                        logger.warning("Не удалось извлечь оценку (1-4) из ответа нейросети")
                    self.last_request_time = time.time()
                else:
                    logger.warning("Ответ от API не получен")
        except FileNotFoundError:
            logger.error(f"Файл {self.input_file} не найден")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке файла: {e}")
        finally:
            self.is_processing = False


def load_system_prompt(prompt_file: str) -> str:
    if not os.path.exists(prompt_file):
        logger.warning(f"Файл {prompt_file} не найден. Создаётся пустой файл.")
        Path(prompt_file).touch()
        return ""
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"Файл {prompt_file} пуст. Нейросеть будет работать без системной инструкции.")
            return content
    except IOError as e:
        logger.error(f"Ошибка чтения файла {prompt_file}: {e}")
        return ""


def ensure_file_exists(filepath: str):
    if not os.path.exists(filepath):
        Path(filepath).touch()
        logger.info(f"Создан файл: {filepath}")


def main():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("🔹 [❗ ВСТАВЬТЕ ВАШ API КЛЮЧ OPENROUTER В ФАЙЛ .env]")
        sys.exit(1)
    logger.info("API ключ найден")
    if "🔹" in MODEL_ID or not MODEL_ID.strip():
        logger.error("🔹 [❗ ВСТАВЬТЕ ID МОДЕЛИ В БЛОКЕ CONFIG В main.py]")
        sys.exit(1)
    logger.info(f"Используемая модель: {MODEL_ID}")
    system_prompt = load_system_prompt(PROMPT_FILE)
    if system_prompt:
        logger.info(f"Системный промпт загружен ({len(system_prompt)} символов)")
    else:
        logger.warning("Работа без системного промпта")
    ensure_file_exists(INPUT_FILE)
    logger.info(f"Подключение к браузеру Thorium на порту {BROWSER_DEBUG_PORT}...")
    browser_client = BrowserCDPClient(BROWSER_HOST, BROWSER_DEBUG_PORT)
    if not browser_client.connect():
        logger.warning("Не удалось подключиться к браузеру. Убедитесь, что Thorium запущен с флагом --remote-debugging-port=9222")
        logger.warning("Программа продолжит работу без эмуляции нажатий клавиш")
    else:
        logger.info("Браузер подключен. Эмуляция нажатий клавиш будет работать.")
    event_handler = ParserFileHandler(
        input_file=INPUT_FILE,
        system_prompt=system_prompt,
        api_key=api_key,
        model_id=MODEL_ID,
        cooldown=COOLDOWN_SEC,
        browser_client=browser_client
    )
    observer = Observer()
    observer.schedule(event_handler, path=os.path.dirname(os.path.abspath(INPUT_FILE)) or ".", recursive=False)
    observer.start()
    logger.info(f"Мониторинг запущен. Ожидание изменений в файле: {INPUT_FILE}")
    logger.info("Ответы нейросети будут выводиться в консоль")
    logger.info(f"Cooldown между запросами: {COOLDOWN_SEC} сек.")
    logger.info(f"Оценки (1-4) будут отправляться в браузер Thorium как нажатия клавиш")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
        observer.stop()
        browser_client.disconnect()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        observer.stop()
        browser_client.disconnect()
    observer.join()
    logger.info("Скрипт остановлен")


if __name__ == "__main__":
    main()
