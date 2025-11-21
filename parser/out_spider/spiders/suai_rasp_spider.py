import scrapy
import json
import os
import re
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from minio import Minio
import io

class SheduleSpider(scrapy.Spider):
    name = 'guap_rasp'
    start_urls = ['https://guap.ru/rasp']

    custom_settings = {
        'CONCURRENT_REQUESTS': 3,
        'DOWNLOAD_DELAY': 0.5,
    }

    def __init__(self, *args, **kwargs):
        super(SheduleSpider, self).__init__(*args, **kwargs)

        # Берем настройки из settings.py
        from scrapy.utils.project import get_project_settings
        settings = get_project_settings()
        self.minio_config = settings.get('MINIO_CONFIG', {})

        # Инициализация MinIO клиента
        self.minio_client = Minio(
            self.minio_config['endpoint'],
            access_key=self.minio_config['access_key'],
            secret_key=self.minio_config['secret_key'],
            secure=self.minio_config['secure']
        )
        self.bucket_name = self.minio_config['bucket_name']

        # Создаем бакет если не существует
        self.setup_minio_bucket()

    def setup_minio_bucket(self):
        """Создает бакет в MinIO если не существует"""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                self.logger.info(f"Создан бакет в MinIO: {self.bucket_name}")
        except Exception as e:
            self.logger.error(f"Ошибка создания бакета в MinIO: {e}")

    def parse(self, response):
        self.logger.info("Собираем фильтры")

        # Простые селекторы
        selectors = {
            'selGroup': 'groups',
            'selPrep': 'teachers',
            'selChair': 'departments',
            'selRoom': 'classrooms'
        }

        filters_data = {}

        for selector, entity_type in selectors.items():
            options = response.css(f'select[name="{selector}"] option[value][value!=""]')
            entities = []

            for opt in options:
                entity_id = opt.attrib.get('value')
                entity_name = opt.css('::text').get()

                if entity_id and entity_name:
                    entities.append({
                        'id': entity_id.strip(),
                        'name': entity_name.strip()
                    })

            filters_data[entity_type] = entities
            self.logger.info(f"{entity_type}: {len(entities)}")

        # Парсим
        for entity_type, entities in filters_data.items():
            for entity in entities:
                yield from self.download_schedule(response.url, entity_type, entity)

    def download_schedule(self, base_url, entity_type, entity):
        """Скачиваем расписание для одной сущности"""
        # Маппинг селекторов на параметры URL
        param_map = {
            'groups': 'gr',
            'teachers': 'pr',
            'departments': 'ch',
            'classrooms': 'ad'
        }

        param_name = param_map[entity_type]
        url = f"{base_url}?{param_name}={entity['id']}"

        yield scrapy.Request(
            url,
            callback=self.extract_schedule_text,
            meta={
                'entity_type': entity_type,
                'entity_id': entity['id'],
                'entity_name': entity['name']
            }
        )

    def extract_schedule_text(self, response):
        """Извлекаем расписание в виде чистого текста"""
        meta = response.meta
        schedule_text = self.parse_schedule_to_text(response)

        # Сохраняем ВСЕ txt файлы в одну папку schedules/
        filename = f"schedules/{meta['entity_type']}_{meta['entity_id']}.txt"

        # Сохраняем в MinIO
        self.save_to_minio(
            filename,
            schedule_text.encode('utf-8'),
            "text/plain"
        )

        self.logger.info(f"Сохранено: {filename}")

        yield {
            'type': meta['entity_type'],
            'id': meta['entity_id'],
            'name': meta['entity_name'],
            'file': filename
        }

    def save_to_minio(self, object_name, data, content_type):
        """Сохраняет данные в MinIO"""
        try:
            self.minio_client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type
            )
        except Exception as e:
            self.logger.error(f"Ошибка сохранения в MinIO {object_name}: {e}")

    def parse_schedule_to_text(self, response):
        """Преобразуем HTML расписание в чистый текст"""
        text_parts = []

        # Извлекаем дни недели
        days = response.css('h4.text-danger.border-bottom')

        for day in days:
            day_name = day.css('::text').get().strip()
            text_parts.append(f"\n{day_name}")

            # Находим все занятия для этого дня
            current = day.xpath('following-sibling::*[1]')
            while current and not (current.css('h4.text-danger.border-bottom')):
                # Если это время пары
                if 'mt-3 text-danger' in current.attrib.get('class', ''):
                    time_text = current.css('::text').get().strip()
                    text_parts.append(f"\n{time_text}")

                # Если это блок с занятием
                elif 'mb-3 py-2 d-flex gap-2' in current.attrib.get('class', ''):
                    lesson_text = self.parse_lesson_to_text(current)
                    if lesson_text.strip():  # Добавляем только если есть текст
                        text_parts.append(lesson_text)

                current = current.xpath('following-sibling::*[1]')

        return '\n'.join(text_parts)

    def parse_lesson_to_text(self, lesson_element):
        """Преобразуем один блок занятия в норм текст"""
        # Получаем текст из блока с деталями
        details_text = self.extract_all_details_text(lesson_element)

        # Неделя (▲ или ▼)
        week_symbol = lesson_element.css('div[class*="week"]::text').get('').strip()

        # Тип занятия
        lesson_type = lesson_element.css('.fs-6.lh-sm.opacity-50::text').get('').strip()

        # Название предмета
        subject = lesson_element.css('.lead.lh-sm::text').get('').strip()

        # Форматируем
        lines = []
        if week_symbol:
            lines.append(week_symbol)
        if lesson_type:
            lines.append(lesson_type)
        if subject:
            lines.append(subject)
        if details_text:
            lines.append(details_text)

        return '\n'.join(lines)

    def extract_all_details_text(self, lesson_element):
        """Извлекает текст из блока с деталями и добавляет переносы"""
        details_div = lesson_element.css('.opacity-75')
        if not details_div:
            return ''

        # Получаем весь HTML блока
        details_html = details_div.get()

        # Сначала извлекаем чистый текст без HTML
        soup = BeautifulSoup(details_html, 'html.parser')
        clean_text = soup.get_text(separator=' ')

        # Очищаем пробелы
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        # Теперь добавляем переносы в чистый текст
        # Добавляем перенос перед "преп:"
        clean_text = re.sub(r'преп:', '\nпреп:', clean_text)

        # Добавляем перенос перед "гр:"
        clean_text = re.sub(r'гр:', '\nгр:', clean_text)

        return clean_text

def closed(self, reason):
    self.logger.info("Парсинг расписаний завершен")