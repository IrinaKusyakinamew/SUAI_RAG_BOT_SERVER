import io
import json
import re
from pathlib import Path
import tiktoken
from tqdm import tqdm
from minio_client import get_minio_client

# Настройки бакетов и путей
BUCKET_SOURCE = "web-crawler"
BUCKET_TARGET = "rag-sources"
TXT_PREFIX = "schedules/"
OUTPUT_OBJECT = "tmp_chunks_for_embeddings/schedules_chunks.json"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

def normalize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def chunk_by_gpt_tokens(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)
    chunks = []
    start = 0
    chunk_id = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_text = enc.decode(tokens[start:end])

        last_space = chunk_text.rfind(" ")
        if last_space != -1 and end != len(tokens):
            trimmed = chunk_text[:last_space]
            new_end = start + len(enc.encode(trimmed))
            chunk_text = trimmed
        else:
            new_end = end

        chunks.append({
            "chunk_id": chunk_id,
            "chunk_uid": f"txt_chunk_{chunk_id}",
            "text": chunk_text.strip(),
            "token_count": len(enc.encode(chunk_text)),
        })

        start = max(new_end - overlap, new_end)
        chunk_id += 1

    return chunks

def upload_json_to_minio(bucket, object_name, data):
    client = get_minio_client()
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(encoded),
        length=len(encoded),
        content_type="application/json"
    )
    print(f"[MinIO] Загружено: {object_name}", flush=True)


def process_txt_from_minio(
        source_bucket: str = BUCKET_SOURCE,
        source_prefix: str = TXT_PREFIX,
        target_bucket: str = BUCKET_TARGET,
        output_object: str = OUTPUT_OBJECT
):

    client = get_minio_client()
    all_chunks = []
    global_id = 0

    print(f"[INFO] Начинаем обработку файлов из {source_bucket}/{source_prefix}", flush=True)
    objects = list(client.list_objects(source_bucket, prefix=source_prefix, recursive=True))

    for obj in tqdm(objects, desc="Processing TXT files", ncols=100):
        if not obj.object_name.endswith(".txt"):
            continue

        file_bytes = client.get_object(source_bucket, obj.object_name).read()
        text = file_bytes.decode("utf-8", errors="ignore")
        text = normalize_text(text)
        chunks = chunk_by_gpt_tokens(text)

        base_name = Path(obj.object_name).name
        for chunk in chunks:
            chunk["source_file"] = base_name
            chunk["global_id"] = global_id
            chunk["chunk_uid"] = f"{global_id}_txt"
            all_chunks.append(chunk)
            global_id += 1

    upload_json_to_minio(target_bucket, output_object, {"chunks": all_chunks})
    print(f"[INFO] Всего TXT чанков: {len(all_chunks)}", flush=True)

if __name__ == "__main__":
    process_txt_from_minio()
