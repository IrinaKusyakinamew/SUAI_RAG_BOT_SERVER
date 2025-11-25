import asyncio
import aiohttp
import pandas as pd
import json
import re
import hashlib
from io import BytesIO
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTFigure
from pdf2image import convert_from_bytes
import pytesseract
import tiktoken
from tqdm import tqdm
from minio_client import get_minio_client

# Бакет, где лежит файл links.csv со ссылками pdf
BUCKET_WEB_CRAWLER = "web-crawler"
# Бакет, куда сохраняются извлеченные по ссылкам pdf документы и чанки
BUCKET_RAG_SOURCES = "rag-sources"

# Папка для сохранения pdf доков
PDF_PREFIX = "saved_pdf"
# Папка для временных чанков
CHUNKS_PREFIX = "tmp_chunks"

# Названия файлов
LINKS_CSV = "links.csv"
OUTPUT_JSON_NAME = "pdf_chunks.json"

# Параметры для чанкинга и скачивания файлов
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
MAX_CONCURRENT = 12
MAX_RETRIES = 3 # Попытки скачивания pdf
MAX_WORKERS = 4 # Процессы для распознавания pdf

client = get_minio_client()

# Функция очистки текста
def normalize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# Функция разбиения текста на чанки
def chunk_by_gpt_tokens(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)
    chunks, start_idx, chunk_id = [], 0, 0

    while start_idx < len(tokens):
        end_idx = min(start_idx + chunk_size, len(tokens))
        # Извлекаем токены чанка
        chunk_text = enc.decode(tokens[start_idx:end_idx])
        # Мягкий перенос, чтобы чанк заканчивался на пробеле
        last_space = chunk_text.rfind(" ")
        if last_space != -1 and end_idx != len(tokens):
            chunk_text = chunk_text[:last_space]
            end_idx = start_idx + len(enc.encode(chunk_text))
        # Вычисляем точное положение чанка в исходном тексте
        start_offset = text.find(chunk_text)
        end_offset = start_offset + len(chunk_text)
        chunks.append({
            "chunk_uid": f"chunk_{chunk_id}",
            "chunk_id": chunk_id,
            "text": chunk_text.strip(),
            "token_count": len(enc.encode(chunk_text)),
            "start_offset": start_offset,
            "end_offset": end_offset
        })
        start_idx = max(end_idx - overlap, end_idx)
        chunk_id += 1
    return [c for c in chunks if c["token_count"] >= 40]

# Функция проверки, является ли текст pdf дока мусорным
def looks_like_garbage(text: str) -> bool:
    if not text:
        return True
    allowed_chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        "0123456789 .,;:-–—()[]\"'«»?!%\n\t"
    )
    garbage_ratio = sum(ch not in allowed_chars for ch in text) / max(len(text), 1)
    if garbage_ratio > 0.3:
        return True
    cid_pattern = re.compile(r"\(cid:\d+\)")
    if cid_pattern.findall(text):
        return True
    return False

# Функция извлечения текста через pdfminer
def extract_text_from_pdf_bytes(pdf_bytes):
    try:
        text_parts = []
        # Рекурсивное извлечение текста из pdf
        def recursive_elements(elements):
            for el in elements:
                if isinstance(el, LTTextContainer):
                    yield el
                elif isinstance(el, LTFigure):
                    yield from recursive_elements(el._objs)

        # Обходим все страницы pdf
        for page_layout in extract_pages(BytesIO(pdf_bytes)):
            page_text = []
            for element in recursive_elements(page_layout):
                if isinstance(element, LTTextContainer):
                    page_text.append(element.get_text().strip())
            if page_text:
                text_parts.append("\n".join(page_text))

        text = normalize_text("\n\n".join(text_parts))

        # Если текст содержит мусор, используем OCR
        if not text or looks_like_garbage(text):
            images = convert_from_bytes(pdf_bytes)
            ocr_texts = [pytesseract.image_to_string(img, config="--psm 6").strip() for img in images]
            text = normalize_text("\n\n".join(ocr_texts))

        return text
    except Exception as e:
        print(f"[Ошибка PDF]: {e}")
        return ""

