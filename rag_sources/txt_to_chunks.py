import io
import json
import re
import uuid
from pathlib import Path
from tqdm import tqdm
from minio_client import get_minio_client

# ========= НАСТРОЙКИ =========
BUCKET_SOURCE = "web-crawler"
BUCKET_TARGET = "rag-sources"
TXT_PREFIX = "schedules/"
OUTPUT_OBJECT = "tmp_chunks_for_embeddings/schedules_chunks.json"


# ========= ВСПОМОГАТЕЛЬНЫЕ =========
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# Функция, находящая все уникальные группы и возвращающая список строк
def extract_group(text: str):
    pattern = r"\b[а-яА-Яa-zA-Z]*\d{3,4}[а-яА-Яa-zA-Z]*\b"
    matches = re.findall(pattern, text)
    cleaned = [m.strip(",. ") for m in matches]
    return list(set([m.lower() for m in cleaned]))


# Функция для разделения текста на верхнюю и нижнюю неделю
def split_by_week(text: str):
    """
    Разделяет текст на части для верхней (▲) и нижней (▼) недели
    Возвращает список кортежей (week_type, week_text)
    """
    result = []

    # Ищем разделитель между неделями
    # Паттерн ищет переход от ▲ к ▼
    if "▲" in text and "▼" in text:
        # Разделяем по символу ▼, но сохраняем его в тексте
        parts = text.split("▼")

        # Обрабатываем первую часть (верхняя неделя)
        if "▲" in parts[0]:
            upper_part = parts[0]
            # Находим где начинается верхняя неделя
            upper_start = upper_part.find("▲")
            result.append(("верхняя", upper_part[upper_start:]))

        # Обрабатываем вторую часть (нижняя неделя)
        if len(parts) > 1 and parts[1].strip():
            result.append(("нижняя", "▼" + parts[1]))

    return result


# ========= ЧАНКИНГ ПО ПАРАМ =========
def chunk_by_pairs(text: str):
    days_pattern = r"(Понедельник|Вторник|Среда|Четверг|Пятница|Суббота)"
    pair_pattern = r"(\d+\s+пара)"

    chunks = []
    day_blocks = re.split(days_pattern, text)

    for i in range(1, len(day_blocks), 2):
        day = day_blocks[i]
        day_text = day_blocks[i + 1]

        pair_blocks = re.split(pair_pattern, day_text)

        for j in range(1, len(pair_blocks), 2):
            time = pair_blocks[j]
            pair_content = pair_blocks[j + 1]

            # Проверяем, есть ли информация для обеих недель
            week_parts = split_by_week(pair_content)

            if week_parts:
                # Если есть разделение на недели, создаем отдельные чанки
                for week_type, week_text in week_parts:
                    full_text = normalize_text(f"{day} {time} {week_text}")

                    # Для недель уже знаем тип
                    if week_type == "верхняя":
                        week = "верхняя"
                    else:
                        week = "нижняя"

                    # ===== тип =====
                    type_match = re.search(
                        r"(Лекция|Практическое занятие|ЛР|Семинар|Лабораторное занятие)", full_text
                    )
                    lesson_type = type_match.group(1) if type_match else "не указано"

                    # ===== предмет =====
                    subject_match = re.search(
                        r"(?:Лекция|Практическое занятие|ЛР|Семинар|Лабораторное занятие)\s+(.+?)\s+ауд",
                        full_text
                    )
                    subject = subject_match.group(1) if subject_match else "не указано"

                    # ===== аудитория =====
                    room_match = re.search(r"(ауд\.[^—]+)", full_text)
                    room = room_match.group(1).strip() if room_match else "не указано"

                    # ===== преподаватели =====
                    teachers = []
                    teachers_block = re.search(
                        r"преп[:\s]+(.+?)(?:\.?\s*гр:|$)", full_text
                    )
                    if teachers_block:
                        raw = teachers_block.group(1)
                        for t in re.split(r";|,", raw):
                            t = t.strip()
                            if t:
                                teachers.append(t)

                    if not teachers:
                        teachers = ["не указано"]

                    # ===== кафедра =====
                    department_match = re.search(r"Кафедра\s+(\d+)", full_text)
                    department = department_match.group(1) if department_match else "не указано"

                    # Извлекаем группы ТОЛЬКО из week_text (части для конкретной недели)
                    groups = extract_group(week_text)

                    # Если нет групп, используем ["не указано"]
                    if not groups:
                        groups = ["не указано"]

                    # Сортируем группы для единообразия
                    groups.sort()

                    chunks.append({
                        "day": day,
                        "time": time,
                        "week": week,
                        "lesson_type": lesson_type,
                        "subject": subject,
                        "room": room,
                        "teacher": teachers,
                        "groups": groups,
                        "department": department,
                        "full_text": full_text
                    })
            else:
                # Если нет разделения на недели, создаем один чанк
                full_text = normalize_text(f"{day} {time} {pair_content}")

                # ===== неделя =====
                if "▲" in full_text:
                    week = "верхняя"
                elif "▼" in full_text:
                    week = "нижняя"
                else:
                    week = "не указано"

                # ===== тип =====
                type_match = re.search(
                    r"(Лекция|Практическое занятие|ЛР|Семинар|Лабораторное занятие)", full_text
                )
                lesson_type = type_match.group(1) if type_match else "не указано"

                # ===== предмет =====
                subject_match = re.search(
                    r"(?:Лекция|Практическое занятие|ЛР|Семинар|Лабораторное занятие)\s+(.+?)\s+ауд",
                    full_text
                )
                subject = subject_match.group(1) if subject_match else "не указано"

                # ===== аудитория =====
                room_match = re.search(r"(ауд\.[^—]+)", full_text)
                room = room_match.group(1).strip() if room_match else "не указано"

                # ===== преподаватели =====
                teachers = []
                teachers_block = re.search(
                    r"преп[:\s]+(.+?)(?:\.?\s*гр:|$)", full_text
                )
                if teachers_block:
                    raw = teachers_block.group(1)
                    for t in re.split(r";|,", raw):
                        t = t.strip()
                        if t:
                            teachers.append(t)

                if not teachers:
                    teachers = ["не указано"]

                # ===== кафедра =====
                department_match = re.search(r"Кафедра\s+(\d+)", full_text)
                department = department_match.group(1) if department_match else "не указано"

                # Извлекаем группы
                groups = extract_group(full_text)

                # Если нет групп, используем ["не указано"]
                if not groups:
                    groups = ["не указано"]

                # Сортируем группы для единообразия
                groups.sort()

                chunks.append({
                    "day": day,
                    "time": time,
                    "week": week,
                    "lesson_type": lesson_type,
                    "subject": subject,
                    "room": room,
                    "teacher": teachers,
                    "groups": groups,
                    "department": department,
                    "full_text": full_text
                })

    return chunks


