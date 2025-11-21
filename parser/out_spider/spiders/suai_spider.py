import scrapy
from urllib.parse import urljoin, urlparse
import csv
import os
import hashlib
from scrapy.pipelines.files import FilesPipeline
import requests
from minio import Minio
import io

class LinkParserSpider(scrapy.Spider):
    name = 'link_parser'
    start_urls = []
    output_file = "out_spider/spiders/links.csv"

    visited = set()
    file_links = set()
    file_extensions = [".pdf", ".docx"]

    def __init__(self, start_urls=None, output_file=None, *args, **kwargs):
        super(LinkParserSpider, self).__init__(*args, **kwargs)
        if start_urls:
            self.start_urls = [start_urls]
        if output_file:
            self.output_file = output_file

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

        # Накопление ссылок в памяти
        self.links_buffer = []

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
        self.save_html_page(response.url, response.body)

        if response.status == 404:
            self.logger.warning(f"Страница не найдена: {response.url}")
            return

        links = response.css('a::attr(href)').getall()

        for link in links:
            if link:
                try:
                    full_url = response.urljoin(link)

                    # Пропускаем уже посещенные URL
                    if full_url in self.visited:
                        continue

                    self.visited.add(full_url)

                    # Проверяем на PDF или DOCX
                    is_pdf = full_url.lower().endswith('.pdf')
                    is_docx = full_url.lower().endswith('.docx')

                    if is_pdf or is_docx:
                        file_type = "pdf" if is_pdf else "docx"
                        self.file_links.add(full_url)
                        self.save_link(full_url, file_type)

                    elif full_url.lower().endswith('.html') or urlparse(full_url).netloc == urlparse(
                            self.start_urls[0]).netloc:
                        # Внутренние страницы продолжаем обходить
                        yield scrapy.Request(
                            url=full_url,
                            callback=self.parse,
                            errback=self.handle_error
                        )

                except Exception as e:
                    self.logger.error(f"Ошибка при обработке ссылки {link}: {e}")

    def save_html_page(self, url, html_content):
        """Сохраняет HTML страницу в MinIO"""
        try:
            file_name = hashlib.md5(url.encode('utf-8')).hexdigest() + ".html"
            object_name = f"html_pages/{file_name}"

            # Конвертируем в bytes если нужно
            if isinstance(html_content, str):
                html_content = html_content.encode('utf-8')

            # Сохраняем в MinIO
            self.minio_client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(html_content),
                length=len(html_content),
                content_type="text/html"
            )

            self.logger.info(f"Сохранена HTML-страница в MinIO: {object_name}")
        except Exception as e:
            self.logger.error(f"Ошибка сохранения HTML в MinIO: {e}")

    def save_link(self, url, link_type):
        """Сохраняем ссылку в буфер (в памяти)"""
        self.links_buffer.append([url, link_type])

        # Сбрасываем в MinIO каждые 10 ссылок
        if len(self.links_buffer) >= 10:
            self.flush_links_to_minio()

        self.logger.info(f"Ссылка добавлена в буфер ({link_type}): {url}")

    def flush_links_to_minio(self):
        """Сбрасывает накопленные ссылки в MinIO"""
        if not self.links_buffer:
            return

        try:
            # Создаем CSV в памяти
            output = io.StringIO()
            writer = csv.writer(output)

            # Заголовок
            writer.writerow(['url', 'type'])

            # Данные
            for url, link_type in self.links_buffer:
                writer.writerow([url, link_type])

            # Конвертируем в bytes
            csv_data = output.getvalue().encode('utf-8')

            # Сохраняем в MinIO (перезаписываем весь файл)
            self.minio_client.put_object(
                self.bucket_name,
                "results/links.csv",
                io.BytesIO(csv_data),
                length=len(csv_data),
                content_type="text/csv"
            )

            self.logger.info(f"Сброшено {len(self.links_buffer)} ссылок в MinIO")
            self.links_buffer = []  # Очищаем буфер

        except Exception as e:
            self.logger.error(f"Ошибка сохранения ссылок в MinIO: {e}")

    def handle_error(self, failure):
        """Обработка ошибок запроса"""
        self.logger.error(f"Ошибка запроса: {failure.value}")

    def closed(self, reason):
        self.logger.info(f"Парсинг завершён. Всего найдено {len(self.visited)} ссылок, {len(self.file_links)} файлов.")