# Функция предварительной очистки папки с pdf доками перед новой записью
def clear_pdf_prefix(bucket: str, prefix: str):
    objects = client.list_objects(bucket, prefix=prefix, recursive=True)
    removed = 0
    for obj in objects:
        client.remove_object(bucket, obj.object_name)
        removed += 1
    print(f"[MinIO] Удалено {removed} PDF объектов из {prefix}/")

# Параллельное скачивание pdf для 12 одновременных соединений до 3 попыток
async def download_pdf(session, url, download_map, pbar):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, timeout=60, ssl=False) as response:
                if response.status == 200 and url.lower().endswith(".pdf"):
                    pdf_bytes = await response.read()
                    file_name = f"{PDF_PREFIX}/pdf_{abs(hash(url))}.pdf"
                    client.put_object(
                        BUCKET_RAG_SOURCES,
                        file_name,
                        BytesIO(pdf_bytes),
                        length=len(pdf_bytes)
                    )
                    download_map[url] = file_name
                    pbar.update(1)
                    return
        except:
            await asyncio.sleep(2)
    print(f"[Ошибка скачивания]: {url}")
    pbar.update(1)

# Загрузка ссылок и скачивание всех pdf
async def download_all_pdfs():
    csv_obj = client.get_object(BUCKET_WEB_CRAWLER, LINKS_CSV)
    df = pd.read_csv(BytesIO(csv_obj.read()), header=None, usecols=[0], dtype=str, names=["url"])
    urls = df["url"].dropna().astype(str).str.strip().tolist()
    urls = [u for u in urls if u.lower().endswith(".pdf")]
    urls = list(dict.fromkeys(urls))
    print(f"Всего PDF ссылок: {len(urls)}")

    download_map = {}
    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT)
    async with aiohttp.ClientSession(connector=connector) as session:
        with tqdm(total=len(urls), desc="Скачивание PDF") as pbar:
            tasks = [download_pdf(session, url, download_map, pbar) for url in urls]
            await asyncio.gather(*tasks)

    return download_map

# Параллельная обработка pdf: извлечение текста, чанкинг, метаданные
def process_pdfs(download_map):
    all_chunks = []
    global_chunk_id = 0

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                extract_text_from_pdf_bytes,
                client.get_object(BUCKET_RAG_SOURCES, pdf_path).read()
            ): (url, pdf_path)
            for url, pdf_path in download_map.items()
        }

        with tqdm(total=len(futures), desc="Извлечение текста + чанки") as pbar:
            for future in as_completed(futures):
                url, pdf_path = futures[future]
                text = future.result()
                if not text:
                    pbar.update(1)
                    continue

                chunks = chunk_by_gpt_tokens(text)
                doc_id = hashlib.sha1(pdf_path.encode()).hexdigest()[:10]

                for chunk in chunks:
                    chunk.update({
                        "document_id": doc_id,
                        "source_url": url,
                        "local_pdf": pdf_path,
                        "chunk_id": global_chunk_id,
                        "chunk_uid": f"chunk_{global_chunk_id}",
                        "metadata": {
                            "source_url": url,
                            "pdf_file": pdf_path,
                            "hash": hashlib.md5(url.encode()).hexdigest(),
                            "created_at": datetime.utcnow().isoformat() + "Z"
                        }
                    })
                    all_chunks.append(chunk)
                    global_chunk_id += 1

                pbar.update(1)

    json_bytes = json.dumps({"chunks": all_chunks}, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        BUCKET_RAG_SOURCES,
        f"{CHUNKS_PREFIX}/{OUTPUT_JSON_NAME}",
        BytesIO(json_bytes),
        length=len(json_bytes)
    )
    print(f"[MinIO] Сохранено чанков: {len(all_chunks)}")

# Главная функция
async def full_update():
    print("[MinIO] Очистка PDF папки...")
    clear_pdf_prefix(BUCKET_RAG_SOURCES, PDF_PREFIX)

    print("Скачивание PDF...")
    download_map = await download_all_pdfs()

    print("Обработка PDF и создание чанков...")
    process_pdfs(download_map)

if __name__ == "__main__":
    asyncio.run(full_update())
