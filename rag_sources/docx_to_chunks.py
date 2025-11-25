import json
import re
import io
import tiktoken
from tqdm import tqdm
from datetime import datetime
import hashlib
from minio_client import get_minio_client

# Настройки путей и параметров
BUCKET_SOURCE = "web-crawler"
BUCKET_TARGET = "rag-sources"
INPUT_OBJECT = "parsed_docx.json"
OUTPUT_OBJECT = "tmp_chunks/docx_chunks.json"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

# Проверка существования бакета
def ensure_bucket(bucket_name: str):
    client = get_minio_client()
    buckets = [b.name for b in client.list_buckets()]
    if bucket_name not in buckets:
        client.make_bucket(bucket_name)

# Загрузка json из минио
def load_json_from_minio(bucket: str, object_name: str):
    client = get_minio_client()
    response = client.get_object(bucket, object_name)
    data = response.read()
    return json.loads(data.decode("utf-8"))

# Загрузка json в минио
def upload_json_to_minio(bucket: str, object_name: str, obj):
    ensure_bucket(bucket)
    client = get_minio_client()
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json"
    )

# Удаление лишних пробелов и перевод текста в аккуратный формат
def normalize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# Чанкинг по токенам gpt
def chunk_by_gpt_tokens(text, chunk_size=512, overlap=50):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)

    chunks = []
    start_idx = 0
    chunk_id = 0

    while start_idx < len(tokens):
        end_idx = min(start_idx + chunk_size, len(tokens))
        chunk_text = enc.decode(tokens[start_idx:end_idx])

        # Мягкий перенос — не обрывать на середине слова
        last_space = chunk_text.rfind(" ")
        if last_space != -1 and end_idx != len(tokens):
            chunk_text_trimmed = chunk_text[:last_space]
            new_end_idx = start_idx + len(enc.encode(chunk_text_trimmed))
            chunk_text = chunk_text_trimmed
        else:
            new_end_idx = end_idx

        # Определяем смещение чанка внутри исходного текста
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

        # Двигаемся вперёд с перекрытием
        start_idx = max(new_end_idx - overlap, new_end_idx)
        chunk_id += 1

    return chunks

# Основная функция обработки docx
def process_docx_chunks():
    documents_dict = load_json_from_minio(BUCKET_SOURCE, INPUT_OBJECT)
    all_chunks = []
    # Глобальный счетчик чанков по всем документам
    global_chunk_id = 0

    # Для каждого документа
    for doc_id, text in tqdm(documents_dict.items(), desc="Chunking documents"):
        # Приводим текст к строковому формату
        if isinstance(text, list):
            text = " ".join(map(str, text))
        elif not isinstance(text, str):
            text = str(text)

        # Нормализуем и разбиваем на чанки
        text = normalize_text(text)
        chunks = chunk_by_gpt_tokens(text, chunk_size=512, overlap=50)

        # Добавляем метаданные и уникальные идентификаторы
        for chunk in chunks:
            # id исходного документа
            chunk["document_id"] = doc_id
            # Глобальный id, уникален для всего файла
            chunk["chunk_id"] = global_chunk_id
            # Строковый uid для удобства
            chunk["chunk_uid"] = f"{global_chunk_id}_chunk"
            chunk["metadata"] = {
                "source_docx_id": doc_id,
                "source_hash": hashlib.md5(doc_id.encode()).hexdigest(),
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            all_chunks.append(chunk)
            global_chunk_id += 1

    print(f"[MinIO] Всего чанков: {len(all_chunks)}")
    upload_json_to_minio(BUCKET_TARGET, OUTPUT_OBJECT, {"chunks": all_chunks})

if __name__ == "__main__":
    process_docx_chunks()