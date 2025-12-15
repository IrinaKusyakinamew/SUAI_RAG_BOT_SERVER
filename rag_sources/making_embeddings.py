import io
import json
from typing import List, Dict

from tqdm import tqdm
from loguru import logger
from sentence_transformers import SentenceTransformer

from minio_client import get_minio_client


# Настройки
BUCKET_SOURCE = "rag-sources"
BUCKET_TARGET = "rag-sources"

# Объекты с чанками
SCHEDULES_CHUNKS_OBJECT = "tmp_chunks_for_embeddings/schedules_chunks.json"
ALL_CHUNKS_OBJECT = "tmp_chunks_for_embeddings/all_chunks.json"

# Куда сохраняем эмбеддинги
SCHEDULES_EMBEDDINGS_OBJECT = "embeddings/schedules_chunks.jsonl"
ALL_EMBEDDINGS_OBJECT = "embeddings/all_chunks.jsonl"

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" # Поменять
DEVICE = "cpu"
BATCH_SIZE = 32


# Загрузка чанков из минио
def load_chunks(object_name: str) -> List[Dict]:
    client = get_minio_client()
    data = client.get_object(BUCKET_SOURCE, object_name).read()
    parsed = json.loads(data.decode("utf-8"))
    chunks = parsed.get("chunks", [])
    logger.info(f"Загружено {len(chunks)} чанков из {object_name}")
    return chunks


# Формирование текста для эмбеддинга
def build_text(chunk: Dict) -> str:
    # Если это расписание, расширяем метаданные
    if chunk.get("type") == "schedule":
        m = chunk.get("metadata", {})
        parts = [
            m.get("day"),
            m.get("time"),
            f"Неделя: {m.get('week')}",
            m.get("lesson_type"),
            m.get("subject"),
            f"Аудитория: {m.get('room')}",
            f"Преподаватели: {', '.join(m.get('teacher', []))}",
            f"Группы: {', '.join(m.get('groups', []))}",
            f"Кафедра {m.get('department')}",
        ]
        return ". ".join(p for p in parts if p)
    # Если другой документ
    else:
        return chunk.get("text") or ""


# Генерация эмбеддингов для списка чанков и сохранение в минио
def generate_embeddings(chunks: List[Dict], output_object: str):
    client = get_minio_client()
    model = SentenceTransformer(MODEL_NAME, device=DEVICE)

    buffer = io.StringIO()

    # Обрабатываем чанки батчами
    for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc=output_object):
        batch = chunks[i:i + BATCH_SIZE]
        # Тексы для эмбеддинга
        texts = [build_text(c) for c in batch]
        # Генерим эмбеддинги
        vectors = model.encode(texts, show_progress_bar=False)

        # Формируем структуру для jsonl
        for chunk, vector, text in zip(batch, vectors, texts):
            record = {
                "id": chunk["chunk_uid"], # ВАЖНО, чтобы прошла загрузка в qdrant
                "vector": vector.tolist(),
                "payload": {
                    "text": text,
                    "type": chunk.get("type"),
                    "document_id": chunk.get("document_id"),
                    "source_url": chunk.get("source_url"),
                    "metadata": chunk.get("metadata", {})
                }
            }
            buffer.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Конвертируем буфер в байты для загрузки в минио
    data = buffer.getvalue().encode("utf-8")

    # Сохраняем результат в минио
    client.put_object(
        bucket_name=BUCKET_TARGET,
        object_name=output_object,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json"
    )

    logger.success(f"Эмбеддинги сохранены: {output_object}")


# Главная функция, загружает все чанки и генерит для них эмбеддинги
def main():
    # Эмбеддинги чанков расписания
    generate_embeddings(
        load_chunks(SCHEDULES_CHUNKS_OBJECT),
        SCHEDULES_EMBEDDINGS_OBJECT
    )

    # Эмбеддинги остальных чанков
    generate_embeddings(
        load_chunks(ALL_CHUNKS_OBJECT),
        ALL_EMBEDDINGS_OBJECT
    )


if __name__ == "__main__":
    main()
