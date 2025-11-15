import json
import re
from pathlib import Path
import tiktoken
from tqdm import tqdm

# Корень проекта
BASE_DIR = Path(__file__).parent.parent

# Папка для временных файлов-чанков
TMP_DIR = BASE_DIR / "rag_sources" / "tmp_chunks"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Исходный json с docx доками
INPUT_JSON = BASE_DIR / "parser" / "out_spider" / "spiders" / "parsed_docx.json"

# Куда сохраняем чанки
OUTPUT_JSON = TMP_DIR / "chunks_docx.json"

# Создаем папку для результата, если ее еще нет
OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

# Удаляет лишние пробелы и переводит текст в аккуратный формат
def normalize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# Разбивает текст на чанки по количеству токенов
def chunk_by_gpt_tokens(text, chunk_size=512, overlap=50):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)

    chunks = []
    start_idx = 0
    chunk_id = 0

    while start_idx < len(tokens):
        end_idx = min(start_idx + chunk_size, len(tokens))
        chunk_text = enc.decode(tokens[start_idx:end_idx])

        last_space = chunk_text.rfind(" ")
        if last_space != -1 and end_idx != len(tokens):
            chunk_text_trimmed = chunk_text[:last_space]
            new_end_idx = start_idx + len(enc.encode(chunk_text_trimmed))
            chunk_text = chunk_text_trimmed
        else:
            new_end_idx = end_idx

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

        start_idx = max(new_end_idx - overlap, new_end_idx)
        chunk_id += 1

    return chunks

# Загружаем исходный json с доками
with open(INPUT_JSON, "r", encoding="utf-8") as f:
    documents_dict = json.load(f)

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
        global_chunk_id += 1
        all_chunks.append(chunk)

# Сохраняем все чанки в json
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=2)
