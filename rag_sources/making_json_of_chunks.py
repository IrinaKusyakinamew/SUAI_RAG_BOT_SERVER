import io
import json
import re
import uuid
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from minio_client import get_minio_client
import tiktoken
from loguru import logger

# Настройки
BUCKET = "rag-sources"
TMP_CHUNKS_PREFIX = "tmp_chunks"  # исходные PDF/HTML/DOCX
TMP_JSON_PREFIX = "tmp_chunks_for_embeddings"  # куда сохраняем объединённый JSON

ENC = tiktoken.encoding_for_model("gpt-3.5-turbo")
MIN_TOKENS = 50

CHUNK_FILES = {"pdf_chunks.json", "docx_chunks.json", "html_chunks.json"}
SCHEDULES_FILE = "schedules_chunks.json"

client = get_minio_client()

# Функции нормализации
def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()

# Функция, находящая все уникальные группы и возвращающая список строк
def extract_group(text: str):
    pattern = r"\b[а-яА-Яa-zA-Z]*\d{3,4}[а-яА-Яa-zA-Z]*\b"
    matches = re.findall(pattern, text)
    cleaned = [m.strip(",. ") for m in matches]
    return list(set([m.lower() for m in cleaned]))


def tokenize(text: str) -> int:
    return len(ENC.encode(text))

def looks_like_navigation(html_fragment: str) -> bool:
    soup = BeautifulSoup(html_fragment, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    if len(text.split()) < 5:
        return True
    nav_tags = soup.find_all(["nav", "header", "footer", "aside", "menu"])
    if nav_tags:
        return True
    link_ratio = len(soup.find_all("a")) / (len(text.split()) + 1)
    if link_ratio > 0.5:
        return True
    return False

def normalize_chunk(chunk: dict, source_url: str, doc_type: str, chunk_id: int, offset: int):
    text = clean_text(chunk.get("text", ""))
    if not text:
        return None, offset

    token_count = tokenize(text)
    start_offset = offset
    end_offset = offset + len(text)
    offset = end_offset

    if doc_type != "txt" and token_count < MIN_TOKENS:
        return None, offset
    if doc_type == "html":
        raw_html = chunk.get("raw_html", chunk.get("text", ""))
        if looks_like_navigation(raw_html):
            return None, offset

    chunk_uid = str(uuid.uuid4())
    normalized = {
        "chunk_id": chunk_id,
        "chunk_uid": chunk_uid,
        "text": text,
        "token_count": token_count,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "document_id": source_url,
        "source_url": source_url,
        "type": doc_type,
        "metadata": {
            "source": doc_type,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    }
    return normalized, offset

def upload_json_to_minio(object_name: str, data: dict):
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        bucket_name=BUCKET,
        object_name=f"{TMP_JSON_PREFIX}/{object_name}",
        data=io.BytesIO(json_bytes),
        length=len(json_bytes),
        content_type="application/json"
    )
    logger.info(f"[MinIO] JSON загружен: {BUCKET}/{TMP_JSON_PREFIX}/{object_name}")

# Объединение и нормализация
def merge_and_normalize_chunks():
    all_chunks = []
    chunk_id_global = 0

    objects = client.list_objects(BUCKET, prefix=f"{TMP_CHUNKS_PREFIX}/", recursive=True)
    for obj in objects:
        file_name = obj.object_name.split("/")[-1]
        if file_name not in CHUNK_FILES:
            continue

        logger.info(f"Обрабатываем {file_name}...")
        data_bytes = client.get_object(BUCKET, obj.object_name).read()
        data_json = json.loads(data_bytes)
        chunks = data_json.get("chunks", data_json if isinstance(data_json, list) else [])
        offset = 0

        doc_type = "pdf" if "pdf" in file_name else "docx" if "docx" in file_name else "html"

        for ch in chunks:
            source_url = ch.get("source_url") or ch.get("document_id") or file_name
            normalized, offset = normalize_chunk(ch, source_url, doc_type, chunk_id_global, offset)
            if normalized:
                all_chunks.append(normalized)
                chunk_id_global += 1

    upload_json_to_minio("all_chunks.json", {"chunks": all_chunks})
    logger.success(f"Объединение PDF/HTML/DOCX завершено. Всего чанков: {len(all_chunks)}")

def normalize_schedules():
    try:
        data_bytes = client.get_object(BUCKET, f"{TMP_JSON_PREFIX}/{SCHEDULES_FILE}").read()
        data_json = json.loads(data_bytes)
        chunks = data_json.get("chunks", data_json if isinstance(data_json, list) else [])
        normalized_chunks = []
        offset = 0
        for i, ch in enumerate(chunks):
            source_url = ch.get("source_url") or ch.get("document_id") or SCHEDULES_FILE
            text = ch.get("text", "")
            group = extract_group(text)
            normalized, offset = normalize_chunk(
                ch,
                source_url,
                "txt",
                i,
                offset
            )

            if normalized:
                if group:
                    normalized["metadata"]["group"] = group  # добавляем группу для расписания

                normalized_chunks.append(normalized)

        upload_json_to_minio(SCHEDULES_FILE, {"chunks": normalized_chunks})
        logger.success(f"schedules_chunks.json нормализован. Всего чанков: {len(normalized_chunks)}")
    except Exception as e:
        logger.error(f"Не удалось нормализовать schedules_chunks.json: {e}")

if __name__ == "__main__":
    logger.info("Объединение и нормализация PDF/HTML/DOCX чанков ===")
    merge_and_normalize_chunks()

    logger.info("Нормализация schedules_chunks.json ===")
    normalize_schedules()
