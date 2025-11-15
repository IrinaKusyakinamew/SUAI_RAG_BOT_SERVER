import os
import json
import re
import shutil
from pathlib import Path
import tiktoken
from tqdm import tqdm


# Текущая директория (rag_sources)
PROJECT_DIR = Path(__file__).resolve().parent

# Папка, где лежат txt файлы
TXT_DIR = PROJECT_DIR / "schedules_txt"

# Временная папка для чанков
TMP_DIR = PROJECT_DIR / "tmp_chunks"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Итоговый файл с чанками TXT
OUTPUT_JSON = TMP_DIR / "chunks_txt.json"

CHUNK_SIZE = 512   # размер чанка в токенах
CHUNK_OVERLAP = 50 # перекрытие токенов между чанками

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

        # Обрезаем до последнего пробела, чтобы не резать слова
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

        # сдвигаем start с учетом перекрытия
        start = max(new_end - overlap, new_end)
        chunk_id += 1

    return chunks


def process_all_txt():
    all_chunks = []
    global_id = 0

    txt_files = list(TXT_DIR.glob("*.txt"))

    if not txt_files:
        print("Нет txt файлов для обработки!")
        return

    for path in tqdm(txt_files, desc="Chunking TXT files"):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        text = normalize_text(text)
        chunks = chunk_by_gpt_tokens(text)

        for chunk in chunks:
            chunk["source_file"] = path.name
            chunk["global_id"] = global_id
            chunk["chunk_uid"] = f"{global_id}_txt"
            all_chunks.append(chunk)
            global_id += 1

    # сохраняем
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=2)

    print(f"TXT чанки сохранены в {OUTPUT_JSON}")

    # Удаляем исходную папку с txt файлами
    if TXT_DIR.exists():
        shutil.rmtree(TXT_DIR)
        print(f"🗑 Папка {TXT_DIR} удалена после создания JSON")


if __name__ == "__main__":
    process_all_txt()
