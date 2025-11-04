import json
import torch
from tqdm import tqdm
from pathlib import Path
from loguru import logger
from langchain_huggingface import HuggingFaceEmbeddings
import warnings

warnings.filterwarnings("ignore")

# Корневая директория проекта
BASE_DIR = Path(__file__).parent.parent

# Пути к файлам
CHUNKS_FILE = BASE_DIR / "rag_sources" / "chunks.json"  # файл с чанками
OUTPUT_FILE = BASE_DIR / "rag_sources" / "embeddings.jsonl"      # итоговый файл с эмбеддингами

# Модель эмбеддингов и ее параметры
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 32 # Размер батча для одновременной обработки чанков

# Функция загрузки чанков из json файла
def load_chunks():
    logger.info(f"Загрузка чанков из {CHUNKS_FILE.resolve()}")
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(f"Файл не найден: {CHUNKS_FILE.resolve()}")
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Возвращает список словарей с текстом и метаданными
    return data.get("chunks", data)


def main():
    logger.info(f"Используется модель эмбеддингов: {MODEL_NAME} ({DEVICE})")

    # Инициализируем модель эмбеддингов через LangChain
    embeddings_model = HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": DEVICE},
        encode_kwargs={"normalize_embeddings": True}, # Нормализация векторов
    )

    chunks = load_chunks()
    logger.info(f"Всего чанков: {len(chunks)}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Открываем файл для записи результатов в jsonl: каждая строка - один объект
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        # Проходим по чанкам батчами
        for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc="Генерация эмбеддингов", ncols=100):
            batch = chunks[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]
            uids = [c.get("chunk_uid", "") for c in batch]
            metadatas = [c.get("metadata", {}) for c in batch]

            # Генерируем эмбеддинги
            try:
                batch_embeddings = embeddings_model.embed_documents(texts)
            except Exception as e:
                logger.warning(f"Ошибка в батче {i}: {e}")
                continue

            # Сохраняем каждый чанк как отдельную строку jsonl
            for uid, text, emb, metadata in zip(uids, texts, batch_embeddings, metadatas):
                record = {
                    "id": uid,
                    "text": text,
                    "embedding": emb,
                    "metadata": metadata,
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.success(f"Эмбеддинги сохранены в {OUTPUT_FILE.resolve()}")

if __name__ == "__main__":
    main()
