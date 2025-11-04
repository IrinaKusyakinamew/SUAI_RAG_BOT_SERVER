import asyncio
import aiohttp
import aiofiles
import pandas as pd
import os
import json
import re
from pathlib import Path
from urllib.parse import quote
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTFigure
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
import tiktoken
import hashlib
import multiprocessing
from datetime import datetime
import shutil


from pathlib import Path

# Текущая директория, где лежит скрипт (rag_sources)
PROJECT_DIR = Path(__file__).resolve().parent

# Путь до CSV со ссылками
INPUT_CSV = PROJECT_DIR.parent / "parser" / "out_spider" / "spiders" / "links.csv"

# Директория, куда сохраняются временные и итоговые данные
BASE_DIR = PROJECT_DIR  # то есть rag_sources

# Временные папки и файлы
DOWNLOAD_DIR = BASE_DIR / "saved_pdf"
PDF_DIR = DOWNLOAD_DIR / "pdf"
MAP_PATH = DOWNLOAD_DIR / "pdf_url_map.json"
OUTPUT_JSON = BASE_DIR / "chunks_all_pdf.json"

# Параметры чанкинга и загрузки
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
MAX_CONCURRENT = 12
MAX_RETRIES = 3


# 1. Скачивание pdf
# Асинхронно скачивает один pdf документ и сохраняет в папку PDF_DIR
async def download_pdf(session, url, idx, download_map):
    encoded_url = quote(url, safe=':/?=&')
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(encoded_url, timeout=30, ssl=False) as response:
                if response.status == 200:
                    if "pdf" not in response.headers.get("Content-Type", "").lower():
                        return

                    safe_name = f"pdf_{idx}_{abs(hash(url))}.pdf"
                    file_path = PDF_DIR / safe_name

                    # Сохраняем файл, если его еще нет
                    if not file_path.exists():
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(await response.read())

                    download_map[url] = safe_name
                    return
                else:
                    raise Exception(f"HTTP {response.status}")
        except:
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1)

# Считывает csv со ссылками и скачивает все pdf файлы
async def download_all_pdfs(input_csv, download_dir):
    os.makedirs(PDF_DIR, exist_ok=True)
    df = pd.read_csv(input_csv, header=None, usecols=[0], dtype=str, names=["url"])
    urls = df["url"].dropna().astype(str).str.strip().tolist()
    urls = [u for u in urls if u.startswith(("http://", "https://"))]
    urls = list(dict.fromkeys(urls))
    print(f"Всего ссылок для скачивания: {len(urls)}")

    download_map = {}

    # Создаем сессию с ограничением числа одновременных подключений
    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [download_pdf(session, url, idx + 1, download_map) for idx, url in enumerate(urls)]
        # Отображаем процесс загрузки
        for f in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="Скачивание PDF"):
            await f

    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(download_map, f, ensure_ascii=False, indent=2)

    print(f"\nСкачивание завершено. Загружено {len(download_map)} файлов.")
    return download_map


# 2. Извлечение текста и чанкинг
# Удаляет лишние пробелы и переводит строки в единый формат
def normalize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# Разбивает текст на перекрывающиеся чанки по токенам
def chunk_by_gpt_tokens(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)
    chunks, start_idx, chunk_id = [], 0, 0

    while start_idx < len(tokens):
        end_idx = min(start_idx + chunk_size, len(tokens))
        chunk_text = enc.decode(tokens[start_idx:end_idx])

        # Стараемся не обрывать слова посередине
        last_space = chunk_text.rfind(" ")
        if last_space != -1 and end_idx != len(tokens):
            chunk_text = chunk_text[:last_space]
            end_idx = start_idx + len(enc.encode(chunk_text))

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

    # Фильтруем короткие чанки
    return [c for c in chunks if c["token_count"] >= 40]

