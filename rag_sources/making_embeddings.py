import io
import json
import torch
from tqdm import tqdm
from loguru import logger
from langchain_huggingface import HuggingFaceEmbeddings
from minio_client import get_minio_client
import warnings

warnings.filterwarnings("ignore")

# Настройки
BUCKET_SOURCE = "rag-sources"
ALL_CHUNKS_KEY = "tmp_chunks_for_embeddings/all_chunks.json"
SCHEDULES_KEY = "tmp_chunks_for_embeddings/schedules_chunks.json"
ALL_CHUNKS_EMB_KEY = "embeddings/all_chunks.jsonl"
SCHEDULES_EMB_KEY = "embeddings/schedules_chunks.jsonl"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 32

client = get_minio_client()

# Вспомогательные функции
def load_chunks_from_minio(key: str):
    try:
        obj = client.get_object(BUCKET_SOURCE, key)
        data = json.loads(obj.read())
        chunks = data.get("chunks", data if isinstance(data, list) else [])
        logger.info(f"Загружено {len(chunks)} чанков из {key}")
        return chunks
    except Exception as e:
        logger.error(f"Не удалось загрузить {key}: {e}")
        return []

def upload_jsonl_to_minio(bucket: str, object_name: str, records):
    """Сохраняет JSONL прямо в MinIO"""
    jsonl_bytes = "\n".join(json.dumps(r, ensure_ascii=False) for r in records).encode("utf-8")
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(jsonl_bytes),
        length=len(jsonl_bytes),
        content_type="application/json"
    )
    logger.success(f"JSONL загружен в {bucket}/{object_name}")

# Генерация эмбеддингов
def generate_embeddings(chunks, key_name):
    if not chunks:
        logger.warning(f"Нет чанков для {key_name}, пропуск...")
        return

    embeddings_model = HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": DEVICE},
        encode_kwargs={"normalize_embeddings": True},
    )

    records = []
    for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc=f"Генерация эмбеддингов {key_name}", ncols=100):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        uids = [c.get("chunk_uid", str(idx)) for idx, c in enumerate(batch)]
        metadatas = [c.get("metadata", {}) for c in batch]

        try:
            batch_embeddings = embeddings_model.embed_documents(texts)
        except Exception as e:
            logger.warning(f"Ошибка в батче {i}: {e}")
            continue

        for uid, text, emb, metadata in zip(uids, texts, batch_embeddings, metadatas):
            records.append({
                "id": uid,
                "text": text,
                "embedding": emb,
                "metadata": metadata,
            })

    upload_jsonl_to_minio(BUCKET_SOURCE, key_name, records)
    logger.info(f"Эмбеддинги {key_name} созданы для {len(records)} чанков")

def main():
    logger.info(f"Используется модель эмбеддингов: {MODEL_NAME} ({DEVICE})")

    # schedules_chunks
    schedules_chunks = load_chunks_from_minio(SCHEDULES_KEY)
    generate_embeddings(schedules_chunks, SCHEDULES_EMB_KEY)

    # all_chunks
    all_chunks = load_chunks_from_minio(ALL_CHUNKS_KEY)
    generate_embeddings(all_chunks, ALL_CHUNKS_EMB_KEY)


if __name__ == "__main__":
    main()
