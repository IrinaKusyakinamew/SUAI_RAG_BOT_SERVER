import os
import json
import warnings
from pathlib import Path
from tqdm import tqdm
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import html
import re
from html_chunking import get_html_chunks

warnings.filterwarnings("ignore")

# Настройки путей
BASE_DIR = Path(__file__).parent.parent

# Папка с html-страницами
HTML_DIR = BASE_DIR / "rag_sources" / "saved_html_pages"

# Папка для временных чанков
TMP_DIR = BASE_DIR / "rag_sources" / "tmp_chunks"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Файл, куда будет сохраняться результат
OUTPUT_JSON = TMP_DIR / "chunks_html.json"

MAX_TOKENS = 512
ATTR_CUTOFF_LEN = 50
CLEAN_HTML = True
MIN_WORDS = 5

HTML_DIR.mkdir(parents=True, exist_ok=True)

# Функция очистки html
def clean_html_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[–—−]", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()

# Извлечение исходного URL
def extract_source_url(html_content: str, html_file: Path) -> str:
    soup = BeautifulSoup(html_content, "lxml")

    og_tag = soup.find("meta", property="og:url")
    if og_tag and og_tag.get("content") and og_tag["content"].startswith(("http", "https")):
        return og_tag["content"]

    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href") and canonical_tag["href"].startswith(("http", "https")):
        return canonical_tag["href"]

    a_tag = soup.find("a", href=True)
    if a_tag and a_tag["href"].startswith(("http", "https")):
        return a_tag["href"]

    return html_file.name

# Ускоренный подсчет токенов
def fast_token_count(text: str) -> int:
    return int(len(text.split()) * 1.3)

# Обработка одного html файла: извлечение текста, чанкинг
def process_html_file(html_file: Path) -> list[dict]:
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        source_url = extract_source_url(html_content, html_file)

        # Разбиваем html на фрагменты
        chunks = get_html_chunks(
            html_content,
            max_tokens=MAX_TOKENS,
            is_clean_html=CLEAN_HTML,
            attr_cutoff_len=ATTR_CUTOFF_LEN
        )

        results = []
        start_offset = 0

        # Формируем структуру каждого чанка
        for i, chunk_html in enumerate(chunks):
            text_only = clean_html_text(chunk_html)
            if len(text_only.split()) < MIN_WORDS:
                continue

            token_count = fast_token_count(text_only)
            end_offset = start_offset + len(text_only)
            now_iso = datetime.utcnow().isoformat() + "Z"

            results.append({
                "chunk_id": i,
                "chunk_uid": f"{html_file.stem[:10]}_chunk_{i}",
                "text": text_only,
                "token_count": token_count,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "document_id": OUTPUT_JSON.name,
                "source_url": source_url,
                "type": "html",
                "metadata": {
                    "source": "html",
                    "path": source_url,
                    "created_at": now_iso
                }
            })

            start_offset = end_offset

        return results

    except Exception as e:
        # Можно добавить лог ошибок
        return []

# Параллельная обработка всех файлов и сохранение результатов в json
def main():
    html_files = list(HTML_DIR.glob("*.html"))
    all_chunks = []

    num_workers = max(2, os.cpu_count() // 2)
    print(f"Запуск обработки {len(html_files)} HTML-файлов ({num_workers} процессов)...")

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(process_html_file, f): f for f in html_files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Обработка HTML", ncols=100):
            result = future.result()
            if result:
                all_chunks.extend(result)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"chunks": all_chunks}, f, ensure_ascii=False, indent=2)

    print(f"\nГотово! Всего чанков: {len(all_chunks)}")

    # Удаляем папку с исходными HTML после обработки
    if HTML_DIR.exists():
        import shutil
        shutil.rmtree(HTML_DIR)
        print(f"Папка {HTML_DIR} удалена после создания JSON")

if __name__ == "__main__":
    main()