# Определяем, не битый ли текст
def looks_like_garbage(text: str) -> bool:
    if not text:
        return True

    # 1. Проверка доли непечатаемых символов
    allowed_chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        "0123456789 .,;:-–—()[]\"'«»?!%\n\t"
    )
    garbage_ratio = sum(ch not in allowed_chars for ch in text) / max(len(text), 1)
    if garbage_ratio > 0.3:
        return True

    # 2. Проверка на повторяющиеся (cid:XXX)-паттерны
    cid_pattern = re.compile(r"\(cid:\d+\)")
    cid_matches = cid_pattern.findall(text)
    if cid_matches:
        cid_ratio = sum(len(m) for m in cid_matches) / max(len(text), 1)
        if cid_ratio > 0.1:  # если >10% текста — подозрительно
            return True

    # 3. Проверка на длинные последовательности странных символов
    strange_seq_pattern = re.compile(r"[^A-Za-zА-Яа-я0-9 .,;:\-–—()\"'«»?!%\n\t]{5,}")
    if strange_seq_pattern.search(text):
        return True

    return False


# Извлекает текст из pdf, если не получилось, использует OCR
def extract_text_from_pdf(pdf_path):
    try:
        text_parts = []

        def recursive_elements(elements):
            for el in elements:
                if isinstance(el, LTTextContainer):
                    yield el
                elif isinstance(el, LTFigure):
                    yield from recursive_elements(el._objs)

        for page_layout in extract_pages(pdf_path):
            page_text = []
            for element in recursive_elements(page_layout):
                if isinstance(element, LTTextContainer):
                    page_text.append(element.get_text().strip())
            if page_text:
                text_parts.append("\n".join(page_text))

        text = normalize_text("\n\n".join(text_parts))

        # Проверяем, не "битый" ли текст
        if not text or looks_like_garbage(text):
            print(f"[OCR] {pdf_path.name}: текст повреждён, включаем распознавание...")
            images = convert_from_path(pdf_path)
            ocr_texts = [pytesseract.image_to_string(img, config="--psm 6").strip() for img in images]
            text = normalize_text("\n\n".join(ocr_texts))

        return text
    except Exception as e:
        print(f"[Ошибка при извлечении {pdf_path.name}]: {e}")
        return ""

# Обрабатывает скачанные pdf, извлекает из них текст и делит на чанки
def process_pdfs(download_map):
    all_pdfs = list(PDF_DIR.glob("*.pdf"))
    all_chunks = []
    global_chunk_id = 0

    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(extract_text_from_pdf, pdf): pdf for pdf in all_pdfs}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Извлечение текста и чанкинг"):
            pdf_file = futures[future]
            text = future.result()
            if not text:
                continue

            # Разбиваем текст на чанки
            chunks = chunk_by_gpt_tokens(text)
            doc_id = hashlib.sha1(str(pdf_file).encode()).hexdigest()[:10]
            source_url = next((u for u, f in download_map.items() if f == pdf_file.name), None)

            # Добавляем метаданные
            for chunk in chunks:
                chunk.update({
                    "document_id": doc_id,
                    "filename": source_url or "unknown",
                    "source_url": source_url or "unknown",
                    "chunk_id": global_chunk_id,
                    "chunk_uid": f"chunk_{global_chunk_id}",
                    "metadata": {
                        "source_url": source_url or "unknown",
                        "local_filename": pdf_file.name,
                        "source_hash": hashlib.md5((source_url or pdf_file.name).encode()).hexdigest(),
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }
                })
                all_chunks.append(chunk)
                global_chunk_id += 1

    # Сохраняем чанки в json
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=2)

    print(f"\nИзвлечение завершено. Всего чанков: {len(all_chunks)}")


# 3. Полный цикл обновления
# Загрузка, обработка pdf файлов и очистка временных директорий
async def full_update():
    print("Этап 1: Скачивание PDF")
    download_map = await download_all_pdfs(INPUT_CSV, DOWNLOAD_DIR)

    print("\nЭтап 2: Извлечение текста и разбиение на чанки")
    process_pdfs(download_map)

    print("\nЭтап 3: Очистка временных директорий")
    if DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)
        print(f"Папка {DOWNLOAD_DIR} удалена.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    asyncio.run(full_update())