# ========= ЗАГРУЗКА В MINIO =========
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


# ========= PIPELINE =========
def process_txt_from_minio():
    client = get_minio_client()
    all_chunks = []
    global_id = 0

    print(f"[INFO] Читаем {BUCKET_SOURCE}/{TXT_PREFIX}", flush=True)
    objects = list(client.list_objects(
        BUCKET_SOURCE, prefix=TXT_PREFIX, recursive=True
    ))

    for obj in tqdm(objects, desc="Processing TXT files", ncols=100):
        if not obj.object_name.endswith(".txt"):
            continue

        raw = client.get_object(BUCKET_SOURCE, obj.object_name).read()
        text = normalize_text(raw.decode("utf-8", errors="ignore"))

        pairs = chunk_by_pairs(text)
        source_file = Path(obj.object_name).name

        for pair in pairs:
            chunk_uid = str(uuid.uuid4())

            embedding_text = (
                f"{pair['day']}. {pair['time']}. {pair['week']}. "
                f"{pair['lesson_type']}. {pair['subject']}. "
                f"Аудитория: {pair['room']}. "
                f"Преподаватели: {', '.join(pair['teacher'])}. "
                f"Группы: {', '.join(pair['groups'])}. "
                f"Кафедра {pair['department']}."
            )

            all_chunks.append({
                "chunk_id": global_id,
                "chunk_uid": chunk_uid,
                "text": embedding_text,
                "document_id": source_file,
                "source_url": None,
                "type": "schedule",
                "metadata": {
                    "source": "schedule",
                    "day": pair["day"],
                    "time": pair["time"],
                    "week": pair["week"],
                    "lesson_type": pair["lesson_type"],
                    "subject": pair["subject"],
                    "room": pair["room"],
                    "teacher": pair["teacher"],
                    "groups": pair["groups"],
                    "department": pair["department"],
                    "full_text": pair["full_text"]
                }
            })

            global_id += 1

    upload_json_to_minio(
        BUCKET_TARGET,
        OUTPUT_OBJECT,
        {"chunks": all_chunks}
    )

    print(f"[INFO] Всего чанков расписания: {len(all_chunks)}", flush=True)


if __name__ == "__main__":
    process_txt_from_minio()