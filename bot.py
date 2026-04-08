"""
PolygraphAiSales — заглушка процесса до подключения реальной логики бота.
Замените содержимое на aiogram/telebot и т.д.
"""
import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("PolygraphAiSales: старт (заглушка). Ожидание…")
    while True:
        time.sleep(86400)


if __name__ == "__main__":
    main()
