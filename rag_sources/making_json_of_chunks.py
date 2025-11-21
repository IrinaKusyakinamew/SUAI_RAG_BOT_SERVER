import json
import re
import uuid
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import shutil
import tiktoken

# Папка с временными чанками
TMP_CHUNKS_DIR = Path(__file__).parent / "tmp_chunks"

# Папка для объединённых JSON перед эмбеддингом
TMP_JSON_DIR = Path(__file__).parent / "tmp_json_for_embedding"
TMP_JSON_DIR.mkdir(parents=True, exist_ok=True)

# Итоговый объединённый JSON
OUTPUT_JSON = TMP_JSON_DIR / "all_chunks.json"

# Минимальное количество токенов для сохранения ненулевых чанков (для html/pdf/docx)
MIN_TOKENS = 50

# Инициализация кодировщика для GPT токенов
ENC = tiktoken.encoding_for_model("gpt-3.5-turbo")


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def tokenize(text: str) -> int:
    """Подсчёт GPT-токенов через tiktoken"""
    return len(ENC.encode(text))


def looks_like_navigation(html_fragment: str) -> bool:
    """Простейшая фильтрация HTML навигационных блоков"""
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
    """Создаёт нормализованный объект чанка с UUID и GPT-токенами"""
    text = clean_text(chunk.get("text", ""))
    if not text:
        return None, offset

    token_count = tokenize(text)
    start_offset = offset
    end_offset = offset + len(text)
    offset = end_offset

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
            "path": source_url,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
    }
    return normalized, offset


def main():
    all_chunks = []
    global_chunk_id = 0
    stats = {"kept": 0, "removed_short": 0, "removed_structural": 0, "removed_empty": 0}

    # Собираем все JSON файлы из tmp_chunks
    input_files = sorted(TMP_CHUNKS_DIR.glob("*.json"))
    if not input_files:
        print("Нет файлов в tmp_chunks")
        return

    for file_path in input_files:
        print(f"Обрабатываем {file_path.name}...")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = data.get("chunks", data if isinstance(data, list) else [])
        offset = 0
        # Определяем тип документа
        doc_type = (
            "html" if "html" in file_path.name
            else "pdf" if "pdf" in file_path.name
            else "docx" if "docx" in file_path.name
            else "txt"
        )

        for ch in chunks:
            text = clean_text(ch.get("text", ""))
            if not text:
                stats["removed_empty"] += 1
                continue

            token_count = tokenize(text)

            # Для html/pdf/docx применяем фильтры
            if doc_type != "txt":
                if token_count < MIN_TOKENS:
                    stats["removed_short"] += 1
                    continue

                if doc_type == "html":
                    raw_html = ch.get("raw_html", ch.get("text", ""))
                    if looks_like_navigation(raw_html):
                        stats["removed_structural"] += 1
                        continue

            # Для txt сохраняем всё без фильтрации
            source_url = (
                ch.get("source_url")
                or ch.get("document_id")
                or ch.get("filename")
                or file_path.name
            )

            normalized, offset = normalize_chunk(ch, source_url, doc_type, global_chunk_id, offset)
            if normalized:
                all_chunks.append(normalized)
                global_chunk_id += 1
                stats["kept"] += 1

    # Сохраняем объединённый JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=2)

    print("\nОбработка завершена.")
    print(f"  Сохранено чанков:      {stats['kept']}")
    print(f"  Удалено коротких:      {stats['removed_short']}")
    print(f"  Удалено пустых:        {stats['removed_empty']}")
    print(f"  Удалено навигационных: {stats['removed_structural']}")
    print(f"  ➜ Итог сохранён в: {OUTPUT_JSON}")

    # Удаляем временную папку с отдельными JSON
    if TMP_CHUNKS_DIR.exists():
        shutil.rmtree(TMP_CHUNKS_DIR)
        print(f"🗑 Папка {TMP_CHUNKS_DIR} удалена")


if __name__ == "__main__":
    main()
