import os
import json
import warnings
from pathlib import Path
from tqdm import tqdm
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import re
import io
from html_chunking import get_html_chunks
from minio_client import get_minio_client

warnings.filterwarnings("ignore")

# Настройки бакетов и папок
BUCKET_SOURCE = "web-crawler"
BUCKET_TARGET = "rag-sources"
HTML_PREFIX = "html_pages/"
TMP_FOLDER = "tmp_chunks/"
OUTPUT_OBJECT = TMP_FOLDER + "html_chunks.json"

# Параметры обработки
MAX_TOKENS = 512
ATTR_CUTOFF_LEN = 50
CLEAN_HTML = True
MIN_WORDS = 5

# Проверка существования бакета
def ensure_bucket(bucket_name: str):
    client = get_minio_client()
    if bucket_name not in [b.name for b in client.list_buckets()]:
        client.make_bucket(bucket_name)

# Очистка html от тегов, мусора и спецсимволов
def clean_html_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[–—−]", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()

# Извлечение ссылки из html
def extract_source_url(html_content: str, html_file: Path) -> str:
    soup = BeautifulSoup(html_content, "lxml")
    og_tag = soup.find("meta", property="og:url")
    if og_tag and og_tag.get("content") and og_tag["content"].startswith(("http", "https")):
        return og_tag["content"]
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href") and canonical_tag["href"].startswith(("http", "https")):
        return canonical_tag["href"]
    a_tag = soup.find("a", href=True)
    if a_tag and a_tag["href"].startswith(("http", "https")):
        return a_tag["href"]
    return html_file.name

# Быстрая оценка количества токенов
def fast_token_count(text: str) -> int:
    return int(len(text.split()) * 1.3)

# Обработка одного html: чанкинг, очистка, метаданные
def process_html_file(html_file: Path) -> list[dict]:
    html_path, html_bytes = html_file
    try:
        html_content = html_bytes.decode("utf-8", errors="ignore")
        source_url = extract_source_url(html_content, html_path)

        # Генерируем html чанки
        chunks = get_html_chunks(
            html_content,
            max_tokens=MAX_TOKENS,
            is_clean_html=CLEAN_HTML,
            attr_cutoff_len=ATTR_CUTOFF_LEN
        )

        results = []
        start_offset = 0
        base_id = Path(html_path).stem[:10]

        for i, chunk_html in enumerate(chunks):
            text_only = clean_html_text(chunk_html)
            if len(text_only.split()) < MIN_WORDS:
                continue

            token_count = fast_token_count(text_only)
            end_offset = start_offset + len(text_only)
            now_iso = datetime.utcnow().isoformat() + "Z"

            results.append({
                "chunk_id": i,
                "chunk_uid": f"{base_id}_chunk_{i}",
                "text": text_only,
                "token_count": token_count,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "document_id": base_id,
                "source_url": source_url,
                "type": "html",
                "metadata": {
                    "source": "html",
                    "path": source_url,
                    "created_at": now_iso
                }
            })
            start_offset = end_offset

        return results
    except Exception:
        return []

# Загрузка json с чанками в минио
def upload_json_to_minio(bucket, object_name, data):
    ensure_bucket(bucket)
    client = get_minio_client()
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(encoded),
        length=len(encoded),
        content_type="application/json"
    )
    print(f"[MinIO] Загружено: {object_name}")

# Главная функция
def main():
    print("SCRIPT STARTED", flush=True)
    client = get_minio_client()

    # Список объектов HTML в бакете
    object_list = list(client.list_objects(BUCKET_SOURCE, prefix=HTML_PREFIX, recursive=True))
    html_objects = [obj for obj in object_list if obj.object_name.endswith(".html")]
    print(f"[INFO] HTML файлов найдено: {len(html_objects)}")

    all_chunks = []
    num_workers = max(2, os.cpu_count() // 2)
    print(f"[INFO] Обработка HTML файлов ({num_workers} потоков)...", flush=True)

    pbar = tqdm(total=len(html_objects), desc="Chunk HTML", ncols=100)

    # Обёртка для параллельной обработки одного объекта MinIO
    def process_object(obj):
        html_bytes = client.get_object(BUCKET_SOURCE, obj.object_name).read()
        return process_html_file((obj.object_name, html_bytes))

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(process_object, obj): obj for obj in html_objects}
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_chunks.extend(result)
            pbar.update(1)

    pbar.close()
    print(f"[INFO] Всего HTML чанков: {len(all_chunks)}", flush=True)

    # Сохраняем в MinIO в tmp_chunks
    upload_json_to_minio(BUCKET_TARGET, OUTPUT_OBJECT, {"chunks": all_chunks})

if __name__ == "__main__":
    main()
