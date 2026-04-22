#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт автоматической обработки данных парсера через локальную Ollama API.

📋 ИНСТРУКЦИЯ ПО ЗАПУСКУ:
1. Установите зависимости: pip install -r requirements.txt
2. Установите и запустите Ollama на вашем ПК
3. Запустите: python main.py

Скрипт будет мониторить markup_output.txt и автоматически отправлять
новые данные в локальную Ollama, выводить ответы в консоль и нажимать
соответствующую клавишу (1-4) и затем Shift+S через библиотеку keyboard.
"""

import os
import sys
import time
import hashlib
import logging
import json
import re
import random
from datetime import datetime
from pathlib import Path

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import keyboard

# 🔹 БЛОК КОНФИГУРАЦИИ
# =============================================================================
MODEL_ID = "qwen2.5:14b"  # Название модели в Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
INPUT_FILE = "C:\\Users\\gahar\\Desktop\\P_W\\markup_output.txt"
COOLDOWN_SEC = 10  # Минимальная пауза между запросами к API
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


class ParserFileHandler(FileSystemEventHandler):
    """Обработчик событий изменения файла парсера."""

    def __init__(self, input_file: str, model_id: str, cooldown: int):
        super().__init__()
        self.input_file = input_file
        self.model_id = model_id
        self.cooldown = cooldown
        
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

    def _send_to_ollama(self, user_content: str) -> str | None:
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model_id,
            "prompt": user_content,
            "stream": False
        }
        
        try:
            response = requests.post(OLLAMA_URL, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            content = result.get("response", "")
            logger.info("Ответ успешно получен от Ollama API")
            return content
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка при запросе к Ollama: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Сетевая ошибка при запросе к Ollama: {e}. Убедитесь, что Ollama запущена.")
        except KeyError as e:
            logger.error(f"Ошибка парсинга ответа Ollama (отсутствует ключ {e})")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при запросе к Ollama: {e}")
        
        return None

    def _extract_rating_from_response(self, ai_response: str) -> str | None:
        match = re.search(r"\b([1-4])\b", ai_response)
        if match:
            return match.group(1)
        match = re.search(r"[1-4]", ai_response)
        if match:
            return match.group(0)
        return None

    def _simulate_key_press(self, key: str):
        """Симулирует нажатие клавиши с человеческими задержками."""
        # Случайная задержка перед нажатием (от 1 до 3 секунд) для имитации человека
        delay = random.uniform(1.0, 3.0)
        logger.info(f"Задержка {delay:.2f} сек перед нажатием клавиши {key} (имитация человека)")
        time.sleep(delay)
        
        logger.info(f"Эмуляция нажатия клавиши: {key}")
        keyboard.press(key)
        keyboard.release(key)
        
        # Случайная задержка между нажатием и отпусканием клавиши (50-150 мс)
        press_duration = random.uniform(0.05, 0.15)
        time.sleep(press_duration)
        
        logger.info(f"Клавиша {key} успешно отправлена")

    def _simulate_shift_s(self):
        """Симулирует нажатие комбинации Shift+S с человеческими задержками."""
        # Случайная задержка перед нажатием (от 1 до 2 секунд)
        delay = random.uniform(1.0, 2.0)
        logger.info(f"Задержка {delay:.2f} сек перед нажатием Shift+S (имитация человека)")
        time.sleep(delay)
        
        logger.info("Эмуляция нажатия Shift+S")
        keyboard.press('shift')
        keyboard.press('s')
        time.sleep(0.1)
        keyboard.release('s')
        keyboard.release('shift')
        
        logger.info("Shift+S успешно отправлен")

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
                ai_response = self._send_to_ollama(user_content)
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
                        # Нажимаем цифру, которую прислала нейросеть
                        self._simulate_key_press(rating)
                        # Затем нажимаем Shift+S
                        self._simulate_shift_s()
                    else:
                        logger.warning("Не удалось извлечь оценку (1-4) из ответа нейросети")
                    self.last_request_time = time.time()
                else:
                    logger.warning("Ответ от Ollama не получен")
        except FileNotFoundError:
            logger.error(f"Файл {self.input_file} не найден")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке файла: {e}")
        finally:
            self.is_processing = False


def ensure_file_exists(filepath: str):
    if not os.path.exists(filepath):
        Path(filepath).touch()
        logger.info(f"Создан файл: {filepath}")


def main():
    logger.info(f"Используемая модель: {MODEL_ID}")
    ensure_file_exists(INPUT_FILE)
    
    event_handler = ParserFileHandler(
        input_file=INPUT_FILE,
        model_id=MODEL_ID,
        cooldown=COOLDOWN_SEC
    )
    observer = Observer()
    observer.schedule(event_handler, path=os.path.dirname(os.path.abspath(INPUT_FILE)) or ".", recursive=False)
    observer.start()
    logger.info(f"Мониторинг запущен. Ожидание изменений в файле: {INPUT_FILE}")
    logger.info("Ответы нейросети будут выводиться в консоль")
    logger.info(f"Cooldown между запросами: {COOLDOWN_SEC} сек.")
    logger.info("После получения оценки программа нажмёт цифру (1-4), а затем Shift+S")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
        observer.stop()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        observer.stop()
    observer.join()
    logger.info("Скрипт остановлен")


if __name__ == "__main__":
    main()
