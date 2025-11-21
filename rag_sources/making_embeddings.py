import json
import torch
from tqdm import tqdm
from pathlib import Path
from loguru import logger
from langchain_huggingface import HuggingFaceEmbeddings
import warnings
import shutil

warnings.filterwarnings("ignore")

# Корневая директория проекта
BASE_DIR = Path(__file__).parent.parent

# Папка с временными JSON для эмбеддинга
TMP_JSON_DIR = BASE_DIR / "rag_sources" / "tmp_json_for_embedding"

# Папка для итоговых эмбеддингов
EMBEDDINGS_DIR = BASE_DIR / "rag_sources" / "embeddings"
EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Модель эмбеддингов и её параметры
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 32

def load_chunks_from_folder(folder: Path):
    """Собираем все чанки из JSON файлов в папке"""
    all_chunks = []
    json_files = sorted(folder.glob("*.json"))
    if not json_files:
        logger.warning(f"Нет файлов в {folder.resolve()}")
        return all_chunks

    for file_path in json_files:
        logger.info(f"Загрузка чанков из {file_path.name}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chunks = data.get("chunks", data if isinstance(data, list) else [])
        all_chunks.extend(chunks)
    return all_chunks

def main():
    logger.info(f"Используется модель эмбеддингов: {MODEL_NAME} ({DEVICE})")

    # Инициализация модели
    embeddings_model = HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": DEVICE},
        encode_kwargs={"normalize_embeddings": True},
    )

    # Загружаем все чанки из tmp_json_for_embedding
    chunks = load_chunks_from_folder(TMP_JSON_DIR)
    if not chunks:
        logger.error("Нет чанков для обработки!")
        return

    logger.info(f"Всего чанков: {len(chunks)}")

    output_file = EMBEDDINGS_DIR / "embeddings.jsonl"

    with open(output_file, "w", encoding="utf-8") as f_out:
        for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc="Генерация эмбеддингов", ncols=100):
            batch = chunks[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]
            uids = [c.get("chunk_uid", "") for c in batch]
            metadatas = [c.get("metadata", {}) for c in batch]

            try:
                batch_embeddings = embeddings_model.embed_documents(texts)
            except Exception as e:
                logger.warning(f"Ошибка в батче {i}: {e}")
                continue

            for uid, text, emb, metadata in zip(uids, texts, batch_embeddings, metadatas):
                record = {
                    "id": uid,
                    "text": text,
                    "embedding": emb,
                    "metadata": metadata,
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.success(f"Эмбеддинги сохранены в {output_file.resolve()}")

    # Удаляем временную папку с JSON для эмбеддинга
    if TMP_JSON_DIR.exists():
        shutil.rmtree(TMP_JSON_DIR)
        logger.info(f"🗑 Папка {TMP_JSON_DIR} удалена после создания эмбеддингов")


if __name__ == "__main__":
    main()
