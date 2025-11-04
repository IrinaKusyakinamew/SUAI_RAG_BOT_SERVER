import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# Файлы с предварительно подготовленными чанками
INPUT_FILES = [
    Path("chunks_all_html.json"),
    Path("chunks_all_pdf.json"),
    Path("chunks_all_docx.json"),
]

# Итоговый объединённый файл
OUTPUT_JSON = Path("chunks.json")

# Минимальное количество токенов для сохранения чанка
MIN_TOKENS = 50


# Функции обработки

def clean_text(text: str) -> str:
    """
    Очистка текста от спецсимволов, HTML-мусора и лишних пробелов.
    """
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = text.strip()
    return text


def tokenize(text: str) -> int:
    """
    Примерная оценка количества токенов по числу слов.
    """
    return len(text.split())


def looks_like_navigation(html_fragment: str) -> bool:
    """
    Проверяет, содержит ли HTML-чанк признаки навигационного/служебного блока.
    Удаляем элементы вроде header, footer, nav, menu, aside и др.
    """
    soup = BeautifulSoup(html_fragment, "lxml")

    # Если в чанке почти нет текста, это структурный блок
    text = soup.get_text(separator=" ", strip=True)
    if len(text.split()) < 5:
        return True

    # Если чанку соответствует навигационная структура
    nav_tags = soup.find_all(["nav", "header", "footer", "aside", "menu"])
    if len(nav_tags) > 0:
        return True

    # Если состоит в основном из ссылок или кнопок
    link_ratio = len(soup.find_all("a")) / (len(text.split()) + 1)
    if link_ratio > 0.5:
        return True

    return False


def normalize_chunk(chunk: dict, source_url: str, doc_type: str, chunk_id: int, offset: int):
    """
    Формирует нормализованный словарь чанка с едиными полями и метаданными.
    """
    text = clean_text(chunk.get("text", ""))
    if not text:
        return None, offset

    token_count = tokenize(text)
    start_offset = offset
    end_offset = offset + len(text)
    offset = end_offset

    chunk_uid = f"{Path(source_url).stem[:10]}_chunk_{chunk_id}"

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


# Основная логика
all_chunks = []
global_chunk_id = 0
stats = {"kept": 0, "removed_short": 0, "removed_structural": 0, "removed_empty": 0}

for file_path in INPUT_FILES:
    if not file_path.exists():
        print(f"Пропущен {file_path} — файл не найден")
        continue

    print(f"Обрабатываем {file_path.name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks = data.get("chunks", data if isinstance(data, list) else [])
    offset = 0
    doc_type = "html" if "html" in file_path.name else "pdf" if "pdf" in file_path.name else "docx"

    for ch in chunks:
        text = clean_text(ch.get("text", ""))
        if not text:
            stats["removed_empty"] += 1
            continue

        token_count = tokenize(text)
        if token_count < MIN_TOKENS:
            stats["removed_short"] += 1
            continue

        # Проверка только для HTML — структурный мусор не сохраняем
        if doc_type == "html":
            raw_html = ch.get("raw_html", ch.get("text", ""))  # если есть оригинальный HTML
            if looks_like_navigation(raw_html):
                stats["removed_structural"] += 1
                continue

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

# Сохранение результата
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=4, separators=(",", ": "))

# Очистка промежуточных файлов
for file_path in INPUT_FILES:
    try:
        if file_path.exists():
            file_path.unlink()
            print(f"Удалён промежуточный файл: {file_path.name}")
    except Exception as e:
        print(f"Не удалось удалить {file_path.name}: {e}")

print("\nОбработка завершена.")
print(f"  Сохранено чанков:      {stats['kept']}")
print(f"  Удалено коротких:      {stats['removed_short']}")
print(f"  Удалено пустых:        {stats['removed_empty']}")
print(f"  Удалено навигационных: {stats['removed_structural']}")
print(f"  ➜ Итог сохранён в: {OUTPUT_JSON}")
